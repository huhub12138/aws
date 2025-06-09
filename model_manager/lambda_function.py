import json
import boto3
import os
from botocore.exceptions import ClientError

s3_client = boto3.client('s3')
dynamodb = boto3.resource('dynamodb')

# Model configuration table
MODEL_CONFIG_TABLE = os.environ.get('MODEL_CONFIG_TABLE', 'model-configurations')

def lambda_handler(event, context):
    """
    Lambda function to handle model updates and configuration
    Supports updating model files without changing source code
    """
    try:
        # Parse the incoming request
        http_method = event.get('httpMethod', 'GET')
        
        if http_method == 'GET':
            return get_model_config(event)
        elif http_method == 'POST':
            return update_model_config(event)
        elif http_method == 'PUT':
            return upload_new_model(event)
        else:
            return {
                'statusCode': 405,
                'body': json.dumps({'error': 'Method not allowed'})
            }
            
    except Exception as e:
        return {
            'statusCode': 500,
            'body': json.dumps({'error': str(e)})
        }


def get_model_config(event):
    """Get current model configurations"""
    try:
        table = dynamodb.Table(MODEL_CONFIG_TABLE)
        
        # Get all model configurations
        response = table.scan()
        
        models = {}
        for item in response.get('Items', []):
            models[item['model_type']] = {
                'version': item['version'],
                'model_path': item['model_path'],
                'config': item.get('config', {}),
                'last_updated': item.get('last_updated'),
                'is_active': item.get('is_active', True)
            }
        
        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({
                'success': True,
                'models': models
            })
        }
        
    except Exception as e:
        return {
            'statusCode': 500,
            'body': json.dumps({'error': f'Failed to get model config: {str(e)}'})
        }


def update_model_config(event):
    """Update model configuration without changing code"""
    try:
        body = json.loads(event.get('body', '{}'))
        model_type = body.get('model_type')  # 'yolo', 'birdnet', etc.
        model_path = body.get('model_path')  # S3 path to new model
        version = body.get('version')
        config = body.get('config', {})
        
        if not all([model_type, model_path, version]):
            return {
                'statusCode': 400,
                'body': json.dumps({'error': 'Missing required parameters'})
            }
        
        table = dynamodb.Table(MODEL_CONFIG_TABLE)
        
        # Update model configuration
        from datetime import datetime
        response = table.put_item(
            Item={
                'model_type': model_type,
                'version': version,
                'model_path': model_path,
                'config': config,
                'last_updated': datetime.now().isoformat(),
                'is_active': True
            }
        )
        
        # Trigger Lambda function updates
        update_lambda_environment(model_type, model_path, version)
        
        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({
                'success': True,
                'message': f'Model {model_type} updated to version {version}'
            })
        }
        
    except Exception as e:
        return {
            'statusCode': 500,
            'body': json.dumps({'error': f'Failed to update model config: {str(e)}'})
        }


def upload_new_model(event):
    """Handle new model file uploads"""
    try:
        body = json.loads(event.get('body', '{}'))
        model_type = body.get('model_type')
        file_name = body.get('file_name')
        
        if not all([model_type, file_name]):
            return {
                'statusCode': 400,
                'body': json.dumps({'error': 'Missing model_type or file_name'})
            }
        
        # Generate presigned URL for model upload
        bucket = os.environ.get('MODEL_S3_BUCKET', 'bird-detection-bucket')
        key = f"models/{model_type}/{file_name}"
        
        presigned_url = s3_client.generate_presigned_url(
            'put_object',
            Params={'Bucket': bucket, 'Key': key},
            ExpiresIn=3600  # 1 hour
        )
        
        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({
                'success': True,
                'upload_url': presigned_url,
                'model_path': f"s3://{bucket}/{key}"
            })
        }
        
    except Exception as e:
        return {
            'statusCode': 500,
            'body': json.dumps({'error': f'Failed to create upload URL: {str(e)}'})
        }


def update_lambda_environment(model_type, model_path, version):
    """Update Lambda function environment variables with new model paths"""
    try:
        lambda_client = boto3.client('lambda')
        
        # Map model types to Lambda function names
        function_mapping = {
            'yolo': os.environ.get('IMAGE_DETECTOR_FUNCTION', 'bird-image-detector'),
            'birdnet': os.environ.get('AUDIO_DETECTOR_FUNCTION', 'bird-audio-detector')
        }
        
        function_name = function_mapping.get(model_type)
        if not function_name:
            return
        
        # Get current function configuration
        response = lambda_client.get_function_configuration(FunctionName=function_name)
        
        # Update environment variables
        env_vars = response.get('Environment', {}).get('Variables', {})
        env_vars[f'{model_type.upper()}_MODEL_PATH'] = model_path
        env_vars[f'{model_type.upper()}_MODEL_VERSION'] = version
        
        # Update the function
        lambda_client.update_function_configuration(
            FunctionName=function_name,
            Environment={'Variables': env_vars}
        )
        
        print(f"Updated {function_name} with new model path: {model_path}")
        
    except Exception as e:
        print(f"Failed to update Lambda environment: {str(e)}")


def get_active_model_path(model_type):
    """Helper function to get the current active model path"""
    try:
        table = dynamodb.Table(MODEL_CONFIG_TABLE)
        response = table.get_item(Key={'model_type': model_type})
        
        if 'Item' in response and response['Item'].get('is_active'):
            return response['Item']['model_path']
        else:
            # Return default model path
            defaults = {
                'yolo': './model.pt',
                'birdnet': './BirdNET_GLOBAL_6K_V2.4_Model_FP32.tflite'
            }
            return defaults.get(model_type)
            
    except Exception as e:
        print(f"Error getting model path: {str(e)}")
        return None 