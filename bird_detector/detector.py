"""
Unified Bird Detection Module

This module combines functionality from both Img_dectector and bird_detection modules.
It provides functions for detecting birds in images and videos using YOLO models.
"""

from ultralytics import YOLO
import supervision as sv
import cv2 as cv
import numpy as np
import os
from collections import Counter
import boto3

# S3 client for AWS integration
try:
    s3_client = boto3.client('s3')
    dynamodb = boto3.resource('dynamodb')
    AWS_INTEGRATION = True
except Exception:
    AWS_INTEGRATION = False
    print("AWS integration not available")

# Default database table name
TABLE = "media3"

def create_thumbnail(image_path, width=200, height=200):
    """
    Generate a thumbnail from the image file at the given path.
    
    Parameters:
        image_path (str): The path to the original image 
        width (int): The width of the thumbnail (default 200px)
        height (int): The height of the thumbnail (default 200px)
        
    Returns:
        bytes: The binary data of the thumbnail, returns None on failure
    """
    # Get file extension
    _, ext = os.path.splitext(image_path)
    # Read the original image file
    img = cv.imread(image_path)
    if img is None:
        print("Cannot load the image, please check the path")
        return None
    try:
        # Adjust the image size to the specified width and height
        thumbnail = cv.resize(img, (width, height))
        ok, buffer = cv.imencode(ext, thumbnail)
        
        if not ok:
            print("Image encoding failed")
            return None
        
        # Return the binary data of the thumbnail
        return buffer.tobytes()
    except Exception as e:
        print(f"An error occurred while generating the thumbnail: {str(e)}")
        return None

def image_prediction(image_path, confidence=0.5, model_path=None, save_result=False, save_dir="./results"):
    """
    Detect birds in images using a pre-trained YOLO model.

    Parameters:
        image_path (str): Path to the image file
        confidence (float): Confidence threshold (0-1), default is 0.5
        model_path (str): Path to the YOLO model file, default is "./model.pt" in module directory
        save_result (bool): Whether to save the annotated result image
        save_dir (str): Directory to save output files if save_result is True
        
    Returns:
        list: List of detected bird species
    """
    # Use default model if not specified
    if model_path is None:
        model_path = os.path.join(os.path.dirname(__file__), "model.pt")
    
    # Check if model exists
    if not os.path.exists(model_path):
        print(f"Model not found at {model_path}. Please check the model path.")
        return []

    # Load YOLO model
    model = YOLO(model_path)
    class_dict = model.names

    # Load image from local path
    img = cv.imread(image_path)

    # Check if image was loaded successfully
    if img is None:
        print("Couldn't load the image! Please check the image path.")
        return []

    # Get image dimensions for annotations if saving result
    if save_result:
        h, w = img.shape[:2]
        thickness = sv.calculate_optimal_line_thickness(resolution_wh=(w, h))
        text_scale = sv.calculate_optimal_text_scale(resolution_wh=(w, h))
        color_palette = sv.ColorPalette.from_matplotlib('magma', 10)
        box_annotator = sv.BoxAnnotator(thickness=thickness, color=color_palette)
        label_annotator = sv.LabelAnnotator(color=color_palette, text_scale=text_scale, 
                                          text_thickness=thickness, 
                                          text_position=sv.Position.TOP_LEFT)

    # Run the model on the image
    result = model(img)[0]

    # Convert YOLO result to Detections format
    detections = sv.Detections.from_ultralytics(result)

    # Initialize labels list
    labels = []
    
    # Filter detections based on confidence threshold and check if any exist
    if detections.class_id is not None:
        detections = detections[(detections.confidence > confidence)]

        # Create labels for the detected objects
        labels = [class_dict[cls_id] for cls_id in detections.class_id]
        
        # Annotate the image if saving result
        if save_result:
            label_texts = [f"{class_dict[cls_id]} {conf*100:.2f}%" for cls_id, conf in 
                          zip(detections.class_id, detections.confidence)]
            box_annotator.annotate(img, detections=detections)
            label_annotator.annotate(img, detections=detections, labels=label_texts)
            
            # Save the annotated image
            os.makedirs(save_dir, exist_ok=True)
            result_filename = os.path.basename(image_path)
            result_path = os.path.join(save_dir, f"result_{result_filename}")
            try:
                cv.imwrite(result_path, img)
                print(f"Annotated image saved to {result_path}")
            except Exception as e:
                print(f"Error saving annotated image: {e}")
    
    return labels

