"""Private vendor-referral board: 'who do you use for X' among users who own
at least one claimed business. Gate is checked here, not stored on the
model -- claimed-owner status can change over time."""
from flask import Blueprint, jsonify, request

from config import db
from backend.business.modals.business import Business
from security import token_required
from backend.business.modals.business_referral import BusinessReferralPost, BusinessReferralReply
from backend.business.schemas.business_referral import ReferralPostSchema, ReferralReplySchema

referral_api = Blueprint('referral_api', __name__, url_prefix='/business')

TITLE_MAX, BODY_MAX, REPLY_MAX = 200, 3000, 2000


def _owned_claimed_business(user):
    """The first business this user actually owns (claim approved) -- what
    lets them into the board and what a post they write is attributed to."""
    return Business.query.filter_by(owner_user_id=user.public_id).first()


@referral_api.route('/referrals', methods=['GET'])
@token_required
def list_referrals(current_user):
    if not _owned_claimed_business(current_user):
        return jsonify({'message': 'Only owners of a claimed business can view the vendor board'}), 403
    posts = (BusinessReferralPost.query.order_by(BusinessReferralPost.created_at.desc()).limit(100).all())
    return jsonify(ReferralPostSchema(many=True).dump(posts))


@referral_api.route('/referrals', methods=['POST'])
@token_required
def create_referral(current_user):
    business = _owned_claimed_business(current_user)
    if not business:
        return jsonify({'message': 'Only owners of a claimed business can post to the vendor board'}), 403

    body = request.get_json() or {}
    title = (body.get('title') or '').strip()
    text = (body.get('body') or '').strip()
    if not title or len(title) > TITLE_MAX:
        return jsonify({'message': f'Title is required (max {TITLE_MAX} characters)'}), 400
    if not text or len(text) > BODY_MAX:
        return jsonify({'message': f'Body is required (max {BODY_MAX} characters)'}), 400

    post = BusinessReferralPost(business_id=business.id, user_id=current_user.public_id, title=title, body=text)
    db.session.add(post)
    db.session.commit()
    return jsonify(ReferralPostSchema().dump(post)), 201


@referral_api.route('/referrals/<int:post_id>/replies', methods=['POST'])
@token_required
def reply_referral(current_user, post_id):
    business = _owned_claimed_business(current_user)
    if not business:
        return jsonify({'message': 'Only owners of a claimed business can reply'}), 403
    post = db.session.get(BusinessReferralPost, post_id)
    if not post:
        return jsonify({'message': 'Post not found'}), 404

    text = ((request.get_json() or {}).get('body') or '').strip()
    if not text or len(text) > REPLY_MAX:
        return jsonify({'message': f'Reply body is required (max {REPLY_MAX} characters)'}), 400

    reply = BusinessReferralReply(post_id=post_id, business_id=business.id, user_id=current_user.public_id, body=text)
    db.session.add(reply)
    db.session.commit()
    return jsonify(ReferralReplySchema().dump(reply)), 201


@referral_api.route('/referrals/<int:post_id>', methods=['DELETE'])
@token_required
def delete_referral(current_user, post_id):
    post = db.session.get(BusinessReferralPost, post_id)
    if not post:
        return jsonify({'message': 'Post not found'}), 404
    if post.user_id != current_user.public_id and not current_user.is_boss:
        return jsonify({'message': 'Not authorized'}), 403
    db.session.delete(post)
    db.session.commit()
    return jsonify({'message': 'Deleted'})
