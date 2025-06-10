import json
import boto3
from boto3.dynamodb.conditions import Key, Attr
from urllib.parse import urlparse

dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table('BirdFiles')  


def lambda_handler(event, context):
    http_method = event['httpMethod']
    path = event['path']

    if path == '/api/search' and http_method == 'GET':
        return handle_search(event)

    elif path == '/api/search-by-species' and http_method == 'GET':
        return handle_species_search(event)

    elif path == '/api/search-by-thumbnail' and http_method == 'GET':
        return handle_thumbnail_search(event)

    elif path == '/api/file-based-search' and http_method == 'POST':
        return handle_file_search(event)

    elif path == '/api/tags' and http_method == 'POST':
        return handle_bulk_tags(event)

    elif path == '/api/files' and http_method == 'DELETE':
        return handle_delete_files(event)

    else:
        return {
            'statusCode': 400,
            'body': json.dumps({'error': 'Invalid request'})
        }

def handle_search(event):

    try:
        query_params = event.get('queryStringParameters', {})
        
        # 只接受tags参数
        if 'tags' not in query_params:
            return {
                'statusCode': 400,
                'body': json.dumps({'error': 'Missing tags parameter'})
            }
        
        try:
            tags = json.loads(query_params['tags'])
        except json.JSONDecodeError:
            return {
                'statusCode': 400,
                'body': json.dumps({'error': 'Invalid tags JSON format'})
            }
        
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
        
        # Query conditions
        filter_expr = None
        for species, min_count in tags.items():
            condition = Attr(f'detections.{species}').gte(min_count)
            filter_expr = condition if filter_expr is None else filter_expr & condition
        
        #Execute the query and return the results
        response = table.scan(
            FilterExpression=filter_expr,
            ProjectionExpression="file_url,thumbnail_url,file_type,detections"
        )
        
        results = {'images': [], 'videos': []}
        for item in response.get('Items', []):
            file_info = {
                'url': item['file_url'],
                'detections': item.get('detections', {})
            }
            if item['file_type'] == 'image':
                file_info['thumbnail_url'] = item['thumbnail_url']
                results['images'].append(file_info)
            elif item['file_type'] == 'video':
                results['videos'].append(file_info)
        
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
        
def handle_species_search(event):
    try:
        #Parsing query parameters
        query_params = event.get('queryStringParameters', {})
        
        if not query_params or 'species' not in query_params:
            return {
                'statusCode': 400,
                'body': json.dumps({'error': 'Species parameter is required'})
            }
        
        species = query_params['species']
        
        #Checking if a nested field exists using AttributePath
        response = table.scan(
            FilterExpression=Attr(f'detections.{species}').exists()
        )
        
        #Collating results
        results = []
        for item in response['Items']:
            if 'thumbnail_url' in item:
                results.append(item['thumbnail_url'])
            else:
                results.append(item['file_url'])
        
        #Handling Paging
        while 'LastEvaluatedKey' in response:
            response = table.scan(
                FilterExpression=Attr(f'detections.{species}').exists(),
                ExclusiveStartKey=response['LastEvaluatedKey']
            )
            for item in response['Items']:
                if 'thumbnail_url' in item:
                    results.append(item['thumbnail_url'])
                else:
                    results.append(item['file_url'])
        
        return {
            'statusCode': 200,
            'body': json.dumps({'links': results})
        }

    except Exception as e:
        return {
            'statusCode': 500,
            'body': json.dumps({'error': str(e)})
        }

def handle_thumbnail_search(event):
    try:
        query_params = event.get('queryStringParameters', {})
        if not query_params or 'thumbnail_url' not in query_params:
            return {
                'statusCode': 400,
                'body': json.dumps({'error': 'thumbnail_url parameter is required'})
            }

        thumbnail_url = query_params['thumbnail_url']

        #Query DynamoDB for records matching thumbnail_url
        response = table.scan(
            FilterExpression=Attr('thumbnail_url').eq(thumbnail_url)
        )

        items = response.get('Items', [])
        if not items:
            return {
                'statusCode': 404,
                'body': json.dumps({'error': 'No matching file found'})
            }

        item = items[0]
        result = {
            'file_url': item['file_url'],
            'file_type': item.get('file_type', 'unknown')
        }

        return {
            'statusCode': 200,
            'body': json.dumps(result)
        }

    except Exception as e:
        return {
            'statusCode': 500,
            'body': json.dumps({'error': str(e)})
        }
def handle_file_search(event):
    try:
        #Parsing JSON
        body = event.get('body', '{}')
        if event.get('isBase64Encoded'):
            body = base64.b64decode(body).decode('utf-8')
        payload = json.loads(body)

        if 'tags' not in payload:
            return {
                'statusCode': 400,
                'body': json.dumps({'error': 'Missing tags field in request'})
            }

        tags = payload['tags']
        if not isinstance(tags, dict):
            return {
                'statusCode': 400,
                'body': json.dumps({'error': 'tags must be a dictionary'})
            }

        #query conditions
        filter_expr = None
        for species, min_count in tags.items():
            if not isinstance(min_count, (int, float)):
                return {
                    'statusCode': 400,
                    'body': json.dumps({'error': f'Invalid count for {species}'})
                }
            condition = Attr(f'detections.{species}').gte(min_count)
            filter_expr = condition if filter_expr is None else filter_expr & condition

        #DynamoDB Scan Query
        response = table.scan(
            FilterExpression=filter_expr,
            ProjectionExpression="file_url, thumbnail_url, file_type, detections"
        )

        results = {'images': [], 'videos': []}
        for item in response.get('Items', []):
            file_info = {
                'url': item['file_url'],
                'detections': {k: str(v) for k, v in item.get('detections', {}).items()}
            }
            if item['file_type'] == 'image':
                file_info['thumbnail_url'] = item['thumbnail_url']
                results['images'].append(file_info)
            elif item['file_type'] == 'video':
                results['videos'].append(file_info)

        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps(results)
        }

    except Exception as e:
        return {
            'statusCode': 500,
            'body': json.dumps({'error': 'Internal server error', 'details': str(e)})
        }

