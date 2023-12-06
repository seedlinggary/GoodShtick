import os
from flask_sqlalchemy import SQLAlchemy
from flask_marshmallow import Marshmallow
from flask import Flask
from flask_mail import Mail
from flask_cors import CORS
from flask_migrate import Migrate
from dotenv import load_dotenv
load_dotenv()
db = SQLAlchemy()
ma = Marshmallow()
application = Flask(__name__)

CORS(application)
UPLOAD_FOLDER = 'uploadedFiles'
application.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get('SQLALCHEMY_DATABASE_URI')
# stripe.api_key = os.environ.get('STRIPE_API_KEY')

application.config['SECRET_KEY'] = os.environ.get('SECRET_KEY')
application.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
application.config['MAIL_SERVER']='smtp.gmail.com'
application.config['MAIL_PORT'] = 465
application.config['MAIL_USERNAME'] = os.environ.get('MAIL_USERNAME')
application.config['MAIL_PASSWORD'] = os.environ.get('MAIL_PASSWORD')
application.config['MAIL_USE_TLS'] = False
application.config['MAIL_USE_SSL'] = True
application.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
db.init_app(application)
ma.init_app(application)
mail = Mail(application)
migrate = Migrate(application, db)




# DvqLRJOQNjWfproc
