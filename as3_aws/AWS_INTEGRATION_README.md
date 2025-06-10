# AWS Lambda Integration Guide

## Overview

This project has successfully integrated AWS Lambda functions to implement the following features:

1. **File Upload to S3** - Direct upload to S3 using presigned URLs
2. **Image/Video Detection** - Bird detection using YOLO model
3. **Audio Detection** - Audio recognition using BirdNET model
4. **Result Storage** - Detection results stored in DynamoDB

## Architecture Flow

```
Frontend Upload → Get Presigned URL → Direct Upload to S3 → Trigger Lambda Detection → Store Results in DynamoDB → Frontend Retrieves Results
```

## Required AWS Resources

### 1. S3 Bucket
- Name: `a3-media-folder`
- Folder structure:
  - `images/` - Image files
  - `videos/` - Video files  
  - `audios/` - Audio files
  - `thumbnails/` - Thumbnail images

### 2. Lambda Functions
- `upload-function` - Generate presigned URLs
- `image-detector` - Image/video detection
- `audio-detector` - Audio detection

### 3. DynamoDB Table
- Table name: `media`
- Primary key: `s3-url` (String)
- Attributes: `tags` (Map)

## Environment Variable Configuration

Set the following variables in your environment:

```bash
# AWS Credentials
AWS_ACCESS_KEY_ID=your_access_key
AWS_SECRET_ACCESS_KEY=your_secret_key
AWS_DEFAULT_REGION=us-east-1

# S3 Configuration
AWS_S3_BUCKET=a3-media-folder

# Lambda ARNs (update with actual ARNs)
UPLOAD_LAMBDA_ARN=arn:aws:lambda:us-east-1:your-account:function:upload-function
IMAGE_DETECTOR_ARN=arn:aws:lambda:us-east-1:your-account:function:image-detector  
AUDIO_DETECTOR_ARN=arn:aws:lambda:us-east-1:your-account:function:audio-detector

# DynamoDB
DYNAMODB_TABLE=media
```

## Deployment Steps

### 1. Install Dependencies
```bash
cd as3_aws
pip install -r requirements.txt
```

### 2. Deploy Lambda Functions
```bash
# Deploy upload function
cd ../upload_function
zip -r upload-function.zip .
aws lambda create-function --function-name upload-function --runtime python3.9 --role arn:aws:iam::account:role/lambda-role --handler upload_lambda.lambda_handler --zip-file fileb://upload-function.zip

# Deploy image detection function  
cd ../Img_dectector
# Build and deploy container image according to Dockerfile

# Deploy audio detection function
cd ../audio_dectector  
zip -r audio-detector.zip .
aws lambda create-function --function-name audio-detector --runtime python3.9 --role arn:aws:iam::account:role/lambda-role --handler lambda.handler --zip-file fileb://audio-detector.zip
```

### 3. Create DynamoDB Table
```bash
aws dynamodb create-table \
    --table-name media \
    --attribute-definitions AttributeName=s3-url,AttributeType=S \
    --key-schema AttributeName=s3-url,KeyType=HASH \
    --billing-mode PAY_PER_REQUEST
```

### 4. Configure S3 Event Triggers
Configure event notifications for the S3 bucket to automatically trigger corresponding Lambda functions when files are uploaded.

## Usage

### Frontend Usage
1. User selects files on the web page
2. System automatically gets presigned URL
3. Files are uploaded directly to S3
4. AI detection Lambda functions are triggered
5. Wait for detection results and display them

### API Endpoints
- `POST /api/presigned-url` - Get presigned upload URL
- `POST /upload-aws` - Process AWS upload and detection
- `GET /api/check-detection/<s3_url>` - Check detection status
- `POST /upload` - Fallback local upload

## Troubleshooting

### Common Issues

1. **Lambda Function Timeout**
   - Adjust timeout setting to 15 minutes
   - Check model file size

2. **Permission Issues**
   - Ensure Lambda functions have S3 and DynamoDB access permissions
   - Check IAM role configuration

3. **DynamoDB Access Failed**
   - Confirm table name is correct
   - Check region settings

4. **Presigned URL Invalid**
   - Check timestamp and signature
   - Confirm AWS credentials are valid

### View Logs
```bash
# Lambda function logs
aws logs describe-log-groups --log-group-name-prefix /aws/lambda/

# Application logs
tail -f app.log
```

## Performance Optimization

1. **Lambda Cold Start Optimization**
   - Use provisioned concurrency
   - Optimize package size

2. **S3 Transfer Optimization**  
   - Use multipart upload for large files
   - Enable transfer acceleration

3. **DynamoDB Optimization**
   - Set appropriate read/write capacity
   - Use secondary indexes for queries

## Security Considerations

1. **Presigned URL Validity** - Set to 1000 seconds
2. **File Type Validation** - Only allow specific formats
3. **File Size Limits** - Prevent malicious uploads
4. **Access Control** - User login verification

## Fallback Strategy

If AWS services are unavailable, the system will automatically fall back to local upload mode using simulated AI detection functionality. 