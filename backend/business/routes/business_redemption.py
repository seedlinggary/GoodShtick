"""QR-code deal redemption. One BusinessRedemption row per (deal, customer):
issuing it is what "Get this deal" does (and feeds the customer's deal
wallet), and an owner scanning/typing its code back in is what marks it
redeemed -- which is also the fact a review's `verified` badge is built on
(see business_rating.py)."""
from datetime import datetime

from flask import Blueprint, jsonify, request

from config import db
from security import super_admin_required
from backend.notifications.helpers import notify
from backend.business.modals.business import Business
from backend.business.modals.business_post import BusinessPost
from backend.business.modals.business_redemption import BusinessRedemption
from backend.business.modals.business_referral_code import BusinessReferral, BusinessReferralUse
from backend.business.schemas.business_redemption import RedemptionSchema

redemption_api = Blueprint('redemption_api', __name__, url_prefix='/business')


def _can_manage(business, user):
    if not user:
        return False
    if user.is_boss:
        return True
    if business.owner_user_id:
        return business.owner_user_id == user.public_id
    return business.created_by == user.public_id


@redemption_api.route('/deals/<int:post_id>/get', methods=['POST'])
@super_admin_required
def get_deal(current_user, post_id):
    """Issues (or returns the existing) redemption code for this
    customer+deal -- idempotent, so tapping "Get this deal" twice never
    creates two wallet entries."""
    post = db.session.get(BusinessPost, post_id)
    if not post or not post.approved_to_publish:
        return jsonify({'message': 'Deal not found'}), 404
    if post.expires_at and post.expires_at < datetime.utcnow():
        return jsonify({'message': 'This deal has expired'}), 400

    existing = BusinessRedemption.query.filter_by(business_post_id=post_id, user_id=current_user.public_id).first()
    if existing:
        return jsonify(RedemptionSchema().dump(existing))

    redemption = BusinessRedemption(business_post_id=post_id, business_id=post.business_id,
                                     user_id=current_user.public_id)
    db.session.add(redemption)

    referral_code = ((request.get_json(silent=True) or {}).get('referral_code') or '').strip().upper()
    if referral_code:
        referral = BusinessReferral.query.filter_by(business_id=post.business_id, code=referral_code).first()
        already_used = referral and BusinessReferralUse.query.filter_by(
            referral_id=referral.id, referred_user_id=current_user.public_id).first()
        if referral and referral.referrer_user_id != current_user.public_id and not already_used:
            db.session.add(BusinessReferralUse(referral_id=referral.id, referred_user_id=current_user.public_id))
            notify(referral.referrer_user_id, f'A friend you referred to {post.business.name} just used your code!',
                   type='business_referral', link=f'/business/{post.business.slug}')

    db.session.commit()
    return jsonify(RedemptionSchema().dump(redemption)), 201


@redemption_api.route('/my/deals', methods=['GET'])
@super_admin_required
def my_deal_wallet(current_user):
    """The customer's deal wallet -- every issued/redeemed deal, newest
    first, so an expiring one is easy to spot."""
    rows = (BusinessRedemption.query
            .filter_by(user_id=current_user.public_id)
            .order_by(BusinessRedemption.issued_at.desc()).all())
    return jsonify(RedemptionSchema(many=True).dump(rows))


@redemption_api.route('/businesses/<int:business_id>/redeem', methods=['POST'])
@super_admin_required
def redeem_code(current_user, business_id):
    """Owner-side: type/scan a customer's code to mark their deal redeemed."""
    business = db.session.get(Business, business_id)
    if not business or not _can_manage(business, current_user):
        return jsonify({'message': 'Not authorized'}), 403

    code = ((request.get_json() or {}).get('code') or '').strip().upper()
    if not code:
        return jsonify({'message': 'code is required'}), 400

    redemption = BusinessRedemption.query.filter_by(code=code, business_id=business_id).first()
    if not redemption:
        return jsonify({'message': 'No matching deal code for this business'}), 404
    if redemption.status == 'redeemed':
        return jsonify({'message': 'This code was already redeemed', 'redeemed_at': redemption.redeemed_at.isoformat()}), 409

    redemption.status = 'redeemed'
    redemption.redeemed_at = datetime.utcnow()
    db.session.commit()
    return jsonify(RedemptionSchema().dump(redemption))


@redemption_api.route('/businesses/<int:business_id>/redemptions', methods=['GET'])
@super_admin_required
def list_redemptions(current_user, business_id):
    """Owner-side redemption log, feeding the click-analytics dashboard's
    'deals redeemed' figure."""
    business = db.session.get(Business, business_id)
    if not business or not _can_manage(business, current_user):
        return jsonify({'message': 'Not authorized'}), 403
    rows = (BusinessRedemption.query.filter_by(business_id=business_id)
            .order_by(BusinessRedemption.issued_at.desc()).limit(200).all())
    return jsonify(RedemptionSchema(many=True).dump(rows))
