"""Decision-support for a business owner: how they stack up against other
businesses in their own category, plus a concrete action list built from
gaps that are actually fixable (not just raw numbers)."""
from datetime import datetime, timedelta

from flask import Blueprint, jsonify
from sqlalchemy import func

from config import db
from security import token_required
from backend.business.modals.business import Business, FOOD_CATEGORIES
from backend.business.modals.business_lead import BusinessLead
from backend.business.modals.business_question import BusinessQuestion
from backend.business.modals.business_feedback import BusinessFeedback
from backend.business.modals.business_redemption import BusinessRedemption
from backend.business.modals.business_follow import BusinessFollow
from backend.business.routes.business_owner_tools import _profile_completeness

insights_api = Blueprint('insights_api', __name__, url_prefix='/business')


def _category_label(category):
    return category.replace('_', ' ')


def _can_manage(business, user):
    if not user:
        return False
    if user.is_boss:
        return True
    if business.owner_user_id:
        return business.owner_user_id == user.public_id
    return business.created_by == user.public_id


@insights_api.route('/businesses/<int:business_id>/insights', methods=['GET'])
@token_required
def business_insights(current_user, business_id):
    business = db.session.get(Business, business_id)
    if not business or not _can_manage(business, current_user):
        return jsonify({'message': 'Not authorized'}), 403

    peers = Business.query.filter(Business.category == business.category, Business.id != business.id)
    peer_count = peers.count()
    avg_rating = peers.with_entities(func.avg(Business.rating_avg)).scalar() or 0.0
    logo_pct = 0.0
    if peer_count:
        with_logo = peers.filter(Business.logo.isnot(None)).count()
        logo_pct = round(100 * with_logo / peer_count, 1)

    checks, missing = _profile_completeness(business)

    unanswered_questions = BusinessQuestion.query.filter_by(business_id=business_id, answer=None).count()
    new_leads = BusinessLead.query.filter_by(business_id=business_id, status='new').count()

    cutoff = datetime.utcnow() - timedelta(days=90)
    recent_feedback = (BusinessFeedback.query
                        .filter(BusinessFeedback.business_id == business_id, BusinessFeedback.created_at >= cutoff)
                        .all())
    avg_feedback = round(sum(f.stars for f in recent_feedback) / len(recent_feedback), 2) if recent_feedback else None
    low_feedback_count = len([f for f in recent_feedback if f.stars <= 3])

    issued = BusinessRedemption.query.filter_by(business_id=business_id).count()
    redeemed = BusinessRedemption.query.filter_by(business_id=business_id, status='redeemed').count()
    redemption_rate = round(100 * redeemed / issued, 1) if issued else None

    follower_count = BusinessFollow.query.filter_by(business_id=business_id).count()

    recommendations = []
    if 'logo' in missing:
        recommendations.append('Add a logo -- listings with one get noticed first in the directory grid.')
    if 'hours_set' in missing:
        recommendations.append('Set your hours so the "open now" filter and search can actually surface you.')
    if business.category in FOOD_CATEGORIES and 'kashrut_set' in missing:
        recommendations.append('Add your kashrut certification -- it\'s one of the most-filtered fields in this directory.')
    if unanswered_questions:
        recommendations.append(f'{unanswered_questions} customer question{"s" if unanswered_questions != 1 else ""} still unanswered -- answered ones show as a public FAQ.')
    if new_leads:
        recommendations.append(f'{new_leads} new quote request{"s" if new_leads != 1 else ""} waiting in your Leads tab.')
    if low_feedback_count:
        recommendations.append(f'{low_feedback_count} recent private feedback rating{"s" if low_feedback_count != 1 else ""} of 3 stars or below -- worth a look before it becomes a public review.')
    if peer_count and business.rating_avg and business.rating_avg < avg_rating - 0.3:
        recommendations.append(f'Your rating ({business.rating_avg:.1f}) is below the {_category_label(business.category)} average ({avg_rating:.1f}) -- the review funnel can help surface more happy customers.')
    if issued and redemption_rate is not None and redemption_rate < 40:
        recommendations.append(f'Only {redemption_rate}% of issued deal codes get redeemed -- consider a shorter expiry or a clearer in-store call to action.')
    if not follower_count:
        recommendations.append('No followers yet -- point customers to the Follow button so your next deal reaches them directly.')

    return jsonify({
        'category_benchmark': {
            'peer_count': peer_count,
            'avg_rating': round(avg_rating, 2),
            'logo_pct': logo_pct,
        },
        'your_stats': {
            'rating_avg': business.rating_avg,
            'rating_count': business.rating_count,
            'follower_count': follower_count,
            'profile_completeness_pct': round(100 * sum(checks.values()) / len(checks), 0) if checks else 0,
            'unanswered_questions': unanswered_questions,
            'new_leads': new_leads,
            'avg_private_feedback_90d': avg_feedback,
            'deal_redemption_rate_pct': redemption_rate,
        },
        'recommendations': recommendations,
    })
