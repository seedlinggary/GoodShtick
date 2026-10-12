import hmac
import os
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


def cron_secret_required(f):
    """For endpoints meant to be hit by a scheduler (Vercel Cron, or an
    external one like cron-job.org) rather than a logged-in user -- compares
    an `X-Cron-Secret` header against CRON_SECRET using a constant-time
    comparison. If CRON_SECRET isn't set, the endpoint refuses every request
    rather than silently accepting an unauthenticated one."""
    @wraps(f)
    def decorated(*args, **kwargs):
        expected = os.environ.get('CRON_SECRET')
        provided = request.headers.get('X-Cron-Secret', '')
        if not expected or not hmac.compare_digest(expected, provided):
            return jsonify({'message': 'Not authorized'}), 401
        return f(*args, **kwargs)
    return decorated
