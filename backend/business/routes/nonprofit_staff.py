"""Nonprofit staff login + staff-account management.

Two ways into the nonprofit module's admin API, both ending in the same
X-Nonprofit-Token JWT (see nonprofit_auth.py):
  1. THE OWNER'S OWN ACCESS -- auto_login_as_owner() below. The owner
     manages this from the exact same dashboard (and the exact same
     community-User login) they already build their site with -- no
     separate signup/login step, no separate credentials to remember.
     The frontend calls this once when the owner opens the nonprofit
     section of their dashboard; it silently finds-or-creates a
     superadmin NonprofitStaff row keyed to the owner's own email and
     hands back a token, the same shape a real staff login would.
  2. DELEGATED STAFF -- for a nonprofit that wants someone else (a
     bookkeeper, a gabbai) to have their OWN restricted login without
     giving them the owner's own platform account: the owner creates
     that account from Settings -> Staff accounts (see create_staff()
     below), and that person logs in independently at
     /nonprofit/by-subdomain/<subdomain>/staff/login with their own
     email+password. Still available, just no longer the primary path
     for the owner's own access.
"""
import secrets

from flask import Blueprint, jsonify, request
from werkzeug.security import generate_password_hash, check_password_hash

from config import db
from security import token_required
from backend.business.modals.business import Business
from backend.business.modals.business_site import BusinessSite
from backend.business.modals.nonprofit import NonprofitStaff, NONPROFIT_STAFF_ROLES
from backend.business.nonprofit_auth import staff_required, superadmin_required, generate_staff_token

nonprofit_staff_api = Blueprint('nonprofit_staff_api', __name__)

NAME_MAX, EMAIL_MAX, PASSWORD_MIN = 150, 150, 8


def _can_manage(business, user):
    if not user:
        return False
    if user.is_boss:
        return True
    if business.owner_user_id:
        return business.owner_user_id == user.public_id
    return business.created_by == user.public_id


def _serialize_staff(staff):
    return {
        'id': staff.id,
        'business_id': staff.business_id,
        'email': staff.email,
        'name': staff.name,
        'role': staff.role,
        'created_at': staff.created_at.isoformat() if staff.created_at else None,
    }


@nonprofit_staff_api.route('/nonprofit/businesses/<int:business_id>/staff/auto-login', methods=['POST'])
@token_required
def auto_login_as_owner(current_user, business_id):
    """The owner's OWN way in -- called once, silently, when they open the
    nonprofit section inside their regular dashboard. Finds-or-creates a
    superadmin NonprofitStaff row keyed to the owner's own email (so
    re-opening the section later re-finds the SAME row rather than piling
    up duplicates) and hands back a real staff token, exactly as if
    they'd logged in through the separate staff form -- except they never
    see that form at all. The password hash on this row is a throwaway
    random value, never shown or used anywhere: this account is never
    meant to be logged into through the password form, only reached
    through this endpoint's own owner-auth check."""
    business = db.session.get(Business, business_id)
    if not business:
        return jsonify({'message': 'Business not found'}), 404
    if not _can_manage(business, current_user):
        return jsonify({'message': 'Not authorized'}), 403

    email = (current_user.email or '').strip().lower()
    staff = NonprofitStaff.query.filter_by(business_id=business_id, email=email).first()
    if not staff:
        name = f'{current_user.first_name or ""} {current_user.last_name or ""}'.strip() or email
        staff = NonprofitStaff(
            business_id=business_id, email=email,
            password_hash=generate_password_hash(secrets.token_urlsafe(32), method='pbkdf2:sha256'),
            name=name, role='superadmin',
        )
        db.session.add(staff)

        site = BusinessSite.query.filter_by(business_id=business_id).first()
        if site:
            merged = dict(site.enabled_modules or {})
            merged['nonprofit'] = True
            site.enabled_modules = merged

        db.session.commit()

    return jsonify({'staff': _serialize_staff(staff), 'token': generate_staff_token(staff)})


