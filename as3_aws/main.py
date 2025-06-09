from flask import Flask, render_template, request, jsonify, redirect, url_for, session
from flask_migrate import Migrate
from werkzeug.utils import secure_filename
from datetime import datetime, timedelta
import os
import secrets
import string
import json
import boto3
from botocore.exceptions import ClientError
from config import config
from models import db, User, Upload, Tag, Species, SearchQuery, PasswordResetToken

# AWS clients will be initialized after app creation
s3_client = None
lambda_client = None
dynamodb = None
sns_client = None


def init_default_data():
    """Initialize default species data"""
    default_species = [
        {
            'common_name': 'Sulphur-crested Cockatoo',
            'scientific_name': 'Cacatua galerita',
            'family': 'Cacatuidae',
            'conservation_status': 'Least Concern'
        },
        {
            'common_name': 'Laughing Kookaburra',
            'scientific_name': 'Dacelo novaeguineae',
            'family': 'Alcedinidae',
            'conservation_status': 'Least Concern'
        },
        {
            'common_name': 'Australian Magpie',
            'scientific_name': 'Gymnorhina tibicen',
            'family': 'Artamidae',
            'conservation_status': 'Least Concern'
        },
        {
            'common_name': 'Rainbow Lorikeet',
            'scientific_name': 'Trichoglossus moluccanus',
            'family': 'Psittaculidae',
            'conservation_status': 'Least Concern'
        },
        {
            'common_name': 'Galah',
            'scientific_name': 'Eolophus roseicapilla',
            'family': 'Cacatuidae',
            'conservation_status': 'Least Concern'
        }
    ]

    for species_data in default_species:
        if not Species.query.filter_by(scientific_name=species_data['scientific_name']).first():
            species = Species(**species_data)
            db.session.add(species)

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"Error initializing default data: {e}")


def create_app(config_name='default'):
    global s3_client, lambda_client, dynamodb, sns_client
    
    app = Flask(__name__)
    app.config.from_object(config[config_name])

    # Initialize AWS clients after config is loaded
    s3_client = boto3.client('s3', region_name=app.config.get('AWS_DEFAULT_REGION', 'us-east-1'))
    lambda_client = boto3.client('lambda', region_name=app.config.get('AWS_DEFAULT_REGION', 'us-east-1'))
    dynamodb = boto3.resource('dynamodb', region_name=app.config.get('AWS_DEFAULT_REGION', 'us-east-1'))
    sns_client = boto3.client('sns', region_name=app.config.get('AWS_DEFAULT_REGION', 'us-east-1'))

    # Initialize extensions
    db.init_app(app)
    migrate = Migrate(app, db)

    # Create upload folder if it doesn't exist
    if not os.path.exists(app.config['UPLOAD_FOLDER']):
        os.makedirs(app.config['UPLOAD_FOLDER'])

    # Create database tables and initialize data
    with app.app_context():
        db.create_all()
        init_default_data()

    return app


app = create_app('development')


def generate_reset_token():
    """Generate random password reset token"""
    return ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(32))


def get_presigned_upload_url(file_type, file_extension):
    """Get S3 presigned upload URL"""
    try:
        payload = {
            'type': file_type,
            'suffix': file_extension
        }
        
        response = lambda_client.invoke(
            FunctionName=app.config['UPLOAD_LAMBDA_ARN'],
            InvocationType='RequestResponse',
            Payload=json.dumps({'body': json.dumps(payload)})
        )
        
        result = json.loads(response['Payload'].read())
        if result.get('statusCode') == 200:
            body = json.loads(result['body'])
            return body.get('url')
        else:
            print(f"Lambda function returned error: {result}")
            return None
            
    except Exception as e:
        print(f"Error getting presigned URL: {e}")
        return None


def trigger_ai_detection(s3_key, file_type):
    """Trigger corresponding AI detection Lambda function"""
    try:
        # Simulate S3 event structure
        s3_event = {
            'Records': [{
                's3': {
                    'bucket': {'name': app.config['AWS_S3_BUCKET']},
                    'object': {'key': s3_key}
                }
            }]
        }
        
        # Select appropriate Lambda function based on file type
        if file_type in ['image', 'video']:
            lambda_arn = app.config['IMAGE_DETECTOR_ARN']
        elif file_type == 'audio':
            lambda_arn = app.config['AUDIO_DETECTOR_ARN']
        else:
            print(f"Unsupported file type: {file_type}")
            return None
            
        # Asynchronously invoke Lambda function
        response = lambda_client.invoke(
            FunctionName=lambda_arn,
            InvocationType='Event',  # Asynchronous invocation
            Payload=json.dumps(s3_event)
        )
        
        return response.get('StatusCode') == 202
        
    except Exception as e:
        print(f"Error triggering AI detection: {e}")
        return False


