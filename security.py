import jwt
from functools import wraps
from flask import jsonify, request
from backend.user.modals.user import User
from config import application


def token_required(f):
    @wraps(f)
    def decorated(*args,**kwargs):
        token = None
        if 'x-access-token' in request.headers:
            token = request.headers['x-access-token']
        if not token:
            return jsonify({"messgae": "token missing"}), 401
        try:
            data = jwt.decode(token, application.config.get('SECRET_KEY'), algorithms="HS256")
            current_user =User.query.filter_by(public_id = data['public_id']).first()
        except:
            
            return jsonify({"messgae": "token is invalid"}), 401
        return f( current_user, *args, **kwargs)
    return decorated
