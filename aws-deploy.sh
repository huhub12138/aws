#!/bin/bash

# AWS Bird Detection System Deployment Script
# This script deploys all necessary AWS resources

set -e  # Exit on error

echo "🚀 Starting deployment..."

# Set AWS credentials
aws configure set aws_access_key_id ASIATTI8RHHZTQLV364I
aws configure set aws_secret_access_key "bgGNTHaGl+gHNI98HEm5CbvsSt+bGPT2YzD3c0XA"
aws configure set aws_session_token "IQoJb3JpZ2luX2VjEHj////////wEaCXvzLXd1c3QtMjIiMEYCIQD21dTHKno2+mb1njPPyj7wrOF7rpjDXCPSPo7c81alUIQIhA+88qCVn63ewn4XtCGPbfMEBTt+wHM7cdt+HH/pj+DQHtv5CpvSGgwMTQwODY0+xyan0191@student.monash.edu"
aws configure set region us-east-1

# Create temporary directory for builds
BUILD_DIR=$(mktemp -d)
echo "📁 Created temporary build directory: $BUILD_DIR"

# Function to clean up temporary files
cleanup() {
    echo "🧹 Cleaning up..."
    rm -rf "$BUILD_DIR"
    rm -f trust-policy.json role-policy.json
    rm -f *.zip
}
trap cleanup EXIT

# Create S3 bucket
BUCKET_NAME="bird-detection-$(date +%s)"
echo "📦 Creating S3 bucket: $BUCKET_NAME"
aws s3 mb s3://$BUCKET_NAME --region us-east-1

# Create folders in S3
for folder in images videos audios thumbnails models; do
    aws s3api put-object --bucket $BUCKET_NAME --key $folder/
done

# Upload model file to S3
echo "📤 Uploading model file..."
aws s3 cp Img_dectector/model.pt s3://$BUCKET_NAME/models/

# Create DynamoDB tables
echo "🗄️ Creating DynamoDB table..."
aws dynamodb create-table \
    --table-name "bird-detection-media" \
    --attribute-definitions AttributeName=s3-url,AttributeType=S \
    --key-schema AttributeName=s3-url,KeyType=HASH \
    --billing-mode PAY_PER_REQUEST \
    --region us-east-1

# Create Cognito User Pool
echo "👥 Creating Cognito User Pool..."
USER_POOL_ID=$(aws cognito-idp create-user-pool \
    --pool-name "bird-detection-users" \
    --policies '{"PasswordPolicy":{"MinimumLength":8,"RequireUppercase":true,"RequireLowercase":true,"RequireNumbers":true,"RequireSymbols":true}}' \
    --schema '[{"Name":"email","Required":true,"Mutable":true}]' \
    --auto-verified-attributes email \
    --query 'UserPool.Id' \
    --output text)

# Create Cognito App Client
CLIENT_ID=$(aws cognito-idp create-user-pool-client \
    --user-pool-id $USER_POOL_ID \
    --client-name "bird-detection-app" \
    --no-generate-secret \
    --explicit-auth-flows "ALLOW_USER_PASSWORD_AUTH" "ALLOW_REFRESH_TOKEN_AUTH" \
    --query 'UserPoolClient.ClientId' \
    --output text)

# Create SNS Topic for notifications
echo "📧 Creating SNS Topic..."
SNS_TOPIC_ARN=$(aws sns create-topic \
    --name "bird-detection-notifications" \
    --query 'TopicArn' \
    --output text)

# Create API Gateway
echo "🌐 Creating API Gateway..."
API_ID=$(aws apigateway create-rest-api \
    --name "bird-detection-api" \
    --query 'id' \
    --output text)

# Create Lambda Layer for dependencies
echo "📚 Creating Lambda Layer..."
mkdir -p "$BUILD_DIR/python"
for dir in upload_function Img_dectector audio_dectector; do
    if [ -f "$dir/requirements.txt" ]; then
        pip install -r "$dir/requirements.txt" --target "$BUILD_DIR/python"
    fi
done
cd "$BUILD_DIR"
zip -r9 ../lambda-layer.zip python/
cd -

LAYER_ARN=$(aws lambda publish-layer-version \
    --layer-name bird-detection-dependencies \
    --zip-file fileb://lambda-layer.zip \
    --compatible-runtimes python3.9 \
    --query 'LayerVersionArn' \
    --output text)

# Create IAM role
echo "🔐 Creating IAM role..."
ROLE_NAME="bird-detection-lambda-role"

# Create trust policy
cat > trust-policy.json << 'EOF'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Service": "lambda.amazonaws.com"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
EOF

# Create IAM role
ROLE_ARN=$(aws iam create-role \
    --role-name $ROLE_NAME \
    --assume-role-policy-document file://trust-policy.json \
    --query 'Role.Arn' \
    --output text)

