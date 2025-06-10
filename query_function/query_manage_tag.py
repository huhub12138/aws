import json
import boto3
from decimal import Decimal
from boto3.dynamodb.conditions import Attr


dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table('media3')  

def lambda_handler(event, context):
    #Check path and method
    path = event.get('path', '')
    http_method = event.get('httpMethod', '')
    
    if path == '/api/manage-tags' and http_method == 'POST':
        return manage_tags(event)
    else:
        return {
            'statusCode': 404,
            'body': json.dumps({'error': 'Not found'})
        }

def manage_tags(event):
    try:
        #Parse request 
        body = json.loads(event['body'])
        
        urls = body.get('url', [])
        operation = body.get('operation')  # 1: add, 0: remove
        tag_list = body.get('tags', [])
        
        #Validate input 
        if not isinstance(urls, list):
            return {'statusCode': 400, 'body': json.dumps({'error': 'url must be a list'})}
        if operation not in [0, 1]:
            return {'statusCode': 400, 'body': json.dumps({'error': 'operation must be 0 or 1'})}
        if not isinstance(tag_list, list):
            return {'statusCode': 400, 'body': json.dumps({'error': 'tags must be a list'})}
        
        updated_urls = []
        
        for url in urls:
            #Find matching thumbnail URL
            response = table.scan(FilterExpression=Attr('thumbnailurl').eq(url))
            if not response['Items']:
                continue
            
            item = response['Items'][0]
            key = {'s3-url': item['s3-url']}  
            
            #Initialize tags
            tags = {}
            if 'tags' in item and isinstance(item['tags'], dict):
                for k, v in item['tags'].items():
                    try:
                        if isinstance(v, Decimal):
                            tags[k] = int(v)
                        elif isinstance(v, (int, float, str)):
                            tags[k] = int(v)
                        elif isinstance(v, dict) and 'N' in v:
                            tags[k] = int(v['N'])
                        else:
                            tags[k] = 0
                    except (ValueError, TypeError):
                        tags[k] = 0
            
            #Process tag 
            for tag_entry in tag_list:
                if not isinstance(tag_entry, str):
                    continue
                parts = tag_entry.split(',')
                if len(parts) != 2:
                    continue
                
                tag = parts[0].strip()
                if not tag:
                    continue
                
                try:
                    count = max(0, int(parts[1]))
                except (ValueError, TypeError):
                    continue
                
                if operation == 1:  #add
                    tags[tag] = tags.get(tag, 0) + count
                else:  #remove
                    current_count = tags.get(tag, 0)
                    new_count = max(0, current_count - count)
                    if new_count > 0:
                        tags[tag] = new_count
                    elif tag in tags:
                        del tags[tag]
            
            #Update DB
            table.update_item(
                Key=key,
                UpdateExpression='SET tags = :t',
                ExpressionAttributeValues={
                    ':t': {k: Decimal(str(v)) for k, v in tags.items()}
                }
            )
            
            updated_urls.append(url)

         #Return successful response
        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({
                'message': 'Batch labeling operation completed',
                'updated_urls': updated_urls,
                'updated_count': len(updated_urls)
            })
        }
    #Handle JSON parsing errors
    except json.JSONDecodeError:
        return {
            'statusCode': 400,
            'body': json.dumps({'error': 'The request body contains invalid JSON format'})
        }
    #Handle unexpected errors
    except Exception as e:
        return {
            'statusCode': 500,
            'body': json.dumps({'error': f'Internal server error: {str(e)}'})
        }
