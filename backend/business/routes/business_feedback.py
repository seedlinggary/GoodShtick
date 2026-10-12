"""The review funnel: a customer rates their experience privately here
first. 4-5 stars gets routed to the business's real Google review link
(higher-value than an internal review for local search ranking); 1-3 stars
stays private and notifies the owner directly instead of becoming a public
review. The existing public BusinessRating system is untouched -- this is a
separate, earlier step, not a replacement."""
from flask import Blueprint, jsonify, request

from config import db
from security import token_required
from backend.notifications.helpers import notify
from backend.business.modals.business import Business
from backend.business.modals.business_feedback import BusinessFeedback
from backend.business.schemas.business_feedback import FeedbackSchema

feedback_api = Blueprint('feedback_api', __name__, url_prefix='/business')

COMMENT_MAX = 1000
GOOGLE_REVIEW_THRESHOLD = 4


def _can_manage(business, user):
    if not user:
        return False
    if user.is_boss:
        return True
    if business.owner_user_id:
        return business.owner_user_id == user.public_id
    return business.created_by == user.public_id


@feedback_api.route('/businesses/<int:business_id>/feedback', methods=['POST'])
@token_required
def submit_feedback(current_user, business_id):
    business = db.session.get(Business, business_id)
    if not business:
        return jsonify({'message': 'Business not found'}), 404

    body = request.get_json() or {}
    try:
        stars = int(body.get('stars'))
    except (TypeError, ValueError):
        return jsonify({'message': 'stars is required'}), 400
    if stars < 1 or stars > 5:
        return jsonify({'message': 'stars must be between 1 and 5'}), 400
    comment = (body.get('comment') or '').strip()
    if len(comment) > COMMENT_MAX:
        return jsonify({'message': f'Comment must be {COMMENT_MAX} characters or fewer'}), 400

    row = BusinessFeedback(business_id=business_id, user_id=current_user.public_id,
                            stars=stars, comment=comment or None)
    db.session.add(row)
    db.session.flush()

    google_review_url = (business.attributes or {}).get('google_review_url')
    route_to_google = stars >= GOOGLE_REVIEW_THRESHOLD and bool(google_review_url)

    if stars < GOOGLE_REVIEW_THRESHOLD and business.owner_user_id:
        notify(business.owner_user_id, f'Private feedback on {business.name}: {stars}★',
               type='business_feedback', link=f'/business/{business.slug}/tools')

    db.session.commit()
    return jsonify({
        **FeedbackSchema().dump(row),
        'route_to_google': route_to_google,
        'google_review_url': google_review_url if route_to_google else None,
    }), 201


@feedback_api.route('/businesses/<int:business_id>/feedback', methods=['GET'])
@token_required
def list_feedback(current_user, business_id):
    business = db.session.get(Business, business_id)
    if not business or not _can_manage(business, current_user):
        return jsonify({'message': 'Not authorized'}), 403
    rows = (BusinessFeedback.query.filter_by(business_id=business_id)
            .order_by(BusinessFeedback.created_at.desc()).limit(200).all())
    return jsonify(FeedbackSchema(many=True).dump(rows))