def get_detection_results(s3_url, max_retries=10, retry_delay=2):
    """Get detection results from DynamoDB (with retry mechanism)"""
    import time
    
    for attempt in range(max_retries):
        try:
            table = dynamodb.Table(app.config['DYNAMODB_TABLE'])
            response = table.get_item(Key={'s3-url': s3_url})
            
            if 'Item' in response:
                tags = response['Item'].get('tags', {})
                # Convert Counter dictionary to list and confidence dictionary
                species_list = list(tags.keys())
                confidence_dict = {species: 0.8 + (count * 0.1) for species, count in tags.items()}
                
                return {
                    'species': species_list,
                    'confidence': confidence_dict
                }
            
            # If no results yet, wait for a while and retry
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
                
        except Exception as e:
            print(f"Error getting results from DynamoDB (attempt {attempt + 1}): {e}")
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
    
    # If all retries fail, return empty results
    return {'species': [], 'confidence': {}}


def allowed_file(filename):
    return '.' in filename and \
        filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']


def validate_password(password):
    """Validate password requirements"""
    import re
    if len(password) < 6:
        return False, "Password must be at least 6 characters long"
    if not re.search(r'[A-Z]', password):
        return False, "Password must contain an uppercase letter"
    if not re.search(r'[a-z]', password):
        return False, "Password must contain a lowercase letter"
    if not re.search(r'\d', password):
        return False, "Password must contain a number"
    return True, "Password meets requirements"


# Helper function to simulate AI species detection
def simulate_species_detection(file_type, filepath):
    """Simulate AI bird species detection"""
    import random

    common_birds = [
        'Cockatoo', 'Kookaburra', 'Magpie', 'Rainbow Lorikeet',
        'Galah', 'Sulphur-crested Cockatoo', 'Australian Raven',
        'Willie Wagtail', 'Fairy Wren', 'Butcherbird'
    ]

    # Simulate detection with random species
    num_species = random.randint(1, 3)
    detected = random.sample(common_birds, num_species)

    confidence = {}
    for species in detected:
        confidence[species] = round(random.uniform(0.7, 0.99), 2)

    return {
        'species': detected,
        'confidence': confidence
    }


