import json
import boto3
import uuid as uuid
from botocore.exceptions import ClientError

s3_client = boto3.client('s3')
bucket = "a3-media-folder"


def generate_presigned_url(s3_client, client_method, method_parameters, expires_in):
    """
    Generate a presigned Amazon S3 URL that can be used to perform an action.
    
    :param s3_client: A Boto3 Amazon S3 client.
    :param client_method: The name of the client method that the URL performs.
    :param method_parameters: The parameters of the specified client method.
    :param expires_in: The number of seconds the presigned URL is valid for.
    :return: The presigned URL.
    """
    try:
        url = s3_client.generate_presigned_url(
            ClientMethod=client_method,
            Params=method_parameters,
            ExpiresIn=expires_in
        )
    except ClientError:
        print(f"Couldn't get a presigned URL for client method '{client_method}'.")
        raise
    return url


def lambda_handler(event, context):
    # TODO implement
    args = json.loads(event['body'])
    type = args['type']
    suffix = args['suffix']
    # The presigned URL is specified to expire in 1000 seconds
    unique_id = uuid.uuid4()
    url = generate_presigned_url(
        s3_client, 
        "put_object", 
        {"Bucket": bucket, "Key": f"{type}/{unique_id}.{suffix}"}, 
        1000
    )

    return {
        'statusCode': 200,
        "headers": {"Content-Type": "text/plain"},
        'body': json.dumps({'url': url})
    }