@nonprofit_staff_api.route('/nonprofit/businesses/<int:business_id>/staff/exists', methods=['GET'])
@token_required
def staff_exists(current_user, business_id):
    """Owner-authenticated (not staff-authenticated) check -- lets the
    owner-dashboard's bootstrap card know whether to show the "set up
    staff login" form or the "open staff portal" link, without the owner
    having to actually log in as staff first just to find out."""
    business = db.session.get(Business, business_id)
    if not business:
        return jsonify({'message': 'Business not found'}), 404
    if not _can_manage(business, current_user):
        return jsonify({'message': 'Not authorized'}), 403
    exists = NonprofitStaff.query.filter_by(business_id=business_id).first() is not None
    return jsonify({'exists': exists})


@nonprofit_staff_api.route('/nonprofit/businesses/<int:business_id>/staff/bootstrap', methods=['POST'])
@token_required
def bootstrap_staff(current_user, business_id):
    business = db.session.get(Business, business_id)
    if not business:
        return jsonify({'message': 'Business not found'}), 404
    if not _can_manage(business, current_user):
        return jsonify({'message': 'Not authorized'}), 403
    if NonprofitStaff.query.filter_by(business_id=business_id).first():
        return jsonify({'message': 'A staff account already exists for this organization -- ask an existing super admin to add you'}), 409

    body = request.get_json() or {}
    email = (body.get('email') or '').strip().lower()
    name = (body.get('name') or '').strip()
    password = body.get('password') or ''
    if not email or '@' not in email or len(email) > EMAIL_MAX:
        return jsonify({'message': 'A valid email is required'}), 400
    if not name or len(name) > NAME_MAX:
        return jsonify({'message': f'name is required (max {NAME_MAX} characters)'}), 400
    if len(password) < PASSWORD_MIN:
        return jsonify({'message': f'Password must be at least {PASSWORD_MIN} characters'}), 400

    site = BusinessSite.query.filter_by(business_id=business_id).first()
    if site:
        merged = dict(site.enabled_modules or {})
        merged['nonprofit'] = True
        site.enabled_modules = merged

    staff = NonprofitStaff(
        business_id=business_id, email=email,
        password_hash=generate_password_hash(password, method='pbkdf2:sha256'),
        name=name, role='superadmin',
    )
    db.session.add(staff)
    db.session.commit()
    return jsonify({'staff': _serialize_staff(staff), 'token': generate_staff_token(staff)}), 201


@nonprofit_staff_api.route('/nonprofit/by-subdomain/<subdomain>/staff/login', methods=['POST'])
def staff_login(subdomain):
    site = BusinessSite.query.filter_by(subdomain=(subdomain or '').strip().lower()).first()
    if not site:
        return jsonify({'message': 'Organization not found'}), 404

    body = request.get_json() or {}
    email = (body.get('email') or '').strip().lower()
    password = body.get('password') or ''
    # Generic error either way -- no "no such email" vs "wrong password"
    # distinction, same no-user-enumeration-leak the ported system's own
    # login form has.
    invalid = (jsonify({'message': 'Invalid email or password.'}), 401)
    if not email or not password:
        return invalid

    staff = NonprofitStaff.query.filter_by(business_id=site.business_id, email=email).first()
    if not staff or not check_password_hash(staff.password_hash, password):
        return invalid

    return jsonify({'staff': _serialize_staff(staff), 'token': generate_staff_token(staff)})


@nonprofit_staff_api.route('/nonprofit/staff/me', methods=['GET'])
@staff_required
def get_me(staff):
    return jsonify(_serialize_staff(staff))


@nonprofit_staff_api.route('/nonprofit/staff/me/password', methods=['PATCH'])
@staff_required
def change_own_password(staff):
    body = request.get_json() or {}
    current = body.get('current_password') or ''
    new = body.get('new_password') or ''
    if not check_password_hash(staff.password_hash, current):
        return jsonify({'message': 'Current password is incorrect'}), 400
    if len(new) < PASSWORD_MIN:
        return jsonify({'message': f'Password must be at least {PASSWORD_MIN} characters'}), 400
    staff.password_hash = generate_password_hash(new, method='pbkdf2:sha256')
    db.session.commit()
    return jsonify({'message': 'Password updated'})


