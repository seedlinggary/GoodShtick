from flask import Blueprint, jsonify, request
from sqlalchemy.orm import selectinload

from config import db
from security import token_required, token_optional
from backend.business.modals.business import Business
from backend.business.modals.business_rating import BusinessRating
from backend.business.modals.business_redemption import BusinessRedemption
from backend.business.schemas.business import RatingSchema

business_rating_api = Blueprint('business_rating_api', __name__, url_prefix='/business')

PAGE_SIZE = 20
REVIEW_MAX = 1000


def _recompute_rating(business_id):
    rows = db.session.query(BusinessRating.stars).filter_by(business_id=business_id).all()
    stars = [r[0] for r in rows]
    business = db.session.get(Business, business_id)
    business.rating_count = len(stars)
    business.rating_avg = round(sum(stars) / len(stars), 2) if stars else 0.0


@business_rating_api.route('/businesses/<int:business_id>/ratings', methods=['GET'])
@token_optional
def list_ratings(_current_user, business_id):
    try:
        page = max(1, int(request.args.get('page', 1)))
    except (TypeError, ValueError):
        page = 1
    rows = (BusinessRating.query
            .options(selectinload(BusinessRating.user))
            .filter_by(business_id=business_id)
            .order_by(BusinessRating.created_at.desc())
            .limit(PAGE_SIZE + 1).offset((page - 1) * PAGE_SIZE).all())
    has_more = len(rows) > PAGE_SIZE
    return jsonify({'ratings': RatingSchema(many=True).dump(rows[:PAGE_SIZE]), 'page': page, 'has_more': has_more})


@business_rating_api.route('/businesses/<int:business_id>/rate', methods=['POST'])
@token_required
def rate_business(current_user, business_id):
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

    review_text = (body.get('review_text') or '').strip()
    if len(review_text) > REVIEW_MAX:
        return jsonify({'message': f'Review must be {REVIEW_MAX} characters or fewer'}), 400

    # A review is "verified" when this reviewer has an actual redeemed deal
    # at this business -- real activity, not a claim they can make
    # themselves (see BusinessRating.verified).
    verified = BusinessRedemption.query.filter_by(
        business_id=business_id, user_id=current_user.public_id, status='redeemed').first() is not None

    rating = BusinessRating.query.filter_by(business_id=business_id, user_id=current_user.public_id).first()
    if rating:
        rating.stars = stars
        rating.review_text = review_text or None
        rating.verified = rating.verified or verified
    else:
        rating = BusinessRating(business_id=business_id, user_id=current_user.public_id,
                                 stars=stars, review_text=review_text or None, verified=verified)
        db.session.add(rating)

    db.session.flush()
    _recompute_rating(business_id)
    db.session.commit()
    return jsonify(RatingSchema().dump(rating)), 201


@business_rating_api.route('/businesses/<int:business_id>/rate', methods=['DELETE'])
@token_required
def delete_rating(current_user, business_id):
    rating = BusinessRating.query.filter_by(business_id=business_id, user_id=current_user.public_id).first()
    if not rating:
        return jsonify({'message': 'You have not rated this business'}), 404
    db.session.delete(rating)
    db.session.flush()
    _recompute_rating(business_id)
    db.session.commit()
    return jsonify({'message': 'Deleted'})
