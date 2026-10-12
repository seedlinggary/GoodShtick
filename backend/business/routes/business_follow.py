"""Follow a business + broadcast to followers. A follow is what makes the
customer-side "get notified about new deals" feature possible, and the same
table is the recipient list a business's broadcast sends to."""
from flask import Blueprint, jsonify, request

from config import db
from backend.notifications.helpers import notify
from security import token_required
from backend.business.modals.business import Business
from backend.business.modals.business_follow import BusinessFollow
from backend.business.schemas.business_follow import FollowSchema

follow_api = Blueprint('follow_api', __name__, url_prefix='/business')

BROADCAST_MAX = 500


def _can_manage(business, user):
    if not user:
        return False
    if user.is_boss:
        return True
    if business.owner_user_id:
        return business.owner_user_id == user.public_id
    return business.created_by == user.public_id


@follow_api.route('/businesses/<int:business_id>/follow', methods=['POST'])
@token_required
def follow_business(current_user, business_id):
    business = db.session.get(Business, business_id)
    if not business:
        return jsonify({'message': 'Business not found'}), 404
    existing = BusinessFollow.query.filter_by(business_id=business_id, user_id=current_user.public_id).first()
    if existing:
        return jsonify(FollowSchema().dump(existing))
    follow = BusinessFollow(business_id=business_id, user_id=current_user.public_id)
    db.session.add(follow)
    db.session.commit()
    return jsonify(FollowSchema().dump(follow)), 201


@follow_api.route('/businesses/<int:business_id>/follow', methods=['DELETE'])
@token_required
def unfollow_business(current_user, business_id):
    follow = BusinessFollow.query.filter_by(business_id=business_id, user_id=current_user.public_id).first()
    if follow:
        db.session.delete(follow)
        db.session.commit()
    return jsonify({'message': 'Unfollowed'})


@follow_api.route('/businesses/<int:business_id>/follow-status', methods=['GET'])
@token_required
def follow_status(current_user, business_id):
    following = BusinessFollow.query.filter_by(business_id=business_id, user_id=current_user.public_id).first() is not None
    count = BusinessFollow.query.filter_by(business_id=business_id).count()
    return jsonify({'following': following, 'follower_count': count})


@follow_api.route('/my/follows', methods=['GET'])
@token_required
def my_follows(current_user):
    rows = (BusinessFollow.query.filter_by(user_id=current_user.public_id)
            .order_by(BusinessFollow.created_at.desc()).all())
    return jsonify(FollowSchema(many=True).dump(rows))


@follow_api.route('/businesses/<int:business_id>/broadcast', methods=['POST'])
@token_required
def broadcast(current_user, business_id):
    """One message, sent as an in-app notification to every follower --
    the business-side lever for the same feature."""
    business = db.session.get(Business, business_id)
    if not business or not _can_manage(business, current_user):
        return jsonify({'message': 'Not authorized'}), 403

    message = ((request.get_json() or {}).get('message') or '').strip()
    if not message:
        return jsonify({'message': 'message is required'}), 400
    if len(message) > BROADCAST_MAX:
        return jsonify({'message': f'Message must be {BROADCAST_MAX} characters or fewer'}), 400

    followers = BusinessFollow.query.filter_by(business_id=business_id).all()
    for follow in followers:
        notify(follow.user_id, f'{business.name}: {message}', type='business_broadcast',
               actor_id=current_user.public_id, link=f'/business/{business.slug}')
    db.session.commit()
    return jsonify({'message': 'Sent', 'recipients': len(followers)})