@app.route('/')
def index():
    if 'user_id' in session and 'username' in session:
        return redirect(url_for('dashboard'))
    return render_template('index.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        data = request.get_json()
        username = data.get('username')
        password1 = data.get('password1')
        password2 = data.get('password2')
        email = data.get('email', '')

        # Check if username already exists
        if User.query.filter_by(username=username).first():
            return jsonify({'success': False, 'message': 'Username already exists'})

        # Check if passwords match
        if password1 != password2:
            return jsonify({'success': False, 'message': 'Passwords do not match'})

        # Validate password strength
        is_valid, message = validate_password(password1)
        if not is_valid:
            return jsonify({'success': False, 'message': message})

        # Create new user
        user = User(username=username, email=email)
        user.set_password(password1)

        try:
            db.session.add(user)
            db.session.commit()
            return jsonify({'success': True, 'message': 'Registration successful'})
        except Exception as e:
            db.session.rollback()
            return jsonify({'success': False, 'message': 'Registration failed. Please try again.'})

    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        data = request.get_json()
        username = data.get('username')
        password = data.get('password')

        user = User.query.filter_by(username=username).first()

        if user and user.check_password(password):
            session['user_id'] = user.id
            session['username'] = user.username
            return jsonify({'success': True})
        else:
            return jsonify({'success': False, 'message': 'Invalid username or password'})

    return render_template('login.html')


@app.route('/api/check-detection/<path:s3_url>', methods=['GET'])
def check_detection_status(s3_url):
    """API endpoint to check AI detection results"""
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Please login first'})
    
    try:
        # Decode URL
        import urllib.parse
        decoded_url = urllib.parse.unquote(s3_url)
        
        # Get detection results
        results = get_detection_results(decoded_url, max_retries=1, retry_delay=0)
        
        return jsonify({
            'success': True,
            'has_results': len(results.get('species', [])) > 0,
            'species': results.get('species', []),
            'confidence': results.get('confidence', {})
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


@app.route('/api/presigned-url', methods=['POST'])
def get_presigned_url():
    """API endpoint to get S3 presigned upload URL"""
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Please login first'})
    
    data = request.get_json()
    file_type = data.get('file_type')  # 'images', 'videos', 'audios'
    file_extension = data.get('file_extension')  # 'jpg', 'mp4', 'mp3', etc.
    
    if not file_type or not file_extension:
        return jsonify({'success': False, 'message': 'File type and extension are required'})
    
    # Get presigned URL
    presigned_url = get_presigned_upload_url(file_type, file_extension)
    
    if presigned_url:
        return jsonify({
            'success': True, 
            'presigned_url': presigned_url
        })
    else:
        return jsonify({'success': False, 'message': 'Failed to generate upload URL'})


@app.route('/api/upload-url', methods=['POST'])
def get_upload_url():
    """API endpoint to get S3 presigned upload URL"""
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Please login first'})
    
    data = request.get_json()
    file_name = data.get('fileName')
    file_type = data.get('fileType')
    
    if not file_name or not file_type:
        return jsonify({'success': False, 'message': 'Missing fileName or fileType'})
    
    # Determine file extension
    file_extension = file_name.rsplit('.', 1)[1].lower() if '.' in file_name else ''
    
    # Determine S3 folder type
    if file_type.startswith('image/'):
        s3_folder = 'images'
        media_type = 'image'
    elif file_type.startswith('video/'):
        s3_folder = 'videos'  
        media_type = 'video'
    elif file_type.startswith('audio/'):
        s3_folder = 'audios'
        media_type = 'audio'
    else:
        return jsonify({'success': False, 'message': 'Unsupported file type'})
    
    # Get presigned URL
    upload_url = get_presigned_upload_url(s3_folder, file_extension)
    
    if upload_url:
        # Extract S3 key from URL
        s3_key = upload_url.split('amazonaws.com/')[1].split('?')[0]
        
        return jsonify({
            'success': True,
            'uploadUrl': upload_url,
            's3Key': s3_key,
            'mediaType': media_type
        })
    else:
        return jsonify({'success': False, 'message': 'Failed to get upload URL'})


@app.route('/upload-aws', methods=['POST'])
def upload_file_aws():
    """New route for file upload and AI detection using AWS Lambda"""
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Please login first'})

    data = request.get_json()
    s3_url = data.get('s3_url')  # Complete S3 URL
    original_filename = data.get('original_filename')
    file_type = data.get('file_type')  # 'image', 'video', 'audio'
    file_size = data.get('file_size', 0)
    location = data.get('location', '')
    observation_date = data.get('date')
    notes = data.get('notes', '')

    if not s3_url or not original_filename or not file_type:
        return jsonify({'success': False, 'message': 'Missing required parameters'})

    try:
        # Extract key from S3 URL
        s3_key = s3_url.split('amazonaws.com/')[-1]
        
        # Trigger AI detection
        detection_triggered = trigger_ai_detection(s3_key, file_type)
        
        if not detection_triggered:
            return jsonify({'success': False, 'message': 'Failed to trigger AI detection'})

        # Get detection results (with retry)
        detected_species = get_detection_results(s3_url)

        # Create upload record
        upload = Upload(
            user_id=session['user_id'],
            filename=s3_key.split('/')[-1],  # Get filename from S3 key
            original_filename=original_filename,
            file_path=s3_url,  # Store S3 URL instead of local path
            file_type=file_type,
            file_size=file_size,
            location=location,
            observation_date=datetime.strptime(observation_date, '%Y-%m-%d').date() if observation_date else None,
            notes=notes,
            species_detected=detected_species.get('species', []),
            confidence_scores=detected_species.get('confidence', {})
        )

        # Auto-tag based on detected species
        for species_name in detected_species.get('species', []):
            tag = Tag.query.filter_by(name=species_name, category='species').first()
            if not tag:
                tag = Tag(name=species_name, category='species')
                db.session.add(tag)
            upload.tags.append(tag)

        db.session.add(upload)
        db.session.commit()

        return jsonify({
            'success': True,
            'message': 'File uploaded and analyzed successfully',
            'species': detected_species.get('species', []),
            'confidence': detected_species.get('confidence', {}),
            'file': upload.to_dict()
        })

    except Exception as e:
        db.session.rollback()
        print(f"Upload processing error: {e}")
        return jsonify({'success': False, 'message': 'Upload processing failed'})


@app.route('/upload', methods=['POST'])
def upload_file():
    """Keep original local upload functionality as fallback option"""
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Please login first'})

    
    if 'file' in request.files:
        files = [request.files['file']]
    elif 'files' in request.files:
        files = request.files.getlist('files')
    else:
        return jsonify({'success': False, 'message': 'No files uploaded'})

    location = request.form.get('location', '')
    observation_date = request.form.get('date')
    notes = request.form.get('notes', '')

    uploaded_files = []

    for file in files:
        if file and file.filename and allowed_file(file.filename):
            # Generate secure filename
            original_filename = file.filename
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"{timestamp}_{secure_filename(original_filename)}"
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)

            # Save file
            file.save(filepath)

            # Determine file type
            file_ext = filename.rsplit('.', 1)[1].lower()
            if file_ext in ['jpg', 'jpeg', 'png', 'gif']:
                file_type = 'image'
            elif file_ext in ['mp4', 'avi', 'mov']:
                file_type = 'video'
            elif file_ext in ['mp3', 'wav', 'm4a']:
                file_type = 'audio'
            else:
                file_type = 'other'

            # Create upload record
            upload = Upload(
                user_id=session['user_id'],
                filename=filename,
                original_filename=original_filename,
                file_path=filepath,
                file_type=file_type,
                file_size=os.path.getsize(filepath),
                location=location,
                observation_date=datetime.strptime(observation_date, '%Y-%m-%d').date() if observation_date else None,
                notes=notes,
                species_detected=[],  # This would be populated by AI detection
                confidence_scores={}
            )

            # Here you would call your AI model to detect species
            # For now, we'll simulate it
            detected_species = simulate_species_detection(file_type, filepath)
            upload.species_detected = detected_species['species']
            upload.confidence_scores = detected_species['confidence']

            # Auto-tag based on detected species
            for species_name in detected_species['species']:
                tag = Tag.query.filter_by(name=species_name, category='species').first()
                if not tag:
                    tag = Tag(name=species_name, category='species')
                    db.session.add(tag)
                upload.tags.append(tag)

            db.session.add(upload)
            uploaded_files.append(upload)

    try:
        db.session.commit()
        return jsonify({
            'success': True,
            'message': f'Successfully uploaded {len(uploaded_files)} file(s)',
            'species': list(set([species for upload in uploaded_files for species in upload.species_detected])),
            'files': [upload.to_dict() for upload in uploaded_files]
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': 'Upload failed. Please try again.'})


@app.route('/search', methods=['POST'])
def search_files():
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Please login first'})

    data = request.get_json()
    species = data.get('species', '')
    media_type = data.get('mediaType', '')
    date_range = data.get('dateRange', '')

    # Build query
    query = Upload.query.filter_by(user_id=session['user_id'])

    # Filter by species
    if species:
        query = query.filter(Upload.species_detected.contains([species]))

    # Filter by media type
    if media_type:
        query = query.filter_by(file_type=media_type)

    # Filter by date range
    if date_range:
        today = datetime.now().date()
        if date_range == 'today':
            query = query.filter(db.func.date(Upload.uploaded_at) == today)
        elif date_range == 'week':
            week_ago = today - timedelta(days=7)
            query = query.filter(Upload.uploaded_at >= week_ago)
        elif date_range == 'month':
            month_ago = today - timedelta(days=30)
            query = query.filter(Upload.uploaded_at >= month_ago)
        elif date_range == 'year':
            year_ago = today - timedelta(days=365)
            query = query.filter(Upload.uploaded_at >= year_ago)

    # Execute query
    results = query.order_by(Upload.uploaded_at.desc()).all()

    # Log search query
    search_log = SearchQuery(
        user_id=session['user_id'],
        query_params={
            'species': species,
            'media_type': media_type,
            'date_range': date_range
        },
        result_count=len(results)
    )
    db.session.add(search_log)
    db.session.commit()

    # Format results
    files_data = []
    for upload in results:
        file_data = {
            'id': upload.id,
            'name': upload.original_filename,
            'type': upload.file_type,
            'species': ', '.join(upload.species_detected) if upload.species_detected else 'Unknown',
            'date': upload.observation_date.strftime('%Y-%m-%d') if upload.observation_date else upload.uploaded_at.strftime('%Y-%m-%d'),
            'location': upload.location or 'Unknown',
            'thumbnail': f'/uploads/{upload.filename}' if upload.file_type == 'image' else None
        }
        files_data.append(file_data)

    return jsonify({
        'success': True,
        'count': len(results),
        'files': files_data
    })


@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    # Get user statistics
    user = User.query.get(session['user_id'])
    if not user:
        session.clear()
        return redirect(url_for('login'))

    total_uploads = Upload.query.filter_by(user_id=user.id).count()

    # Get unique species count
    all_species = db.session.query(Upload.species_detected) \
        .filter_by(user_id=user.id) \
        .filter(Upload.species_detected != None).all()
    unique_species = set()
    for species_list in all_species:
        if species_list[0]:
            unique_species.update(species_list[0])

    # This month's uploads
    first_day_of_month = datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    monthly_uploads = Upload.query.filter(
        Upload.user_id == user.id,
        Upload.uploaded_at >= first_day_of_month
    ).count()

    # Calculate storage used
    total_size = db.session.query(db.func.sum(Upload.file_size)) \
                     .filter_by(user_id=user.id).scalar() or 0
    storage_gb = round(total_size / (1024 * 1024 * 1024), 2)

    return render_template('dashboard.html',
                           username=session.get('username', user.username),
                           stats={
                               'total_uploads': total_uploads,
                               'species_count': len(unique_species),
                               'monthly_uploads': monthly_uploads,
                               'storage_gb': storage_gb
                           })


@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        data = request.get_json()
        username = data.get('username')

        user = User.query.filter_by(username=username).first()
        if not user:
            return jsonify({'success': False, 'message': 'Username does not exist'})

        # Generate reset token
        token = generate_reset_token()
        reset_token = PasswordResetToken(
            token=token,
            user_id=user.id,
            expires_at=datetime.now() + timedelta(hours=1)
        )

        db.session.add(reset_token)
        db.session.commit()

        reset_link = f"/reset-password?token={token}"

        return jsonify({
            'success': True,
            'message': 'Reset link has been generated',
            'reset_link': reset_link,
            'note': 'In production, this link would be sent to your email'
        })

    return render_template('forgot_password.html')


@app.route('/reset-password', methods=['GET', 'POST'])
def reset_password():
    if request.method == 'GET':
        token = request.args.get('token')
        if not token:
            return render_template('reset_password.html', error='Invalid reset link')

        reset_token = PasswordResetToken.query.filter_by(token=token, used=False).first()
        if not reset_token:
            return render_template('reset_password.html', error='Invalid reset link')

        if datetime.now() > reset_token.expires_at:
            return render_template('reset_password.html', error='Reset link has expired')

        return render_template('reset_password.html', token=token)

    elif request.method == 'POST':
        data = request.get_json()
        token = data.get('token')
        password1 = data.get('password1')
        password2 = data.get('password2')

        reset_token = PasswordResetToken.query.filter_by(token=token, used=False).first()
        if not reset_token:
            return jsonify({'success': False, 'message': 'Invalid reset link'})

        if datetime.now() > reset_token.expires_at:
            return jsonify({'success': False, 'message': 'Reset link has expired'})

        if password1 != password2:
            return jsonify({'success': False, 'message': 'Passwords do not match'})

        is_valid, message = validate_password(password1)
        if not is_valid:
            return jsonify({'success': False, 'message': message})

        # Update password
        user = User.query.get(reset_token.user_id)
        user.set_password(password1)
        reset_token.used = True

        db.session.commit()

        return jsonify({'success': True, 'message': 'Password reset successful'})


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))


# API endpoints for dashboard statistics
@app.route('/api/stats')
def get_stats():
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Unauthorized'})

    user_id = session['user_id']

    # Get various statistics
    stats = {
        'total_uploads': Upload.query.filter_by(user_id=user_id).count(),
        'recent_uploads': []
    }

    # Get recent uploads
    recent = Upload.query.filter_by(user_id=user_id) \
        .order_by(Upload.uploaded_at.desc()) \
        .limit(5).all()

    for upload in recent:
        stats['recent_uploads'].append({
            'filename': upload.original_filename,
            'type': upload.file_type,
            'species': upload.species_detected,
            'uploaded_at': upload.uploaded_at.isoformat()
        })

    return jsonify(stats)


@app.route('/api/recent-uploads')
def get_recent_uploads():
    """Get recent uploads for the logged-in user"""
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Unauthorized'})

    user_id = session['user_id']

    # Get recent uploads (last 10)
    recent = Upload.query.filter_by(user_id=user_id) \
        .order_by(Upload.uploaded_at.desc()) \
        .limit(10).all()

    uploads_data = []
    for upload in recent:
        uploads_data.append({
            'filename': upload.original_filename,
            'species': upload.species_detected if upload.species_detected else ['Unknown species'],
            'file': {
                'original_filename': upload.original_filename
            },
            'uploaded_at': upload.uploaded_at.isoformat(),
            'file_type': upload.file_type
        })

    return jsonify({
        'success': True,
        'uploads': uploads_data
    })


# Route to serve uploaded files
@app.route('/uploads/<filename>')
def uploaded_file(filename):
    from flask import send_from_directory
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)


@app.route('/api/query-by-tags', methods=['POST'])
def query_by_tags():
    """Query files based on tags with JSON format"""
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Please login first'})
    
    try:
        data = request.get_json()
        tags = data.get('tags', [])  # e.g., ["crow", "pigeon"]
        counts = data.get('counts', [])  # e.g., [3, 2] for minimum counts
        
        # Query DynamoDB for files matching the criteria
        table = dynamodb.Table(app.config['DYNAMODB_TABLE'])
        response = table.scan()
        
        matching_files = []
        for item in response.get('Items', []):
            file_tags = item.get('tags', {})
            matches = True
            
            for i, tag in enumerate(tags):
                min_count = counts[i] if i < len(counts) else 1
                if file_tags.get(tag, 0) < min_count:
                    matches = False
                    break
            
            if matches:
                s3_url = item['s3-url']
                # Get thumbnail URL if it's an image
                thumbnail_url = None
                if '/images/' in s3_url:
                    thumbnail_url = s3_url.replace('/images/', '/thumbnails/').replace(s3_url.split('.')[-1], 'jpg')
                
                matching_files.append({
                    'url': s3_url,
                    'thumbnail': thumbnail_url,
                    'tags': file_tags
                })
        
        return jsonify({
            'success': True,
            'links': [file['thumbnail'] or file['url'] for file in matching_files],
            'files': matching_files
        })
        
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


@app.route('/api/query-by-species', methods=['POST'])
def query_by_species():
    """Find files based on bird species"""
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Please login first'})
    
    try:
        data = request.get_json()
        species = data.get('species', [])  # e.g., ["crow"]
        
        table = dynamodb.Table(app.config['DYNAMODB_TABLE'])
        response = table.scan()
        
        matching_files = []
        for item in response.get('Items', []):
            file_tags = item.get('tags', {})
            
            # Check if any of the requested species are in the file
            for sp in species:
                if sp in file_tags:
                    s3_url = item['s3-url']
                    thumbnail_url = None
                    if '/images/' in s3_url:
                        thumbnail_url = s3_url.replace('/images/', '/thumbnails/').replace(s3_url.split('.')[-1], 'jpg')
                    
                    matching_files.append({
                        'url': s3_url,
                        'thumbnail': thumbnail_url,
                        'tags': file_tags
                    })
                    break
        
        return jsonify({
            'success': True,
            'files': matching_files
        })
        
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


@app.route('/api/find-by-thumbnail', methods=['POST'])
def find_by_thumbnail():
    """Find full-size image based on thumbnail URL"""
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Please login first'})
    
    try:
        data = request.get_json()
        thumbnail_url = data.get('thumbnail_url')
        
        if not thumbnail_url:
            return jsonify({'success': False, 'message': 'Thumbnail URL is required'})
        
        # Convert thumbnail URL to original image URL
        full_size_url = thumbnail_url.replace('/thumbnails/', '/images/')
        
        return jsonify({
            'success': True,
            'full_size_url': full_size_url
        })
        
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


@app.route('/api/bulk-tag-operations', methods=['POST'])
def bulk_tag_operations():
    """Add or remove tags from multiple files"""
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Please login first'})
    
    try:
        data = request.get_json()
        urls = data.get('url', [])  # List of file URLs
        operation = data.get('operation', 1)  # 1 for add, 0 for remove
        tags = data.get('tags', [])  # List of tags to add/remove
        
        table = dynamodb.Table(app.config['DYNAMODB_TABLE'])
        
        results = []
        for url in urls:
            try:
                # Get current item
                response = table.get_item(Key={'s3-url': url})
                
                if 'Item' in response:
                    current_tags = response['Item'].get('tags', {})
                    
                    if operation == 1:  # Add tags
                        for tag in tags:
                            current_tags[tag] = current_tags.get(tag, 0) + 1
                    else:  # Remove tags
                        for tag in tags:
                            if tag in current_tags:
                                del current_tags[tag]
                    
                    # Update item
                    table.put_item(
                        Item={
                            's3-url': url,
                            'tags': current_tags
                        }
                    )
                    
                    results.append({'url': url, 'success': True})
                    
                    # Send notification if new tags were added
                    if operation == 1:
                        send_tag_notification(tags, url)
                else:
                    results.append({'url': url, 'success': False, 'message': 'File not found'})
                    
            except Exception as e:
                results.append({'url': url, 'success': False, 'message': str(e)})
        
        return jsonify({
            'success': True,
            'results': results
        })
        
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


@app.route('/api/delete-files', methods=['POST'])
def delete_files():
    """Delete files from S3 and database"""
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Please login first'})
    
    try:
        data = request.get_json()
        urls = data.get('urls', [])  # List of S3 URLs to delete
        
        table = dynamodb.Table(app.config['DYNAMODB_TABLE'])
        results = []
        
        for url in urls:
            try:
                # Extract S3 key from URL
                s3_key = url.split('amazonaws.com/')[-1]
                
                # Delete from S3
                s3_client.delete_object(
                    Bucket=app.config['AWS_S3_BUCKET'],
                    Key=s3_key
                )
                
                # Delete thumbnail if it's an image
                if '/images/' in s3_key:
                    thumbnail_key = s3_key.replace('/images/', '/thumbnails/')
                    try:
                        s3_client.delete_object(
                            Bucket=app.config['AWS_S3_BUCKET'],
                            Key=thumbnail_key
                        )
                    except:
                        pass  # Thumbnail might not exist
                
                # Delete from DynamoDB
                table.delete_item(Key={'s3-url': url})
                
                # Delete from local database
                upload = Upload.query.filter_by(file_path=url).first()
                if upload:
                    db.session.delete(upload)
                
                results.append({'url': url, 'success': True})
                
            except Exception as e:
                results.append({'url': url, 'success': False, 'message': str(e)})
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'results': results
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)})


