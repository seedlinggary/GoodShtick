"""Digital punch-card. A business opts in via attributes.loyalty_enabled /
loyalty_threshold / loyalty_reward on its own record (set through the
existing generic PATCH /business/businesses/<id>, same as auto-holiday
closure). A customer's card is created lazily the first time they open it."""
from flask import Blueprint, jsonify, request

from config import db
from security import super_admin_required
from backend.business.modals.business import Business
from backend.business.modals.loyalty_card import LoyaltyCard
from backend.business.schemas.loyalty_card import LoyaltyCardSchema

loyalty_api = Blueprint('loyalty_api', __name__, url_prefix='/business')

DEFAULT_THRESHOLD = 10


def _can_manage(business, user):
    if not user:
        return False
    if user.is_boss:
        return True
    if business.owner_user_id:
        return business.owner_user_id == user.public_id
    return business.created_by == user.public_id


def _loyalty_settings(business):
    attrs = business.attributes or {}
    return {
        'enabled': bool(attrs.get('loyalty_enabled')),
        'threshold': int(attrs.get('loyalty_threshold') or DEFAULT_THRESHOLD),
        'reward': attrs.get('loyalty_reward') or 'A free reward',
    }


@loyalty_api.route('/businesses/<int:business_id>/loyalty/my-card', methods=['GET'])
@super_admin_required
def my_card(current_user, business_id):
    business = db.session.get(Business, business_id)
    if not business:
        return jsonify({'message': 'Business not found'}), 404
    settings = _loyalty_settings(business)
    if not settings['enabled']:
        return jsonify({'message': 'This business does not have a loyalty program yet'}), 404

    card = LoyaltyCard.query.filter_by(business_id=business_id, user_id=current_user.public_id).first()
    if not card:
        card = LoyaltyCard(business_id=business_id, user_id=current_user.public_id)
        db.session.add(card)
        db.session.commit()
    return jsonify({**LoyaltyCardSchema().dump(card), **settings})


@loyalty_api.route('/businesses/<int:business_id>/loyalty/stamp', methods=['POST'])
@super_admin_required
def add_stamp(current_user, business_id):
    business = db.session.get(Business, business_id)
    if not business or not _can_manage(business, current_user):
        return jsonify({'message': 'Not authorized'}), 403
    settings = _loyalty_settings(business)
    if not settings['enabled']:
        return jsonify({'message': 'Loyalty program is not enabled for this business'}), 400

    code = ((request.get_json() or {}).get('code') or '').strip().upper()
    card = LoyaltyCard.query.filter_by(business_id=business_id, customer_code=code).first()
    if not card:
        return jsonify({'message': 'No matching loyalty card for this business'}), 404

    card.stamps += 1
    reward_earned = card.stamps >= settings['threshold']
    if reward_earned:
        card.stamps -= settings['threshold']
        card.rewards_redeemed += 1
    db.session.commit()

    return jsonify({
        **LoyaltyCardSchema().dump(card), **settings,
        'reward_earned': reward_earned,
    })


@loyalty_api.route('/businesses/<int:business_id>/loyalty/settings', methods=['GET'])
@super_admin_required
def loyalty_settings(current_user, business_id):
    business = db.session.get(Business, business_id)
    if not business or not _can_manage(business, current_user):
        return jsonify({'message': 'Not authorized'}), 403
    return jsonify(_loyalty_settings(business))
