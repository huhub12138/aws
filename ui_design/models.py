from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


class User(db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=True)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    uploads = db.relationship('Upload', backref='user', lazy=True, cascade='all, delete-orphan')
    queries = db.relationship('SearchQuery', backref='user', lazy=True, cascade='all, delete-orphan')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def to_dict(self):
        return {
            'id': self.id,
            'username': self.username,
            'email': self.email,
            'created_at': self.created_at.isoformat()
        }


class Upload(db.Model):
    __tablename__ = 'uploads'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    original_filename = db.Column(db.String(255), nullable=False)
    file_path = db.Column(db.String(500), nullable=False)
    file_type = db.Column(db.String(50))  # image, video, audio
    file_size = db.Column(db.Integer)  # in bytes

    # Metadata
    location = db.Column(db.String(255))
    observation_date = db.Column(db.Date)
    notes = db.Column(db.Text)

    # Auto-tagging results
    species_detected = db.Column(db.JSON)  # List of detected species
    confidence_scores = db.Column(db.JSON)  # Confidence scores for each species

    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    tags = db.relationship('Tag', secondary='upload_tags', backref='uploads', lazy=True)

    def to_dict(self):
        return {
            'id': self.id,
            'filename': self.filename,
            'original_filename': self.original_filename,
            'file_type': self.file_type,
            'file_size': self.file_size,
            'location': self.location,
            'observation_date': self.observation_date.isoformat() if self.observation_date else None,
            'notes': self.notes,
            'species_detected': self.species_detected,
            'uploaded_at': self.uploaded_at.isoformat(),
            'tags': [tag.name for tag in self.tags]
        }


class Tag(db.Model):
    __tablename__ = 'tags'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    category = db.Column(db.String(50))  # species, behavior, habitat, etc.
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


# Association table for many-to-many relationship
upload_tags = db.Table('upload_tags',
                       db.Column('upload_id', db.Integer, db.ForeignKey('uploads.id'), primary_key=True),
                       db.Column('tag_id', db.Integer, db.ForeignKey('tags.id'), primary_key=True)
                       )


class Species(db.Model):
    __tablename__ = 'species'

    id = db.Column(db.Integer, primary_key=True)
    common_name = db.Column(db.String(100), nullable=False)
    scientific_name = db.Column(db.String(100), unique=True)
    family = db.Column(db.String(100))
    description = db.Column(db.Text)
    habitat = db.Column(db.String(255))
    conservation_status = db.Column(db.String(50))

    def to_dict(self):
        return {
            'id': self.id,
            'common_name': self.common_name,
            'scientific_name': self.scientific_name,
            'family': self.family,
            'conservation_status': self.conservation_status
        }


class SearchQuery(db.Model):
    __tablename__ = 'search_queries'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    query_params = db.Column(db.JSON)  # Store search parameters
    result_count = db.Column(db.Integer)
    executed_at = db.Column(db.DateTime, default=datetime.utcnow)


class PasswordResetToken(db.Model):
    __tablename__ = 'password_reset_tokens'

    id = db.Column(db.Integer, primary_key=True)
    token = db.Column(db.String(100), unique=True, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    used = db.Column(db.Boolean, default=False)

    user = db.relationship('User', backref='reset_tokens')