def send_tag_notification(tags, file_url):
    """Send SNS notification when new tags are added"""
    try:
        if not app.config.get('SNS_TOPIC_ARN'):
            return  # SNS not configured
        
        message = f"New bird species detected: {', '.join(tags)}\nFile: {file_url}"
        
        sns_client.publish(
            TopicArn=app.config['SNS_TOPIC_ARN'],
            Message=message,
            Subject='Bird Detection Alert'
        )
        
    except Exception as e:
        print(f"Failed to send SNS notification: {e}")


@app.route('/api/subscribe-notifications', methods=['POST'])
def subscribe_notifications():
    """Subscribe user to tag-based notifications"""
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Please login first'})
    
    try:
        data = request.get_json()
        email = data.get('email')
        
        if not email:
            return jsonify({'success': False, 'message': 'Email is required'})
        
        if not app.config.get('SNS_TOPIC_ARN'):
            return jsonify({'success': False, 'message': 'Notifications not configured'})
        
        # Subscribe email to SNS topic
        response = sns_client.subscribe(
            TopicArn=app.config['SNS_TOPIC_ARN'],
            Protocol='email',
            Endpoint=email
        )
        
        return jsonify({
            'success': True,
            'message': 'Please check your email to confirm subscription',
            'subscription_arn': response.get('SubscriptionArn')
        })
        
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


