import json
import boto3
from boto3.dynamodb.conditions import Key, Attr
from urllib.parse import urlparse

dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table('media3')  


def lambda_handler(event, context):
    http_method = event['httpMethod']
    path = event['path']

    if path == '/api/tag-count-search' and http_method == 'GET':
        return tag_count_search(event)

    elif path == '/api/species-tag-search' and http_method == 'GET':
        return species_tag_search(event)

    elif path == '/api/thumbnailurl-to-s3url' and http_method == 'GET':
        return thumbnailurl_to_s3url(event)

    else:
        return {
            'statusCode': 400,
            'body': json.dumps({'error': 'Invalid request'})
        }
def tag_count_search(event):
    try:
        query_params = event.get('queryStringParameters', {})
        
        #Check if tags parameter exists
        if 'tags' not in query_params:
            return {
                'statusCode': 400,
                'body': json.dumps({'error': 'Missing tags parameter'})
            }
        #Parse JSON tags parameter
        try:
            tags = json.loads(query_params['tags'])
        except json.JSONDecodeError:
            return {
                'statusCode': 400,
                'body': json.dumps({'error': 'Invalid tags JSON format'})
            }
        
        #Ensure tags is a dictionary
        if not isinstance(tags, dict):
            return {
                'statusCode': 400,
                'body': json.dumps({'error': 'Tags should be a JSON object'})
            }
        
        #Verify that the tag value is a number
        for species, count in tags.items():
            if not isinstance(count, (int, float)):
                return {
                    'statusCode': 400,
                    'body': json.dumps({'error': f'Count for {species} must be a number'})
                }
        
        #Filter with AND logic 
        filter_expr = None
        for species, min_count in tags.items():
            condition = Attr(f'tags.{species}').gte(min_count)
            filter_expr = condition if filter_expr is None else filter_expr & condition
        
        #Execute the query and get the results - using expression attribute names for s3-url
        response = table.scan(
            FilterExpression=filter_expr,
            ProjectionExpression="#s3url,thumbnailurl,filetype,tags",
            ExpressionAttributeNames={
                "#s3url": "s3-url"
            }
        )
        
        #Make results by file type
        results = {'images': [], 'videos': []}
        for item in response.get('Items', []):
            file_info = {
                'url': item['s3-url'], 
                'tags': item.get('tags', {})  
            }
            if item['filetype'] == 'image':  
                file_info['thumbnailurl'] = item['thumbnailurl']  
                results['images'].append(file_info)
            elif item['filetype'] == 'video': 
                results['videos'].append(file_info)

        #Return success response
        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps(results, default=str)
        }
    
    #Handle unexpected errors
    except Exception as e:
        return {
            'statusCode': 500,
            'body': json.dumps({
                'error': 'Internal server error',
                'details': str(e)
            })
        }
def species_tag_search(event):
    try:
        #Parsing query parameters
        query_params = event.get('queryStringParameters', {})
        
        if not query_params or 'tags' not in query_params:
            return {
                'statusCode': 400,
                'body': json.dumps({'error': 'Species parameter is required'})
            }
        
        species = query_params['tags']
        
        #Checking if the species exists in tags using AttributePath
        response = table.scan(
            FilterExpression=Attr(f'tags.{species}').exists(),
            ProjectionExpression="#s3url,thumbnailurl,filetype,tags",
            ExpressionAttributeNames={
                "#s3url": "s3-url"
            }
        )
        
        #Organize results by file type
        results = {'images': [], 'videos': [], 'audios': []}
        
        for item in response['Items']:
            file_info = {
                'url': item['s3-url'],
                'tags': item.get('tags', {})
            }
            
            #Categorize by file type
            if item['filetype'] == 'image':
                file_info['thumbnailurl'] = item['thumbnailurl']
                results['images'].append(file_info)
            elif item['filetype'] == 'video':
                results['videos'].append(file_info)
            elif item['filetype'] == 'audio':
                results['audios'].append(file_info)
        
        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps(results, default=str)
        }
    
    except Exception as e:
        return {
            'statusCode': 500,
            'body': json.dumps({
                'error': 'Internal server error',
                'details': str(e)
            })
        }
def thumbnailurl_to_s3url(event):
    try:
        query_params = event.get('queryStringParameters', {})
        if not query_params or 'thumbnailurl' not in query_params:
            return {
                'statusCode': 400,
                'body': json.dumps({'error': 'thumbnail url parameter is required'})
            }
        
        thumbnailurl = query_params['thumbnailurl']
        
        # Query DynamoDB for records matching thumbnailurl
        response = table.scan(
            FilterExpression=Attr('thumbnailurl').eq(thumbnailurl),
            ProjectionExpression="#s3url,filetype,tags",
            ExpressionAttributeNames={
                "#s3url": "s3-url"
            }
        )
        
        items = response.get('Items', [])
        if not items:
            return {
                'statusCode': 404,
                'body': json.dumps({'error': 'No matching file found'})
            }
        
        item = items[0]
        result = {
            'original_url': item['s3-url'],
            'filetype': item.get('filetype', 'unknown'),
            'tags': item.get('tags', {})
        }
        
        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps(result, default=str)
        }
    
    except Exception as e:
        return {
            'statusCode': 500,
            'body': json.dumps({
                'error': 'Internal server error',
                'details': str(e)
            })
        }
