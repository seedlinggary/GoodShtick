"""Owner-account utilities that don't need their own model: boosted
placement (earned by profile completeness, no payment processor wired up
yet) and a bulk editor across every business the current user owns."""
from datetime import datetime, timedelta

from flask import Blueprint, jsonify, request

from config import db
from security import token_required
from backend.business.modals.business import Business, FOOD_CATEGORIES
from backend.business.schemas.business import make_business_schema

owner_tools_api = Blueprint('owner_tools_api', __name__, url_prefix='/business')

BOOST_DAYS = 7


def _can_manage(business, user):
    if not user:
        return False
    if user.is_boss:
        return True
    if business.owner_user_id:
        return business.owner_user_id == user.public_id
    return business.created_by == user.public_id


def _profile_completeness(business):
    """What has to be filled in to earn a boost -- deliberately the same
    fields that make a listing actually useful to a customer, so "boosted"
    correlates with "worth showing first," not just "asked for it."""
    primary = next((l for l in business.locations if l.is_primary), business.locations[0] if business.locations else None)
    checks = {
        'name': bool(business.name),
        'about': bool(business.about),
        'logo': bool(business.logo),
        'has_location': primary is not None,
        'hours_set': bool(primary and primary.hours),
        'kashrut_set': business.category not in FOOD_CATEGORIES or bool(primary and primary.kashrut),
    }
    missing = [k for k, ok in checks.items() if not ok]
    return checks, missing


@owner_tools_api.route('/businesses/<int:business_id>/boost/eligibility', methods=['GET'])
@token_required
def boost_eligibility(current_user, business_id):
    business = db.session.get(Business, business_id)
    if not business or not _can_manage(business, current_user):
        return jsonify({'message': 'Not authorized'}), 403
    checks, missing = _profile_completeness(business)
    return jsonify({
        'eligible': not missing,
        'checks': checks,
        'missing': missing,
        'boost_until': business.boost_until.isoformat() if business.boost_until else None,
        'boost_active': bool(business.boost_until and business.boost_until > datetime.utcnow()),
    })


@owner_tools_api.route('/businesses/<int:business_id>/boost/activate', methods=['POST'])
@token_required
def activate_boost(current_user, business_id):
    business = db.session.get(Business, business_id)
    if not business or not _can_manage(business, current_user):
        return jsonify({'message': 'Not authorized'}), 403
    _, missing = _profile_completeness(business)
    if missing:
        return jsonify({'message': 'Complete your profile first', 'missing': missing}), 400
    if business.boost_until and business.boost_until > datetime.utcnow():
        return jsonify({'message': 'Boost is already active'}), 409

    business.boost_until = datetime.utcnow() + timedelta(days=BOOST_DAYS)
    db.session.commit()
    return jsonify({'boost_until': business.boost_until.isoformat()})


@owner_tools_api.route('/my/businesses/bulk', methods=['PATCH'])
@token_required
def bulk_update(current_user):
    """Apply hours/kashrut/attributes across every business the current user
    owns in one call -- for chains/franchises. Only fields present in the
    body are touched; business_ids not owned by the caller are skipped
    (never silently applied to someone else's listing)."""
    body = request.get_json() or {}
    business_ids = body.get('business_ids') or []
    if not isinstance(business_ids, list) or not business_ids:
        return jsonify({'message': 'business_ids (a non-empty list) is required'}), 400

    hours = body.get('hours')
    if hours is not None and not isinstance(hours, dict):
        return jsonify({'message': 'hours must be an object keyed by weekday'}), 400
    kashrut = body.get('kashrut')

    updated, skipped = [], []
    for business_id in business_ids:
        business = db.session.get(Business, int(business_id))
        if not business or not _can_manage(business, current_user):
            skipped.append(business_id)
            continue
        for loc in business.locations:
            if hours is not None:
                loc.hours = hours
            if kashrut is not None:
                loc.kashrut = kashrut or None
        updated.append(business.id)

    db.session.commit()
    schema = make_business_schema(current_user, many=True, card=True)
    businesses = [db.session.get(Business, bid) for bid in updated]
    return jsonify({'updated': schema.dump(businesses), 'skipped': skipped})
