# Unified Bird Detection Module

This module combines the functionality of both `Img_dectector` and `bird_detection` modules, providing a unified interface for bird image and video detection.

## Features

- Bird species recognition using YOLO models
- Support for image and video file processing
- Option to save annotated result files
- AWS S3 and DynamoDB integration (when available)
- Image thumbnail creation

## Installation

```bash
pip install -r requirements.txt
```

## Usage

### Image Detection

```python
from bird_detector import detector

# Basic usage
species = detector.image_prediction("path/to/image.jpg")
print(f"Detected bird species: {species}")

# Save annotated results
species = detector.image_prediction(
    "path/to/image.jpg", 
    confidence=0.6,  # Confidence threshold
    save_result=True,  # Save annotated result
    save_dir="./results"  # Result directory
)
```

### Video Detection

```python
from bird_detector import detector

# Basic usage
species = detector.video_prediction("path/to/video.mp4")
print(f"Detected bird species: {species}")

# Save annotated results
species = detector.video_prediction(
    "path/to/video.mp4", 
    confidence=0.6,  # Confidence threshold
    save_result=True,  # Save annotated result
    save_dir="./results"  # Result directory
)
```

### AWS Integration

For AWS Lambda environments, you can directly process S3 events:

```python
from bird_detector import detector

def lambda_handler(event, context):
    return detector.handle_s3_event(event, context)
```

Or upload files to S3 directly:

```python
from bird_detector import detector

# Upload file to S3
success = detector.save_to_s3(
    "path/to/local_file.jpg",
    "your-bucket-name",
    "images/local_file.jpg"
)

# Save data to DynamoDB
item = {
    's3-url': 'https://your-bucket.s3.amazonaws.com/images/file.jpg',
    'filetype': 'image',
    'tags': {'sparrow': 3, 'eagle': 1}
}
success = detector.save_to_dynamodb(item)
```

## Parameter Reference

### image_prediction

| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| image_path | str | Path to image file | - |
| confidence | float | Confidence threshold (0-1) | 0.5 |
| model_path | str | Path to model file | None (uses model.pt in the module directory) |
| save_result | bool | Whether to save annotated result | False |
| save_dir | str | Directory to save results | "./results" |

### video_prediction

| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| video_path | str | Path to video file | - |
| confidence | float | Confidence threshold (0-1) | 0.5 |
| model_path | str | Path to model file | None (uses model.pt in the module directory) |
| save_result | bool | Whether to save annotated result | False |
| save_dir | str | Directory to save results | "./results" |

## Running Tests

```bash
cd bird_detector
python -m detector
```

## Notes

1. The model file `model.pt` should be placed in the module directory or specified through parameters
2. AWS integration features require properly configured AWS credentials
3. The default DynamoDB table name is "media3", which can be changed by modifying the TABLE variable in detector.py 