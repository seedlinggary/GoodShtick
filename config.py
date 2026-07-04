import os
from flask_sqlalchemy import SQLAlchemy
from flask_marshmallow import Marshmallow
from flask import Flask
from flask_mail import Mail
from flask_cors import CORS
from flask_migrate import Migrate
from flask_caching import Cache
from flask_compress import Compress
from dotenv import load_dotenv

load_dotenv()

db = SQLAlchemy()
ma = Marshmallow()
cache = Cache()
application = Flask(__name__)

# FRONTEND_ORIGINS: comma-separated list of allowed origins (set in .env)
_origins_raw = os.environ.get('FRONTEND_ORIGINS', 'http://localhost:3000,http://127.0.0.1:3000')
FRONTEND_ORIGINS = [o.strip() for o in _origins_raw.split(',') if o.strip()]
CORS(application, origins=FRONTEND_ORIGINS, supports_credentials=True)

UPLOAD_FOLDER = 'uploadedFiles'

application.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('SQLALCHEMY_DATABASE_URI')
application.config['SECRET_KEY'] = os.environ.get('SECRET_KEY')
application.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Cache: simple in-memory, no Redis required
application.config['CACHE_TYPE'] = 'SimpleCache'
application.config['CACHE_DEFAULT_TIMEOUT'] = 60  # seconds

# Compression: gzip all JSON/text responses automatically
application.config['COMPRESS_REGISTER'] = True
application.config['COMPRESS_MIMETYPES'] = [
    'application/json', 'text/html', 'text/css', 'application/javascript'
]

application.config['MAIL_SERVER'] = 'smtp.gmail.com'
application.config['MAIL_PORT'] = 465
application.config['MAIL_USERNAME'] = os.environ.get('MAIL_USERNAME')
application.config['MAIL_PASSWORD'] = os.environ.get('MAIL_PASSWORD')
application.config['MAIL_USE_TLS'] = False
application.config['MAIL_USE_SSL'] = True
application.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

db.init_app(application)
ma.init_app(application)
cache.init_app(application)
Compress(application)
mail = Mail(application)
migrate = Migrate(application, db)




# DvqLRJOQNjWfproc