def video_prediction(video_path, confidence=0.5, model_path=None, save_result=False, save_dir="./results"):
    """
    Detect birds in video frames using a trained YOLO model.

    Parameters:
        video_path (str): Path to the video file
        confidence (float): Confidence threshold (0-1), default is 0.5
        model_path (str): Path to the YOLO model file, default is "./model.pt" in module directory
        save_result (bool): Whether to save the annotated result video
        save_dir (str): Directory to save output files if save_result is True
        
    Returns:
        list: List of detected bird species across all frames
    """
    all_labels = []
    
    # Use default model if not specified
    if model_path is None:
        model_path = os.path.join(os.path.dirname(__file__), "model.pt")
    
    # Check if model exists
    if not os.path.exists(model_path):
        print(f"Model not found at {model_path}. Please check the model path.")
        return []
    
    try:
        # Load video info and extract width, height, and frames per second (fps)
        video_info = sv.VideoInfo.from_video_path(video_path=video_path)
        w, h, fps = int(video_info.width), int(video_info.height), int(video_info.fps)

        # Calculate the optimal thickness for annotations and text scale based on video resolution
        thickness = sv.calculate_optimal_line_thickness(resolution_wh=video_info.resolution_wh)
        text_scale = sv.calculate_optimal_text_scale(resolution_wh=video_info.resolution_wh)

        # Initialize YOLO model, tracker, and color lookup for annotations
        box_annotator = sv.BoxAnnotator(thickness=thickness, color_lookup=sv.ColorLookup.TRACK)
        label_annotator = sv.LabelAnnotator(text_scale=text_scale, text_thickness=thickness, 
                                          text_position=sv.Position.TOP_LEFT,
                                          color_lookup=sv.ColorLookup.TRACK)

        model = YOLO(model_path)  # Load YOLO model
        tracker = sv.ByteTrack(frame_rate=fps)  # Initialize the tracker with the video's frame rate
        class_dict = model.names  # Get the class labels from the model

        # Setup for saving the video with annotations, if required
        if save_result:
            os.makedirs(save_dir, exist_ok=True)
            result_filename = f"result_{os.path.basename(video_path)}"
            save_path = os.path.join(save_dir, result_filename)
            out = cv.VideoWriter(save_path, cv.VideoWriter_fourcc(*"XVID"), fps, (w, h))
        
        # Capture the video from the given path
        cap = cv.VideoCapture(video_path)
        if not cap.isOpened():
            raise Exception("Error: couldn't open the video!")

        # Process the video frame by frame
        while cap.isOpened():
            ret, frame = cap.read()
            if not ret:  # End of the video
                break

            # Make predictions on the current frame using the YOLO model
            result = model(frame)[0]
            detections = sv.Detections.from_ultralytics(result)  # Convert model output to Detections format
            detections = tracker.update_with_detections(detections=detections)  # Track detected objects

            # Filter detections based on confidence
            if detections.tracker_id is not None:
                detections = detections[(detections.confidence > confidence)]  # Keep detections with confidence greater than threshold

                # Extract species labels
                frame_labels = [class_dict[cls_id] for cls_id in detections.class_id]
                all_labels.extend(frame_labels)
                
                # Annotate the frame if saving result
                if save_result:
                    # Generate labels for tracked objects
                    labels = [f"{class_dict[cls_id]} {conf*100:.2f}%" for cls_id, conf in zip(
                              detections.class_id, detections.confidence)]

                    # Annotate the frame with bounding boxes and labels
                    box_annotator.annotate(frame, detections=detections)
                    label_annotator.annotate(frame, detections=detections, labels=labels)
                    out.write(frame)

    except Exception as e:
        print(f"An error occurred during video processing: {e}")

    finally:
        # Release resources
        if 'cap' in locals() and cap is not None:
            cap.release()
        if 'out' in locals() and out is not None and save_result:
            out.release()
        print("Video processing complete")
        
    # Return unique labels
    return list(set(all_labels))

def save_to_s3(file_path, bucket, key):
    """
    Upload a file to S3 bucket.
    
    Parameters:
        file_path (str): Path to the local file
        bucket (str): S3 bucket name
        key (str): S3 object key (path in bucket)
        
    Returns:
        bool: True if upload was successful, False otherwise
    """
    if not AWS_INTEGRATION:
        print("AWS integration not available")
        return False
        
    try:
        s3_client.upload_file(file_path, bucket, key)
        return True
    except Exception as e:
        print(f"Error uploading to S3: {e}")
        return False