from boto3.dynamodb.conditions import Attr
from decimal import Decimal
from boto3.dynamodb.types import TypeSerializer



def handle_bulk_tags(event):
    try:
        body = json.loads(event['body'])

        urls = body.get('url', [])
        operation = body.get('operation')  # 1: add, 0: remove
        tag_list = body.get('tags', [])

        if not isinstance(urls, list):
            return {'statusCode': 400, 'body': json.dumps({'error': 'url must be a list'})}
        if operation not in [0, 1]:
            return {'statusCode': 400, 'body': json.dumps({'error': 'operation must be 0 or 1'})}
        if not isinstance(tag_list, list):
            return {'statusCode': 400, 'body': json.dumps({'error': 'tags must be a list'})}

        updated_urls = []

        for url in urls:
            response = table.scan(FilterExpression=Attr('thumbnail_url').eq(url))
            if not response['Items']:
                continue

            item = response['Items'][0]
            key = {'MediaID': item['MediaID']}

            #Initialize detections
            detections = {}
            if 'detections' in item and isinstance(item['detections'], dict):
                for k, v in item['detections'].items():
                    try:
                        if isinstance(v, Decimal):
                            detections[k] = int(v)
                        elif isinstance(v, (int, float, str)):
                            detections[k] = int(v)
                        elif isinstance(v, dict) and 'N' in v:
                            detections[k] = int(v['N'])
                        else:
                            detections[k] = 0
                    except (ValueError, TypeError):
                        detections[k] = 0

            #Handling tag operations
            for tag_entry in tag_list:
                if not isinstance(tag_entry, str):
                    continue
                parts = tag_entry.split(',')
                if len(parts) != 2:
                    continue

                tag = parts[0].strip().lower()
                if not tag:
                    continue

                try:
                    count = max(0, int(parts[1]))
                except (ValueError, TypeError):
                    continue

                if operation == 1:  #add
                    detections[tag] = detections.get(tag, 0) + count
                else:  #delet
                    current_count = detections.get(tag, 0)
                    new_count = max(0, current_count - count)
                    if new_count > 0:
                        detections[tag] = new_count
                    elif tag in detections:
                        del detections[tag]

            # Writing to DynamoDB
            table.update_item(
                Key=key,
                UpdateExpression='SET detections = :d',
                ExpressionAttributeValues={
                    ':d': {k: Decimal(str(v)) for k, v in detections.items()}
                }
            )

            updated_urls.append(url)

        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': 'Batch labeling operation completed',
                'updated_urls': updated_urls,
                'updated_count': len(updated_urls)
            })
        }

    except json.JSONDecodeError:
        return {
            'statusCode': 400,
            'body': json.dumps({'error': 'The request body contains invalid JSON format'})
        }
    except Exception as e:
        return {
            'statusCode': 500,
            'body': json.dumps({'error': f'Internal server error: {str(e)}'})
        }

def handle_delete_files(event):
    try:
        body = json.loads(event.get('body', '{}'))
        urls = body.get('urls', [])

        if not isinstance(urls, list) or not urls:
            return {
                'statusCode': 400,
                'body': json.dumps({'error': 'urls must be a non-empty list'})
            }

        s3 = boto3.client('s3')
        deleted_items = []
        failed_items = []

        for url in urls:
            #Find matching file_url or thumbnail_url
            response = table.scan(
                FilterExpression=Attr('file_url').eq(url) | Attr('thumbnail_url').eq(url)
            )

            if not response['Items']:
                failed_items.append({'url': url, 'reason': 'Not found in DB'})
                continue

            item = response['Items'][0]
            key = {'MediaID': item['MediaID']}
            deleted_files = []

            # Delete file_url from S3
            parsed = urlparse(item['file_url'])
            bucket_name = parsed.netloc.split('.')[0]
            file_key = parsed.path.lstrip('/')
            try:
                s3.delete_object(Bucket=bucket_name, Key=file_key)
                deleted_files.append(item['file_url'])
            except Exception as e:
                failed_items.append({'url': item['file_url'], 'reason': str(e)})

            #Remove thumbnail_url (if it is an image)
            if item.get('file_type') == 'image' and 'thumbnail_url' in item:
                parsed_thumb = urlparse(item['thumbnail_url'])
                bucket_thumb = parsed_thumb.netloc
                thumb_key = parsed_thumb.path.lstrip('/')
                try:
                    s3.delete_object(Bucket=bucket_thumb, Key=thumb_key)
                    deleted_files.append(item['thumbnail_url'])
                except Exception as e:
                    failed_items.append({'url': item['thumbnail_url'], 'reason': str(e)})

            #Deleting from DynamoDB
            try:
                table.delete_item(Key=key)
                deleted_items.append({'MediaID': item['MediaID'], 'deleted_files': deleted_files})
            except Exception as e:
                failed_items.append({'url': url, 'reason': 'DB delete failed: ' + str(e)})

        return {
            'statusCode': 200,
            'body': json.dumps({
                'deleted': deleted_items,
                'failed': failed_items
            })
        }

    except json.JSONDecodeError:
        return {
            'statusCode': 400,
            'body': json.dumps({'error': 'Invalid JSON'})
        }
    except Exception as e:
        return {
            'statusCode': 500,
            'body': json.dumps({'error': str(e)})
        }
