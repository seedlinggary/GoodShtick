"""Refer-a-friend, tracked through the existing deal-redemption flow: a
customer gets a personal code for a business, and supplying that code when
another person gets a deal (see business_redemption.py's get_deal, extended
to accept referral_code) records the connection. The actual reward
(Business.attributes.referral_reward, e.g. '10% off') is granted informally
by the owner from their referral list -- same trust-based pattern as
boosted placement, no discount engine involved."""
from flask import Blueprint, jsonify

from config import db
from security import super_admin_required
from backend.business.modals.business import Business
from backend.business.modals.business_referral_code import BusinessReferral, BusinessReferralUse
from backend.business.schemas.business_referral_code import ReferralCodeSchema

referral_code_api = Blueprint('referral_code_api', __name__, url_prefix='/business')


def _can_manage(business, user):
    if not user:
        return False
    if user.is_boss:
        return True
    if business.owner_user_id:
        return business.owner_user_id == user.public_id
    return business.created_by == user.public_id


@referral_code_api.route('/businesses/<int:business_id>/referral/my-code', methods=['GET'])
@super_admin_required
def my_referral_code(current_user, business_id):
    business = db.session.get(Business, business_id)
    if not business:
        return jsonify({'message': 'Business not found'}), 404

    referral = BusinessReferral.query.filter_by(business_id=business_id, referrer_user_id=current_user.public_id).first()
    if not referral:
        referral = BusinessReferral(business_id=business_id, referrer_user_id=current_user.public_id)
        db.session.add(referral)
        db.session.commit()

    reward = (business.attributes or {}).get('referral_reward')
    return jsonify({**ReferralCodeSchema().dump(referral), 'reward': reward})


@referral_code_api.route('/businesses/<int:business_id>/referral/list', methods=['GET'])
@super_admin_required
def list_referrals_for_owner(current_user, business_id):
    """Owner-side: who's referring customers, and how many each has brought
    in -- what the owner uses to decide who actually gets the reward."""
    business = db.session.get(Business, business_id)
    if not business or not _can_manage(business, current_user):
        return jsonify({'message': 'Not authorized'}), 403
    referrals = (BusinessReferral.query.filter_by(business_id=business_id)
                 .filter(BusinessReferral.uses.any())
                 .all())
    return jsonify(ReferralCodeSchema(many=True).dump(referrals))