@app.route('/api/models', methods=['GET'])
def get_models():
    """Get current model configurations"""
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Please login first'})
    
    try:
        # Call model configuration Lambda function
        if app.config.get('MODEL_CONFIG_LAMBDA_ARN'):
            response = lambda_client.invoke(
                FunctionName=app.config['MODEL_CONFIG_LAMBDA_ARN'],
                InvocationType='RequestResponse',
                Payload=json.dumps({'httpMethod': 'GET'})
            )
            
            result = json.loads(response['Payload'].read())
            return jsonify(json.loads(result['body']))
        else:
            return jsonify({'success': False, 'message': 'Model configuration not available'})
            
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


@app.route('/api/models/update', methods=['POST'])
def update_model():
    """Update model configuration"""
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Please login first'})
    
    try:
        data = request.get_json()
        
        # Call model configuration Lambda function
        if app.config.get('MODEL_CONFIG_LAMBDA_ARN'):
            response = lambda_client.invoke(
                FunctionName=app.config['MODEL_CONFIG_LAMBDA_ARN'],
                InvocationType='RequestResponse',
                Payload=json.dumps({
                    'httpMethod': 'POST',
                    'body': json.dumps(data)
                })
            )
            
            result = json.loads(response['Payload'].read())
            return jsonify(json.loads(result['body']))
        else:
            return jsonify({'success': False, 'message': 'Model configuration not available'})
            
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


