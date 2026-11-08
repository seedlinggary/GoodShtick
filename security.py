import hmac
import os
import jwt
from functools import wraps
from flask import jsonify, request
from backend.user.modals.user import User
from config import application


def real_client_ip():
    """request.remote_addr, as seen by this app's WSGI layer on Vercel's
    Python runtime, is NOT the visitor's real IP -- it's an address on
    Vercel's own internal routing path, the same for every request
    regardless of who's actually connecting. One caller already worked
    around this by hand (nonprofit_webhook.py's own _request_ip, there to
    verify a webhook's source IP against an allowlist); every per-IP
    throttle in this codebase (guest submissions, the AI site builder,
    this analytics beacon's new-session cap) used request.remote_addr
    directly and so was silently rate-limiting the ENTIRE SITE under one
    shared bucket instead of one bucket per real visitor -- on the
    analytics beacon specifically, that meant only the first
    NEW_SESSION_DAILY_CAP visitors *site-wide* each day ever got a
    country/session recorded at all, which is what made "top countries"
    collapse to whichever country happens to show up early in the UTC
    day. X-Forwarded-For (Vercel sets this to the real client IP, first
    entry if there's a chain) is the actual signal; X-Real-IP and
    remote_addr are only fallbacks for a request that somehow arrives
    without it."""
    forwarded = request.headers.get('X-Forwarded-For')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.headers.get('X-Real-IP') or request.remote_addr


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
