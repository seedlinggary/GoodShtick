"""Nonprofit staff auth -- deliberately NOT security.py's token_required.
That decorator looks up a community User by public_id from an
`x-access-token` header; a nonprofit staff login is a wholly separate
account system (see modals/nonprofit.py:NonprofitStaff's own docstring for
why), so it gets its own header (`X-Nonprofit-Token`, never confused with
the main site's token even in a browser logged into both at once) and its
own JWT payload shape ({staff_id, business_id}, not {public_id}).

Signed with the same application SECRET_KEY as every other token in this
app (one signing secret for the whole deployment is the existing
convention -- see security.py) but that shape difference means a main-site
token can never be replayed here and vice versa: decoding succeeds either
way (same secret), but the lookup this does (NonprofitStaff.id from
staff_id) is meaningless against a community-user payload's public_id
field, which doesn't exist as staff_id, so jwt.decode never finds a
staff_id key and the request is rejected as if the token were simply
missing."""
from datetime import datetime, timedelta
from functools import wraps

import jwt
from flask import jsonify, request

from config import application
from backend.business.modals.nonprofit import NonprofitStaff

TOKEN_HEADER = 'X-Nonprofit-Token'
TOKEN_TTL_DAYS = 14


def generate_staff_token(staff):
    payload = {
        'staff_id': staff.id,
        'business_id': staff.business_id,
        'exp': datetime.utcnow() + timedelta(days=TOKEN_TTL_DAYS),
    }
    return jwt.encode(payload, application.config['SECRET_KEY'], algorithm='HS256')


def _decode_staff(token):
    """Returns (staff, error_response_or_None)."""
    if not token:
        return None, (jsonify({'message': 'Token is missing'}), 401)
    try:
        data = jwt.decode(token, application.config['SECRET_KEY'], algorithms=['HS256'])
    except jwt.ExpiredSignatureError:
        return None, (jsonify({'message': 'Token has expired'}), 401)
    except jwt.InvalidTokenError:
        return None, (jsonify({'message': 'Token is invalid'}), 401)
    staff_id = data.get('staff_id')
    if staff_id is None:
        return None, (jsonify({'message': 'Token is invalid'}), 401)
    staff = NonprofitStaff.query.get(staff_id)
    if not staff:
        return None, (jsonify({'message': 'Staff account not found'}), 401)
    return staff, None


def staff_required(f):
    """Passes the NonprofitStaff row as the first arg. Does NOT check
    which business the staff belongs to -- routes taking a business_id (or
    resolving one from a subdomain) must separately confirm
    staff.business_id matches, same as every other owner-gated route in
    this codebase checks _can_manage. See require_same_business below."""
    @wraps(f)
    def decorated(*args, **kwargs):
        staff, err = _decode_staff(request.headers.get(TOKEN_HEADER))
        if err:
            return err
        return f(staff, *args, **kwargs)
    return decorated


def superadmin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        staff, err = _decode_staff(request.headers.get(TOKEN_HEADER))
        if err:
            return err
        if staff.role != 'superadmin':
            return jsonify({'message': 'Only a super admin can do this.'}), 403
        return f(staff, *args, **kwargs)
    return decorated


def require_same_business(staff, business_id):
    """None if staff may act on this business, else an (response, status)
    tuple to return immediately. A staff login is scoped to exactly one
    business -- unlike a platform User, there's no is_boss-style escape
    hatch here, since nonprofit staff accounts are customer accounts, not
    platform-operator ones."""
    if staff.business_id != business_id:
        return jsonify({'message': 'Not authorized for this organization'}), 403
    return None
