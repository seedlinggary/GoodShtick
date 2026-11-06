"""Family-portal auth -- a THIRD, separate token scheme alongside the
platform's own x-access-token and nonprofit staff's X-Nonprofit-Token (see
nonprofit_auth.py's docstring for why staff got its own scheme; the same
reasoning applies here, one level further: a family member is neither a
platform User nor a nonprofit staff account, just someone who proved they
own an email address a NonprofitFamily row is tagged with). Its own header
(X-Family-Token) and payload shape ({family_id, business_id}) mean it can
never be replayed against either other scheme, same as nonprofit_auth.py.

Deliberately NOT a password-based login -- see
modals/nonprofit.py:NonprofitFamilyLoginCode's docstring. This module only
decodes/verifies an already-issued token; the request-code/verify-code
exchange that issues one lives in routes/nonprofit_family_portal.py
alongside the rest of that blueprint's public endpoints."""
from datetime import datetime, timedelta
from functools import wraps

import jwt
from flask import jsonify, request

from config import application
from backend.business.modals.nonprofit import NonprofitFamily

TOKEN_HEADER = 'X-Family-Token'
# Longer-lived than staff's 14 days -- this is read-only, lower-stakes
# access (no payment config, no other families' data), and the whole
# point is a family member can bookmark/revisit without re-requesting a
# code by email every time.
TOKEN_TTL_DAYS = 30


def generate_family_token(family):
    payload = {
        'family_id': family.id,
        'business_id': family.business_id,
        'exp': datetime.utcnow() + timedelta(days=TOKEN_TTL_DAYS),
    }
    return jwt.encode(payload, application.config['SECRET_KEY'], algorithm='HS256')


def _decode_family(token):
    """Returns (family, error_response_or_None)."""
    if not token:
        return None, (jsonify({'message': 'Token is missing'}), 401)
    try:
        data = jwt.decode(token, application.config['SECRET_KEY'], algorithms=['HS256'])
    except jwt.ExpiredSignatureError:
        return None, (jsonify({'message': 'Your session has expired -- please request a new code'}), 401)
    except jwt.InvalidTokenError:
        return None, (jsonify({'message': 'Token is invalid'}), 401)
    family_id = data.get('family_id')
    if family_id is None:
        return None, (jsonify({'message': 'Token is invalid'}), 401)
    family = NonprofitFamily.query.get(family_id)
    if not family:
        return None, (jsonify({'message': 'Family account not found'}), 401)
    return family, None


def family_required(f):
    """Passes the NonprofitFamily row as the first arg. Does NOT check
    which business/subdomain the family belongs to -- every route taking
    a subdomain must separately confirm family.business_id matches the
    business that subdomain resolves to, same as nonprofit_auth.py's
    staff_required leaves that check to require_same_business."""
    @wraps(f)
    def decorated(*args, **kwargs):
        family, err = _decode_family(request.headers.get(TOKEN_HEADER))
        if err:
            return err
        return f(family, *args, **kwargs)
    return decorated