# Create and attach role policy
cat > role-policy.json << EOF
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "logs:CreateLogGroup",
                "logs:CreateLogStream",
                "logs:PutLogEvents"
            ],
            "Resource": "arn:aws:logs:*:*:*"
        },
        {
            "Effect": "Allow",
            "Action": [
                "s3:GetObject",
                "s3:PutObject",
                "s3:DeleteObject",
                "s3:ListBucket"
            ],
            "Resource": [
                "arn:aws:s3:::$BUCKET_NAME/*",
                "arn:aws:s3:::$BUCKET_NAME"
            ]
        },
        {
            "Effect": "Allow",
            "Action": [
                "dynamodb:PutItem",
                "dynamodb:GetItem",
                "dynamodb:UpdateItem",
                "dynamodb:DeleteItem",
                "dynamodb:Query",
                "dynamodb:Scan"
            ],
            "Resource": "arn:aws:dynamodb:*:*:table/bird-detection-media"
        },
        {
            "Effect": "Allow",
            "Action": [
                "sns:Publish",
                "sns:Subscribe"
            ],
            "Resource": "$SNS_TOPIC_ARN"
        },
        {
            "Effect": "Allow",
            "Action": [
                "cognito-idp:*"
            ],
            "Resource": "arn:aws:cognito-idp:*:*:userpool/$USER_POOL_ID"
        }
    ]
}
EOF

aws iam put-role-policy \
    --role-name $ROLE_NAME \
    --policy-name bird-detection-permissions \
    --policy-document file://role-policy.json

echo "⏳ Waiting for IAM role to propagate..."
sleep 10

# Deploy Lambda functions
echo "⚡ Deploying Lambda functions..."

# Function to create Lambda function
create_lambda_function() {
    local name=$1
    local handler=$2
    local timeout=$3
    local memory=$4
    local dir=$5
    local env=$6

    echo "Creating function: $name"
    cd "$dir"
    zip -r "../$name.zip" .
    cd -

    aws lambda create-function \
        --function-name "$name" \
        --runtime python3.9 \
        --role "$ROLE_ARN" \
        --handler "$handler" \
        --zip-file "fileb://$name.zip" \
        --timeout "$timeout" \
        --memory-size "$memory" \
        --layers "$LAYER_ARN" \
        --environment "Variables=$env"
}

# Deploy functions
create_lambda_function "bird-upload-function" "upload_lambda.lambda_handler" 30 128 "upload_function" "{BUCKET_NAME=$BUCKET_NAME,TABLE_NAME=bird-detection-media,SNS_TOPIC_ARN=$SNS_TOPIC_ARN}"
create_lambda_function "bird-image-detector" "lambda.lambda_handler" 30 1024 "Img_dectector" "{BUCKET_NAME=$BUCKET_NAME,MODEL_PATH=models/model.pt}"
create_lambda_function "bird-audio-detector" "lambda.lambda_handler" 30 1024 "audio_dectector" "{BUCKET_NAME=$BUCKET_NAME}"
create_lambda_function "bird-query-function" "main.query_handler" 30 128 "as3_aws" "{TABLE_NAME=bird-detection-media}"

# Configure S3 event triggers
echo "🔗 Configuring S3 event triggers..."
aws lambda add-permission \
    --function-name "bird-upload-function" \
    --statement-id "AllowS3Invoke" \
    --action "lambda:InvokeFunction" \
    --principal "s3.amazonaws.com" \
    --source-arn "arn:aws:s3:::$BUCKET_NAME"

aws s3api put-bucket-notification-configuration \
    --bucket "$BUCKET_NAME" \
    --notification-configuration '{
        "LambdaFunctionConfigurations": [
            {
                "LambdaFunctionArn": "'$(aws lambda get-function --function-name bird-upload-function --query 'Configuration.FunctionArn' --output text)'",
                "Events": ["s3:ObjectCreated:*"],
                "Filter": {
                    "Key": {
                        "FilterRules": [
                            {
                                "Name": "prefix",
                                "Value": "uploads/"
                            }
                        ]
                    }
                }
            }
        ]
    }'

# Save configuration
echo "💾 Saving configuration..."
cat > .env << EOF
BUCKET_NAME=$BUCKET_NAME
USER_POOL_ID=$USER_POOL_ID
CLIENT_ID=$CLIENT_ID
API_ID=$API_ID
SNS_TOPIC_ARN=$SNS_TOPIC_ARN
REGION=us-east-1
EOF

echo "✅ Deployment completed successfully!"
echo "Configuration saved to .env file"
echo "S3 Bucket: $BUCKET_NAME"
echo "Cognito User Pool ID: $USER_POOL_ID"
echo "Cognito Client ID: $CLIENT_ID"
echo "API Gateway ID: $API_ID"
echo "SNS Topic ARN: $SNS_TOPIC_ARN" 