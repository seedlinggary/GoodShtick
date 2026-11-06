"""Promo sync -- the last of the site builder's Phase 0 module-flag
bolt-ons (see business_site.py's MODULE_REGISTRY docstring: new bolt-ons
are meant to be mostly wiring, reusing what already exists). Surfaces a
business's own storefront activity onto the main Gut Community feed via
the existing BusinessPost model (already has 'new_product'/'sale'
post types -- nothing new to add there), for businesses that would
otherwise have no presence on that feed just for running a shop through
their own site.

Gated by two separate, per-site, DEFAULT-ON toggles (BusinessSite.
share_products_with_community / share_deals_with_community -- set by the
owner in their site settings, opted OUT of rather than opted in), not by
an enabled_modules flag the way every other bolt-on in this file is --
this one was an explicit, specific product request: products and active
discount codes should reach the wider community by default.

Reuses social.py's exact dual-trigger scheduling pattern (a real cron
endpoint + an opportunistic random-chance sweep from a high-traffic
route) -- see booking.py's near-identical recurring-appointment
generation for the same reasoning (no verified cron wiring on this
serverless deployment, so nothing here can assume an in-process
scheduler).

Deliberately leaves BusinessPost.image unset for an auto-generated post --
that column holds a bare Supabase filename (resolved via get_public_url at
serialization time), while Product.images stores already-resolved full
URLs (see commerce.py), so there's a format mismatch with nothing clean to
bridge without re-uploading an already-uploaded image. The post's text
still names the products/codes; it just has no photo.
"""
import random
from datetime import datetime, timedelta

from flask import Blueprint, jsonify

from config import db
from security import cron_secret_required
from backend.business.modals.business import Business
from backend.business.modals.business_site import BusinessSite
from backend.business.modals.business_post import BusinessPost
from backend.business.modals.commerce import Product, PromoCode

promo_sync_api = Blueprint('promo_sync_api', __name__, url_prefix='/business')

# Same reasoning/constant choice as social.py's PUBLISH_CHECK_CHANCE and
# booking.py's GENERATE_CHECK_CHANCE.
PROMO_SYNC_CHECK_CHANCE = 0.05
MIN_DAYS_SINCE_LAST_POST = 7
SITES_SCAN_LIMIT = 200
POSTS_BATCH_LIMIT = 10
FEATURED_PRODUCTS_PER_POST = 3
FEATURED_CODES_PER_POST = 3


def _generate_due_promo_posts():
    cutoff = datetime.utcnow() - timedelta(days=MIN_DAYS_SINCE_LAST_POST)
    sites = BusinessSite.query.filter_by(status='published').limit(SITES_SCAN_LIMIT).all()
    created = 0

    for site in sites:
        if created >= POSTS_BATCH_LIMIT:
            break
        if not site.has_module('products'):
            continue

        business = db.session.get(Business, site.business_id)
        if not business or not business.owner_user_id:
            continue

        last_post = (BusinessPost.query.filter_by(business_id=business.id)
                     .order_by(BusinessPost.pub_date.desc()).first())
        already_posted_recently = bool(last_post and last_post.pub_date and last_post.pub_date > cutoff)

        if site.share_products_with_community and not already_posted_recently:
            products = (Product.query.filter_by(business_id=business.id, active=True)
                        .order_by(Product.position, Product.id).limit(FEATURED_PRODUCTS_PER_POST).all())
            if products:
                lines = [f'{p.name} — ${p.price_cents / 100:.2f}' for p in products]
                db.session.add(BusinessPost(
                    business_id=business.id, user_id=business.owner_user_id, post_type='new_product',
                    title=f'Now shopping: {business.name}',
                    body='Available on our site:\n' + '\n'.join(lines),
                ))
                created += 1
                if created >= POSTS_BATCH_LIMIT:
                    break

        if site.share_deals_with_community and not already_posted_recently:
            now = datetime.utcnow()
            codes = (PromoCode.query.filter(
                        PromoCode.business_id == business.id, PromoCode.active.is_(True),
                        db.or_(PromoCode.expires_at.is_(None), PromoCode.expires_at > now))
                     .order_by(PromoCode.created_at.desc()).limit(FEATURED_CODES_PER_POST).all())
            codes = [c for c in codes if c.max_redemptions is None or c.redemption_count < c.max_redemptions]
            if codes:
                lines = [
                    f'{c.code}: {c.amount}% off' if c.discount_type == 'percent' else f'{c.code}: ${c.amount / 100:.2f} off'
                    for c in codes
                ]
                db.session.add(BusinessPost(
                    business_id=business.id, user_id=business.owner_user_id, post_type='sale',
                    title=f'Deals at {business.name}',
                    body='Use these codes at checkout on our site:\n' + '\n'.join(lines),
                ))
                created += 1

    if created:
        db.session.commit()
    return created


@promo_sync_api.route('/cron/promo-sync', methods=['POST'])
@cron_secret_required
def promo_sync_cron():
    """For anyone who wants tighter timing than the opportunistic sweep
    below -- point a real external scheduler at this with the
    X-Cron-Secret header set to CRON_SECRET, same as social.py's
    /social/cron/publish-due and booking.py's
    /business/cron/generate-recurring-appointments."""
    created = _generate_due_promo_posts()
    return jsonify({'created': created})


def maybe_generate_promo_posts():
    """Called opportunistically from a high-traffic public route (see
    business.py's list_businesses, alongside social.py's own
    maybe_publish_due_posts and booking.py's
    maybe_generate_recurring_appointments) -- never raises, never blocks
    the request that triggered it."""
    if random.random() >= PROMO_SYNC_CHECK_CHANCE:
        return
    try:
        _generate_due_promo_posts()
    except Exception:
        db.session.rollback()
