from datetime import datetime

from flask import Blueprint, jsonify, request
from backend.user.modals.user import User
from backend.user.schemas.user import users_schema, user_schema
from config import db
from security import token_required
from werkzeug.security import generate_password_hash
import uuid

user_api = Blueprint('user_api', __name__, url_prefix='/user')

VALID_GENDERS = {'male', 'female', 'other'}


@user_api.route('/new_email', methods=['POST'])
def check_email():
    email = request.get_json()
    if not email or not isinstance(email, str):
        return jsonify({'message': 'Email is required'}), 400
    exists = User.query.filter_by(email=email).first() is not None
    return jsonify('exists' if exists else None)


@user_api.route('', methods=['GET'])
def get_users():
    all_users = User.query.all()
    return jsonify(users_schema.dump(all_users))


@user_api.route('', methods=['POST'])
def add_user():
    body = request.get_json()
    if not body:
        return jsonify({'message': 'Request body is required'}), 400
    required = ['first_name', 'last_name', 'email', 'profile_name', 'password']
    missing = [f for f in required if not body.get(f)]
    if missing:
        return jsonify({'message': f'Missing fields: {", ".join(missing)}'}), 400
    if User.query.filter_by(email=body['email']).first():
        return jsonify({'message': 'An account with this email already exists'}), 409
    if User.query.filter_by(profile_name=body['profile_name']).first():
        return jsonify({'message': 'That profile name is already taken'}), 409
    hashed_password = generate_password_hash(body['password'], method='pbkdf2:sha256')
    new_user = User(
        public_id=str(uuid.uuid4()),
        first_name=body['first_name'],
        last_name=body['last_name'],
        email=body['email'],
        profile_name=body['profile_name'],
        password=hashed_password
    )
    db.session.add(new_user)
    db.session.commit()
    return jsonify(user_schema.dump(new_user)), 201


@user_api.route('/profile', methods=['PUT'])
@token_required
def update_profile(current_user):
    """Self-service update of the optional ad-targeting fields. Never required, never role/email."""
    body = request.get_json() or {}

    if 'birthdate' in body:
        raw = body['birthdate']
        if not raw:
            current_user.birthdate = None
        else:
            try:
                current_user.birthdate = datetime.strptime(raw, '%Y-%m-%d').date()
            except ValueError:
                return jsonify({'message': 'birthdate must be in YYYY-MM-DD format'}), 400

    if 'gender' in body:
        gender = (body['gender'] or '').lower() or None
        if gender and gender not in VALID_GENDERS:
            return jsonify({'message': f'Invalid gender. Must be one of: {", ".join(VALID_GENDERS)}'}), 400
        current_user.gender = gender

    if 'location_country' in body:
        current_user.location_country = body['location_country'] or None
    if 'location_city' in body:
        current_user.location_city = body['location_city'] or None

    db.session.commit()
    return jsonify(user_schema.dump(current_user))


@user_api.route('/<public_id>', methods=['GET'])
@token_required
def get_user(_current_user, public_id):
    user = User.query.filter_by(public_id=public_id).first()
    if not user:
        return jsonify({'message': 'User not found'}), 404
    return jsonify(user_schema.dump(user))


@user_api.route('/<public_id>', methods=['DELETE'])
@token_required
def delete_user(current_user, public_id):
    if not current_user.is_boss and current_user.public_id != public_id:
        return jsonify({'message': 'Not authorized'}), 403
    user = db.session.get(User, public_id)
    if not user:
        return jsonify({'message': 'User not found'}), 404
    db.session.delete(user)
    db.session.commit()
    return jsonify(user_schema.dump(user))