@app.route('/api/models/upload-url', methods=['POST'])
def get_model_upload_url():
    """Get presigned URL for model upload"""
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Please login first'})
    
    try:
        data = request.get_json()
        
        # Call model configuration Lambda function
        if app.config.get('MODEL_CONFIG_LAMBDA_ARN'):
            response = lambda_client.invoke(
                FunctionName=app.config['MODEL_CONFIG_LAMBDA_ARN'],
                InvocationType='RequestResponse',
                Payload=json.dumps({
                    'httpMethod': 'PUT',
                    'body': json.dumps(data)
                })
            )
            
            result = json.loads(response['Payload'].read())
            return jsonify(json.loads(result['body']))
        else:
            return jsonify({'success': False, 'message': 'Model configuration not available'})
            
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


@app.route('/api/generate-report', methods=['GET'])
def generate_report():
    """Generate species statistics report"""
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Please login first'})
    
    try:
        user_id = session['user_id']
        
        # Get all uploads for user
        uploads = Upload.query.filter_by(user_id=user_id).all()
        
        # Calculate statistics
        total_files = len(uploads)
        species_stats = {}
        file_type_stats = {'image': 0, 'video': 0, 'audio': 0}
        monthly_stats = {}
        location_stats = {}
        
        for upload in uploads:
            # Count by file type
            if upload.file_type in file_type_stats:
                file_type_stats[upload.file_type] += 1
            
            # Count by species
            if upload.species_detected:
                for species in upload.species_detected:
                    species_stats[species] = species_stats.get(species, 0) + 1
            
            # Count by month
            month_key = upload.uploaded_at.strftime('%Y-%m')
            monthly_stats[month_key] = monthly_stats.get(month_key, 0) + 1
            
            # Count by location
            location = upload.location or 'Unknown'
            location_stats[location] = location_stats.get(location, 0) + 1
        
        # Get top species
        top_species = sorted(species_stats.items(), key=lambda x: x[1], reverse=True)[:10]
        
        # Get recent months stats
        recent_months = sorted(monthly_stats.items(), key=lambda x: x[0], reverse=True)[:6]
        
        report_data = {
            'summary': {
                'total_files': total_files,
                'unique_species': len(species_stats),
                'locations_visited': len([loc for loc in location_stats.keys() if loc != 'Unknown']),
                'total_storage_mb': sum(upload.file_size or 0 for upload in uploads) / (1024 * 1024)
            },
            'file_types': file_type_stats,
            'top_species': top_species,
            'recent_activity': recent_months,
            'locations': list(location_stats.items())[:10],
            'generated_at': datetime.now().isoformat()
        }
        
        return jsonify({
            'success': True,
            'report': report_data
        })
        
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


