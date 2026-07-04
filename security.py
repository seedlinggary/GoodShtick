import jwt
from functools import wraps
from flask import jsonify, request
from backend.user.modals.user import User
from config import application


def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get('x-access-token')
        if not token:
            return jsonify({"message": "Token is missing"}), 401
        try:
            data = jwt.decode(token, application.config['SECRET_KEY'], algorithms=["HS256"])
            current_user = User.query.filter_by(public_id=data['public_id']).first()
            if not current_user:
                return jsonify({"message": "User not found"}), 401
        except jwt.ExpiredSignatureError:
            return jsonify({"message": "Token has expired"}), 401
        except jwt.InvalidTokenError:
            return jsonify({"message": "Token is invalid"}), 401
        return f(current_user, *args, **kwargs)
    return decorated


def token_optional(f):
    """Passes current_user if token present and valid, else None."""
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get('x-access-token')
        current_user = None
        if token:
            try:
                data = jwt.decode(token, application.config['SECRET_KEY'], algorithms=["HS256"])
                current_user = User.query.filter_by(public_id=data['public_id']).first()
            except jwt.InvalidTokenError:
                pass
        return f(current_user, *args, **kwargs)
    return decorated


def role_required(*roles):
    """Decorator factory — passes only if current user's role is in the given list."""
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            token = request.headers.get('x-access-token')
            if not token:
                return jsonify({"message": "Token is missing"}), 401
            try:
                data = jwt.decode(token, application.config['SECRET_KEY'], algorithms=["HS256"])
                current_user = User.query.filter_by(public_id=data['public_id']).first()
                if not current_user:
                    return jsonify({"message": "User not found"}), 401
            except jwt.ExpiredSignatureError:
                return jsonify({"message": "Token has expired"}), 401
            except jwt.InvalidTokenError:
                return jsonify({"message": "Token is invalid"}), 401
            if current_user.role not in roles:
                return jsonify({"message": "Insufficient permissions"}), 403
            return f(current_user, *args, **kwargs)
        return decorated
    return decorator


admin_required = role_required('admin', 'super_admin')
super_admin_required = role_required('super_admin')