@nonprofit_staff_api.route('/nonprofit/businesses/<int:business_id>/staff', methods=['GET'])
@staff_required
def list_staff(staff, business_id):
    if staff.business_id != business_id:
        return jsonify({'message': 'Not authorized for this organization'}), 403
    rows = NonprofitStaff.query.filter_by(business_id=business_id).order_by(NonprofitStaff.created_at).all()
    return jsonify({'staff': [_serialize_staff(s) for s in rows]})


@nonprofit_staff_api.route('/nonprofit/businesses/<int:business_id>/staff', methods=['POST'])
@superadmin_required
def create_staff(staff, business_id):
    if staff.business_id != business_id:
        return jsonify({'message': 'Not authorized for this organization'}), 403

    body = request.get_json() or {}
    email = (body.get('email') or '').strip().lower()
    name = (body.get('name') or '').strip()
    password = body.get('password') or ''
    role = body.get('role') or 'staff'
    if not email or '@' not in email or len(email) > EMAIL_MAX:
        return jsonify({'message': 'A valid email is required'}), 400
    if not name or len(name) > NAME_MAX:
        return jsonify({'message': f'name is required (max {NAME_MAX} characters)'}), 400
    if len(password) < PASSWORD_MIN:
        return jsonify({'message': f'Password must be at least {PASSWORD_MIN} characters'}), 400
    if role not in NONPROFIT_STAFF_ROLES:
        return jsonify({'message': f'role must be one of {NONPROFIT_STAFF_ROLES}'}), 400
    if NonprofitStaff.query.filter_by(business_id=business_id, email=email).first():
        return jsonify({'message': 'A staff account with that email already exists'}), 409

    new_staff = NonprofitStaff(
        business_id=business_id, email=email,
        password_hash=generate_password_hash(password, method='pbkdf2:sha256'),
        name=name, role=role,
    )
    db.session.add(new_staff)
    db.session.commit()
    return jsonify(_serialize_staff(new_staff)), 201


@nonprofit_staff_api.route('/nonprofit/staff/<int:staff_id>', methods=['PATCH'])
@superadmin_required
def update_staff(staff, staff_id):
    target = NonprofitStaff.query.get(staff_id)
    if not target or target.business_id != staff.business_id:
        return jsonify({'message': 'Staff account not found'}), 404

    body = request.get_json() or {}
    if 'name' in body:
        name = (body['name'] or '').strip()
        if not name:
            return jsonify({'message': 'name cannot be empty'}), 400
        target.name = name
    if 'role' in body:
        if body['role'] not in NONPROFIT_STAFF_ROLES:
            return jsonify({'message': f'role must be one of {NONPROFIT_STAFF_ROLES}'}), 400
        if target.id == staff.id and body['role'] != 'superadmin':
            return jsonify({'message': "You can't demote your own account"}), 400
        target.role = body['role']
    if 'password' in body and body['password']:
        if len(body['password']) < PASSWORD_MIN:
            return jsonify({'message': f'Password must be at least {PASSWORD_MIN} characters'}), 400
        target.password_hash = generate_password_hash(body['password'], method='pbkdf2:sha256')

    db.session.commit()
    return jsonify(_serialize_staff(target))


@nonprofit_staff_api.route('/nonprofit/staff/<int:staff_id>', methods=['DELETE'])
@superadmin_required
def delete_staff(staff, staff_id):
    if staff_id == staff.id:
        return jsonify({'message': "You can't remove your own account"}), 400
    target = NonprofitStaff.query.get(staff_id)
    if not target or target.business_id != staff.business_id:
        return jsonify({'message': 'Staff account not found'}), 404
    db.session.delete(target)
    db.session.commit()
    return jsonify({'message': 'Removed'})
