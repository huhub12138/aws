import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key-change-in-production'

    # Database configuration
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or 'sqlite:///app.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Upload configuration
    UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')
    MAX_CONTENT_LENGTH = 50 * 1024 * 1024  # 50MB max file size
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'mp4', 'avi', 'mov', 'mp3', 'wav', 'flac'}

    # AWS Configuration
    AWS_ACCESS_KEY_ID = os.environ.get('AWS_ACCESS_KEY_ID')
    AWS_SECRET_ACCESS_KEY = os.environ.get('AWS_SECRET_ACCESS_KEY')
    AWS_DEFAULT_REGION = os.environ.get('AWS_DEFAULT_REGION') or 'us-east-1'
    AWS_S3_BUCKET = os.environ.get('AWS_S3_BUCKET') or 'bird-detection-bucket'
    
    # Lambda Function ARNs
    UPLOAD_LAMBDA_ARN = os.environ.get('UPLOAD_LAMBDA_ARN')
    IMAGE_DETECTOR_ARN = os.environ.get('IMAGE_DETECTOR_ARN')
    AUDIO_DETECTOR_ARN = os.environ.get('AUDIO_DETECTOR_ARN')
    
    # DynamoDB
    DYNAMODB_TABLE = os.environ.get('DYNAMODB_TABLE') or 'bird-detection-media'
    
    # SNS Configuration for notifications
    SNS_TOPIC_ARN = os.environ.get('SNS_TOPIC_ARN')
    
    # Model Management Configuration
    MODEL_CONFIG_LAMBDA_ARN = os.environ.get('MODEL_CONFIG_LAMBDA_ARN')
    MODEL_S3_BUCKET = os.environ.get('MODEL_S3_BUCKET') or 'bird-detection-bucket'


class DevelopmentConfig(Config):
    DEBUG = True


class ProductionConfig(Config):
    DEBUG = False


class TestingConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'


config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig,
    'default': DevelopmentConfig
}