@app.route('/api/export-data', methods=['GET'])
def export_data():
    """Export user data as CSV"""
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Please login first'})
    
    try:
        user_id = session['user_id']
        uploads = Upload.query.filter_by(user_id=user_id).all()
        
        # Prepare CSV data
        import csv
        import io
        
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Write header
        writer.writerow([
            'Filename', 'Original Filename', 'File Type', 'File Size (MB)',
            'Upload Date', 'Observation Date', 'Location', 'Notes',
            'Species Detected', 'Confidence Scores', 'Tags'
        ])
        
        # Write data
        for upload in uploads:
            writer.writerow([
                upload.filename,
                upload.original_filename,
                upload.file_type,
                round((upload.file_size or 0) / (1024 * 1024), 2),
                upload.uploaded_at.strftime('%Y-%m-%d %H:%M:%S'),
                upload.observation_date.strftime('%Y-%m-%d') if upload.observation_date else '',
                upload.location or '',
                upload.notes or '',
                ', '.join(upload.species_detected or []),
                str(upload.confidence_scores or {}),
                ', '.join([tag.name for tag in upload.tags])
            ])
        
        output.seek(0)
        csv_content = output.getvalue()
        output.close()
        
        # Create response with CSV
        from flask import make_response
        response = make_response(csv_content)
        response.headers['Content-Type'] = 'text/csv'
        response.headers['Content-Disposition'] = f'attachment; filename=bird_data_export_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
        
        return response
        
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


