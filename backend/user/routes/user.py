from flask import Blueprint, jsonify, request
from backend.user.modals.user import User
from backend.user.schemas.user import users_schema, user_schema
from config import db
from security import token_required
from werkzeug.security import generate_password_hash
import uuid

user_api = Blueprint('user_api', __name__,url_prefix='/user') 


@user_api.route('/new_email', methods=['POST'])
def get_user_email():
    # user = User.query.get(public_id)
    user = User.query.filter_by(email=request.json).first()
    if user:
        return jsonify('exists') 
    else:
        return jsonify(None)
@user_api.route('', methods=['GET'])
def get_users():
    all_users = User.query.all()
    result = users_schema.dump(all_users)
    return jsonify(result)

@user_api.route('/<id>', methods=['DELETE'])
@token_required
def delete_user(current_user, id):
    user = User.query.get(id)
    db.session.delete(user)
    db.session.commit()
    return user_schema.jsonify(user)

@user_api.route('', methods=['POST'])
def add_user():
    first_name = request.json['first_name']
    last_name = request.json['last_name']
    email = request.json['email']
    profile_name = request.json['profile_name']
    hashed_password = generate_password_hash(request.json['password'], method='pbkdf2:sha256')
    new_user = User(public_id=str(uuid.uuid4()),first_name=first_name,last_name= last_name, password=hashed_password, email=email, profile_name=profile_name)
    db.session.add(new_user)
    db.session.commit()
    return user_schema.jsonify(new_user)




@user_api.route('/<public_id>', methods=['GET'])
@token_required
def get_user(current_user,public_id):
    # user = User.query.get(public_id)
    user = User.query.filter_by(public_id=public_id).first() 
    return user_schema.jsonify(user)

