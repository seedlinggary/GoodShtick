import uuid
from datetime import datetime, timedelta, timezone

import jwt
from flask import Blueprint, jsonify, request

from config import application, cache
from security import token_required
from backend.user.modals.user import User

sso_api = Blueprint('sso_api', __name__, url_prefix='/sso')

# Short-lived on purpose: this token only exists to survive the one redirect
# from goodshtick.com to the business domain (or back). It's carried in the
# URL fragment (never sent to the server, so it never hits access logs or a
# Referer header) and is single-use -- see /exchange.
SSO_TOKEN_TTL_SECONDS = 60


@sso_api.route('/create', methods=['POST'])
@token_required
def create_sso_token(current_user):
    """Issues a one-time handoff token for the cross-site 'switch sides'
    footer link -- lets the other domain log the same user in without a
    shared cookie jar (the two domains are genuinely separate origins)."""
    jti = uuid.uuid4().hex
    token = jwt.encode(
        {
            'public_id': current_user.public_id,
            'purpose': 'sso',
            'jti': jti,
            'exp': datetime.now(timezone.utc) + timedelta(seconds=SSO_TOKEN_TTL_SECONDS),
        },
        application.config['SECRET_KEY'],
        algorithm='HS256',
    )
    return jsonify({'sso_token': token})


@sso_api.route('/exchange', methods=['POST'])
def exchange_sso_token():
    """Public -- the token itself is the credential. Verifies signature,
    expiry, purpose, and single-use via a short cache entry keyed by jti,
    then returns the same payload shape as /login."""
    body = request.get_json() or {}
    token = body.get('sso_token')
    if not token:
        return jsonify({'message': 'sso_token is required'}), 400

    try:
        data = jwt.decode(token, application.config['SECRET_KEY'], algorithms=['HS256'])
    except jwt.ExpiredSignatureError:
        return jsonify({'message': 'This link has expired -- go back and try again'}), 401
    except jwt.InvalidTokenError:
        return jsonify({'message': 'Invalid token'}), 401

    if data.get('purpose') != 'sso':
        return jsonify({'message': 'Invalid token'}), 401

    jti = data.get('jti')
    cache_key = f'sso_used:{jti}'
    if not jti or cache.get(cache_key):
        return jsonify({'message': 'This link has already been used'}), 401
    cache.set(cache_key, True, timeout=SSO_TOKEN_TTL_SECONDS + 30)

    user = User.query.filter_by(public_id=data['public_id']).first()
    if not user:
        return jsonify({'message': 'User not found'}), 401

    session_token = jwt.encode(
        {'public_id': user.public_id, 'exp': datetime.now(timezone.utc) + timedelta(days=7)},
        application.config['SECRET_KEY'],
        algorithm='HS256',
    )
    return jsonify({'token': session_token, 'role': user.role, 'is_boss': user.is_boss,
                    'profile_name': user.profile_name, 'public_id': user.public_id})