def save_to_dynamodb(item):
    """
    Save an item to DynamoDB table.
    
    Parameters:
        item (dict): Item to save to DynamoDB
        
    Returns:
        bool: True if save was successful, False otherwise
    """
    if not AWS_INTEGRATION:
        print("AWS integration not available")
        return False
        
    try:
        dynamodb.Table(TABLE).put_item(Item=item)
        return True
    except Exception as e:
        print(f"Error saving to DynamoDB: {e}")
        return False

def handle_s3_event(event, context=None):
    """
    AWS Lambda handler for S3 events.
    
    Parameters:
        event (dict): S3 event object
        context (object): Lambda context object
        
    Returns:
        dict: Processing result
    """
    if not AWS_INTEGRATION:
        print("AWS integration not available")
        return {"success": False, "message": "AWS integration not available"}
        
    try:
        results = []
        for record in event.get('Records', []):
            try:
                # Analysis of Bucket and Key
                bucket = record['s3']['bucket']['name']
                key = record['s3']['object']['key']
                filename = key.split('/')[-1]
                tmp_path = f"/tmp/{filename}"

                print(f"Downloading s3://{bucket}/{key} → {tmp_path}")
                s3_client.download_file(bucket, key, tmp_path)

                # Initialize variables
                labels = []
                file_type = None
                thumbnail_url = None

                # Determine file type based on key
                if key.startswith('images/') or any(key.lower().endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.gif']):
                    file_type = "image"
                    labels = image_prediction(tmp_path)
                    thumbnail_data = create_thumbnail(tmp_path)
                    
                    if thumbnail_data:
                        thumbnail_key = f"thumbnails/{filename}"
                        s3_client.put_object(
                            Bucket=bucket,
                            Key=thumbnail_key,
                            Body=thumbnail_data,
                            ContentType='image/jpeg'
                        )
                        thumbnail_url = f"https://{bucket}.s3.amazonaws.com/{thumbnail_key}"
                
                elif key.startswith('videos/') or any(key.lower().endswith(ext) for ext in ['.mp4', '.avi', '.mov']):
                    file_type = "video"
                    labels = video_prediction(tmp_path)
                
                elif key.startswith('audio/') or any(key.lower().endswith(ext) for ext in ['.mp3', '.wav', '.m4a']):
                    file_type = "audio"
                    # No audio detection in this module, would need to call audio_detector
                    labels = []
                
                else:
                    print(f"Unsupported file type: {key}")
                    continue

                # Convert labels to counter for frequencies
                labels_counter = Counter(labels)

                # Create DynamoDB item
                item = {
                    's3-url': f"https://{bucket}.s3.amazonaws.com/{key}",
                    'filetype': file_type,
                    'tags': dict(labels_counter)
                }
                
                # Add thumbnail URL if available
                if thumbnail_url:
                    item['thumbnailurl'] = thumbnail_url

                # Save to DynamoDB
                dynamodb.Table(TABLE).put_item(Item=item)
                
                # Add to results
                results.append({
                    'key': key,
                    'file_type': file_type,
                    'labels': labels,
                    'thumbnail_url': thumbnail_url
                })

            except Exception as e:
                print(f"Error processing file {key}: {e}")
                results.append({
                    'key': key,
                    'error': str(e)
                })
        
        return {
            'success': True,
            'message': f'Processed {len(results)} files',
            'results': results
        }
    
    except Exception as e:
        print(f"Error processing event: {e}")
        return {
            'success': False,
            'message': f'Error: {str(e)}'
        }

# Test code for local execution
if __name__ == '__main__':
    print("Testing bird detection module...")
    
    # Test paths to check if files exist
    test_image = "./test_images/test.jpg"
    test_video = "./test_videos/test.mp4"
    
    if os.path.exists(test_image):
        print(f"Testing image detection on {test_image}")
        species = image_prediction(test_image, save_result=True)
        print(f"Detected species: {species}")
    else:
        print(f"Test image not found at {test_image}")
    
    if os.path.exists(test_video):
        print(f"Testing video detection on {test_video}")
        species = video_prediction(test_video, save_result=True)
        print(f"Detected species: {species}")
    else:
        print(f"Test video not found at {test_video}") 