@app.route('/api/view-map-data', methods=['GET'])
def view_map_data():
    """Get location data for map visualization"""
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Please login first'})
    
    try:
        user_id = session['user_id']
        uploads = Upload.query.filter_by(user_id=user_id).filter(Upload.location.isnot(None)).all()
        
        # Group observations by location
        location_data = {}
        for upload in uploads:
            location = upload.location
            if location and location != 'Unknown':
                if location not in location_data:
                    location_data[location] = {
                        'location': location,
                        'count': 0,
                        'species': set(),
                        'files': [],
                        'latest_date': None
                    }
                
                location_data[location]['count'] += 1
                if upload.species_detected:
                    location_data[location]['species'].update(upload.species_detected)
                
                location_data[location]['files'].append({
                    'filename': upload.original_filename,
                    'type': upload.file_type,
                    'date': upload.observation_date.isoformat() if upload.observation_date else upload.uploaded_at.isoformat(),
                    'species': upload.species_detected or []
                })
                
                # Update latest date
                obs_date = upload.observation_date or upload.uploaded_at.date()
                if not location_data[location]['latest_date'] or obs_date > location_data[location]['latest_date']:
                    location_data[location]['latest_date'] = obs_date
        
        # Convert to list and format
        map_points = []
        for loc_data in location_data.values():
            map_points.append({
                'location': loc_data['location'],
                'count': loc_data['count'],
                'species_count': len(loc_data['species']),
                'species_list': list(loc_data['species']),
                'latest_observation': loc_data['latest_date'].isoformat() if loc_data['latest_date'] else None,
                'files': loc_data['files'][:5]  # Limit to 5 most recent files
            })
        
        return jsonify({
            'success': True,
            'locations': map_points,
            'total_locations': len(map_points)
        })
        
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


@app.route('/api/manage-tags', methods=['GET'])
def get_user_tags():
    """Get all tags used by the user for management"""
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Please login first'})
    
    try:
        user_id = session['user_id']
        
        # Get all tags from user's uploads
        user_tags = db.session.query(Tag.name, Tag.category, db.func.count(Upload.id).label('usage_count')) \
            .join(upload_tags) \
            .join(Upload) \
            .filter(Upload.user_id == user_id) \
            .group_by(Tag.id) \
            .order_by(db.func.count(Upload.id).desc()) \
            .all()
        
        # Get species detected across all uploads
        uploads = Upload.query.filter_by(user_id=user_id).all()
        species_usage = {}
        for upload in uploads:
            if upload.species_detected:
                for species in upload.species_detected:
                    species_usage[species] = species_usage.get(species, 0) + 1
        
        tags_data = []
        for tag_name, category, count in user_tags:
            tags_data.append({
                'name': tag_name,
                'category': category or 'general',
                'usage_count': count,
                'type': 'manual'
            })
        
        # Add auto-detected species
        for species, count in species_usage.items():
            if not any(tag['name'] == species for tag in tags_data):
                tags_data.append({
                    'name': species,
                    'category': 'species',
                    'usage_count': count,
                    'type': 'auto-detected'
                })
        
        return jsonify({
            'success': True,
            'tags': tags_data,
            'total_tags': len(tags_data)
        })
        
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


@app.route('/api/manage-tags', methods=['POST'])
def update_user_tags():
    """Update or create tags for user uploads"""
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Please login first'})
    
    try:
        data = request.get_json()
        action = data.get('action')  # 'add', 'remove', 'rename'
        tag_name = data.get('tag_name')
        new_tag_name = data.get('new_tag_name')  # For rename action
        category = data.get('category', 'general')
        upload_ids = data.get('upload_ids', [])  # Specific uploads to tag
        
        user_id = session['user_id']
        
        if action == 'add':
            # Create or get existing tag
            tag = Tag.query.filter_by(name=tag_name, category=category).first()
            if not tag:
                tag = Tag(name=tag_name, category=category)
                db.session.add(tag)
                db.session.flush()  # Get the ID
            
            # Add tag to specified uploads or all user uploads if none specified
            if upload_ids:
                uploads = Upload.query.filter(Upload.id.in_(upload_ids), Upload.user_id == user_id).all()
            else:
                uploads = Upload.query.filter_by(user_id=user_id).all()
            
            for upload in uploads:
                if tag not in upload.tags:
                    upload.tags.append(tag)
            
            db.session.commit()
            return jsonify({'success': True, 'message': f'Tag "{tag_name}" added to {len(uploads)} files'})
        
        elif action == 'remove':
            # Remove tag from user's uploads
            tag = Tag.query.filter_by(name=tag_name).first()
            if tag:
                uploads = Upload.query.filter_by(user_id=user_id).all()
                for upload in uploads:
                    if tag in upload.tags:
                        upload.tags.remove(tag)
                
                db.session.commit()
                return jsonify({'success': True, 'message': f'Tag "{tag_name}" removed from your uploads'})
            else:
                return jsonify({'success': False, 'message': 'Tag not found'})
        
        elif action == 'rename':
            # Rename tag (create new, transfer associations, delete old)
            old_tag = Tag.query.filter_by(name=tag_name).first()
            if old_tag:
                new_tag = Tag.query.filter_by(name=new_tag_name, category=old_tag.category).first()
                if not new_tag:
                    new_tag = Tag(name=new_tag_name, category=old_tag.category)
                    db.session.add(new_tag)
                    db.session.flush()
                
                # Transfer associations for user's uploads only
                uploads = Upload.query.filter_by(user_id=user_id).all()
                for upload in uploads:
                    if old_tag in upload.tags:
                        upload.tags.remove(old_tag)
                        if new_tag not in upload.tags:
                            upload.tags.append(new_tag)
                
                db.session.commit()
                return jsonify({'success': True, 'message': f'Tag renamed from "{tag_name}" to "{new_tag_name}"'})
            else:
                return jsonify({'success': False, 'message': 'Original tag not found'})
        
        else:
            return jsonify({'success': False, 'message': 'Invalid action'})
            
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)})


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
