import json
import boto3
from boto3.dynamodb.conditions import Attr
from urllib.parse import urlparse

dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table('media3')  
s3 = boto3.client('s3')  

def lambda_handler(event, context):
    #Check path and method
    path = event.get('path', '')
    http_method = event.get('httpMethod', '')
    
    if path == '/api/delete-files' and http_method == 'POST':
        return handle_delete_files(event)
    else:
        return {
            'statusCode': 404,
            'body': json.dumps({'error': 'Not found'})
        }

def handle_delete_files(event):
    try:
        #Parse request
        body = json.loads(event.get('body', '{}'))
        urls = body.get('urls', [])
        
        if not isinstance(urls, list) or not urls:
            return {
                'statusCode': 400,
                'body': json.dumps({'error': 'urls must be a non-empty list'})
            }
        
        deleted_items = []
        failed_items = []
        
        for url in urls:
            #Find matching s3-url or thumbnailurl
            response = table.scan(
                FilterExpression=Attr('thumbnailurl').eq(url) | Attr('s3-url').eq(url)
            )
            
            if not response['Items']:
                failed_items.append({'url': url, 'reason': 'Not found in DB'})
                continue
            
            item = response['Items'][0]
            key = {'s3-url': item['s3-url']}
            deleted_files = []
            
            #Delete main file
            if 's3-url' in item:
                try:
                    parsed = urlparse(item['s3-url'])
                    
                    #extract bucket name and object key
                    if '.s3.' in parsed.netloc:
                        #Format: bucket-name.s3.region.amazonaws.com/key
                        bucket_name = parsed.netloc.split('.s3.')[0]
                        file_key = parsed.path.lstrip('/')
                        
                        s3.delete_object(Bucket=bucket_name, Key=file_key)
                        deleted_files.append(item['s3-url'])
                    else:
                        failed_items.append({'url': item['s3-url'], 'reason': 'Invalid S3 URL format'})
                except Exception as e:
                    failed_items.append({'url': item['s3-url'], 'reason': str(e)})
            
            #Delete thumbnail
            if 'thumbnailurl' in item:
                try:
                    parsed_thumb = urlparse(item['thumbnailurl'])
                    
                    #extract thumbnail bucket name and object key
                    if '.s3.' in parsed_thumb.netloc:
                        bucket_thumb = parsed_thumb.netloc.split('.s3.')[0]
                        thumb_key = parsed_thumb.path.lstrip('/')
                        
                        s3.delete_object(Bucket=bucket_thumb, Key=thumb_key)
                        deleted_files.append(item['thumbnailurl'])
                    else:
                        failed_items.append({'url': item['thumbnailurl'], 'reason': 'Invalid thumbnail URL format'})
                except Exception as e:
                    failed_items.append({'url': item['thumbnailurl'], 'reason': str(e)})
            
            #Delete item from DynamoDB
            try:
                table.delete_item(Key=key)
                deleted_items.append({'s3-url': item['s3-url'], 'deleted_files': deleted_files})
            except Exception as e:
                failed_items.append({'url': url, 'reason': 'DB delete failed: ' + str(e)})
        
        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
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