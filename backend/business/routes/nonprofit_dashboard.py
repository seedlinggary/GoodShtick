"""Nedarim Plus credentials settings, membership pricing, and the admin
dashboard's own stat cards + configuration-warning banners."""
import os

from flask import Blueprint, jsonify, request

from config import db
from backend.business.modals.business import Business
from backend.business.modals.business_site import BusinessSite
from backend.business.modals.nonprofit import (
    NonprofitPaymentConfig, NonprofitDonation, NonprofitMembership,
    NonprofitPaymentFollowUp, NonprofitExternalTransaction,
    get_membership_tiers, is_membership_open, is_donations_open,
)
from backend.business.nonprofit_auth import staff_required, superadmin_required


def _webhook_url(business_id):
    """What the owner pastes into THEIR OWN Nedarim Plus dashboard (עוד >
    Webhook). Nedarim Plus has no API to set this remotely -- it's a
    manual step on their side, so the settings screen has to hand the
    owner the exact URL to paste rather than just asking for credentials
    and silently assuming they'll figure out the rest. Returns None (not
    a broken relative path) if BACKEND_PUBLIC_URL isn't configured on
    this deployment -- the frontend shows a "not configured" warning
    instead of a URL that looks real but isn't."""
    base = os.environ.get('BACKEND_PUBLIC_URL')
    if not base:
        return None
    site = BusinessSite.query.filter_by(business_id=business_id).first()
    if not site:
        return None
    return f'{base.rstrip("/")}/nonprofit/webhooks/nedarimplus/{site.subdomain}'


def _family_portal_url(business_id):
    """The public-facing URL to hand out to families -- unlike
    _webhook_url above (this BACKEND's own address, for Nedarim Plus to
    call), this is the owner's PUBLIC SITE's own address (same
    BUSINESS_SITE_BASE_DOMAIN construction nonprofit_public.py's
    _public_site_origin uses), since it's a page a person visits in a
    browser, not a server-to-server callback. None if either the base
    domain isn't configured on this deployment or the site has no
    subdomain yet -- same "don't show a URL that looks real but isn't"
    convention as _webhook_url."""
    base = os.environ.get('BUSINESS_SITE_BASE_DOMAIN')
    if not base:
        return None
    site = BusinessSite.query.filter_by(business_id=business_id).first()
    if not site:
        return None
    return f'https://{site.subdomain}.{base}/family-portal'

nonprofit_dashboard_api = Blueprint('nonprofit_dashboard_api', __name__, url_prefix='/nonprofit')


def _check_business(staff, business_id):
    if staff.business_id != business_id:
        return jsonify({'message': 'Not authorized for this organization'}), 403
    return None


@nonprofit_dashboard_api.route('/businesses/<int:business_id>/payment-config', methods=['GET'])
@staff_required
def get_payment_config(staff, business_id):
    err = _check_business(staff, business_id)
    if err:
        return err
    config = NonprofitPaymentConfig.query.filter_by(business_id=business_id).first()
    return jsonify({
        'mosad_id': config.mosad_id if config else None,
        'api_valid': config.api_valid if config else None,
        # api_password is a real secret -- never echoed back, only whether
        # one is currently set (so the settings UI can show "configured"
        # without ever displaying or re-sending the actual value).
        'has_api_password': bool(config and config.api_password),
        'is_configured': bool(config and config.is_configured),
        'reports_configured': bool(config and config.reports_configured),
        'webhook_url': _webhook_url(business_id),
    })


@nonprofit_dashboard_api.route('/businesses/<int:business_id>/payment-config', methods=['PATCH'])
@superadmin_required
def update_payment_config(staff, business_id):
    err = _check_business(staff, business_id)
    if err:
        return err
    body = request.get_json() or {}
    config = NonprofitPaymentConfig.query.filter_by(business_id=business_id).first()
    if not config:
        config = NonprofitPaymentConfig(business_id=business_id)
        db.session.add(config)

    if 'mosad_id' in body:
        config.mosad_id = (body['mosad_id'] or '').strip() or None
    if 'api_valid' in body:
        config.api_valid = (body['api_valid'] or '').strip() or None
    if 'api_password' in body and body['api_password']:
        config.api_password = body['api_password'].strip()

    db.session.commit()
    return jsonify({
        'mosad_id': config.mosad_id, 'api_valid': config.api_valid,
        'has_api_password': bool(config.api_password),
        'is_configured': config.is_configured, 'reports_configured': config.reports_configured,
        'webhook_url': _webhook_url(business_id),
    })


def _new_tier_id(existing):
    """A short, stable, never-reused slug -- stays meaningful in old
    NonprofitMembership.tier values even after the tier is renamed, so it
    can't just be re-derived from the current label."""
    n = len(existing) + 1
    while True:
        candidate = f'tier-{n}'
        if not any(t['id'] == candidate for t in existing):
            return candidate
        n += 1


@nonprofit_dashboard_api.route('/businesses/<int:business_id>/membership-tiers', methods=['GET'])
@staff_required
def get_membership_tiers_route(staff, business_id):
    err = _check_business(staff, business_id)
    if err:
        return err
    business = db.session.get(Business, business_id)
    return jsonify({'tiers': get_membership_tiers(business), 'is_open': is_membership_open(business)})


@nonprofit_dashboard_api.route('/businesses/<int:business_id>/membership-tiers', methods=['PATCH'])
@superadmin_required
def update_membership_tiers_route(staff, business_id):
    """Replaces the whole tier list (add/edit/archive/reorder all happen
    client-side on the full list, then it's saved back in one call -- same
    shape as every other owner-editable list in this codebase, e.g.
    site_pages.py's page reordering). `is_open` is optional and, when
    given, is saved alongside in the same request."""
    err = _check_business(staff, business_id)
    if err:
        return err
    business = db.session.get(Business, business_id)
    if not business:
        return jsonify({'message': 'Business not found'}), 404

    body = request.get_json() or {}
    attrs = dict(business.attributes or {})

    if 'tiers' in body:
        tiers_in = body['tiers']
        if not isinstance(tiers_in, list) or len(tiers_in) > 20:
            return jsonify({'message': 'tiers must be a list of at most 20 items'}), 400
        existing = get_membership_tiers(business)
        cleaned = []
        for t in tiers_in:
            if not isinstance(t, dict):
                return jsonify({'message': 'Each tier must be an object'}), 400
            label = (t.get('label') or '').strip()
            if not label:
                return jsonify({'message': 'Each tier needs a label'}), 400
            try:
                monthly_cents = int(t.get('monthly_cents'))
            except (TypeError, ValueError):
                return jsonify({'message': f'"{label}" needs a valid monthly price'}), 400
            if monthly_cents <= 0:
                return jsonify({'message': f'"{label}" needs a monthly price greater than 0'}), 400
            tier_id = t.get('id')
            if not tier_id or not any(existing_t['id'] == tier_id for existing_t in existing):
                tier_id = _new_tier_id(cleaned + existing)
            cleaned.append({'id': tier_id, 'label': label, 'monthly_cents': monthly_cents, 'archived': bool(t.get('archived'))})
        if not any(not t['archived'] for t in cleaned):
            return jsonify({'message': 'At least one tier must be active'}), 400
        attrs['nonprofit_membership_tiers'] = cleaned

    if 'is_open' in body:
        attrs['nonprofit_membership_open'] = bool(body['is_open'])

    business.attributes = attrs
    db.session.commit()
    return jsonify({'tiers': get_membership_tiers(business), 'is_open': is_membership_open(business)})


@nonprofit_dashboard_api.route('/businesses/<int:business_id>/donate-open', methods=['GET'])
@staff_required
def get_donate_open(staff, business_id):
    err = _check_business(staff, business_id)
    if err:
        return err
    business = db.session.get(Business, business_id)
    return jsonify({'is_open': is_donations_open(business)})


@nonprofit_dashboard_api.route('/businesses/<int:business_id>/donate-open', methods=['PATCH'])
@superadmin_required
def update_donate_open(staff, business_id):
    err = _check_business(staff, business_id)
    if err:
        return err
    business = db.session.get(Business, business_id)
    if not business:
        return jsonify({'message': 'Business not found'}), 404
    body = request.get_json() or {}
    attrs = dict(business.attributes or {})
    attrs['nonprofit_donate_open'] = bool(body.get('is_open', True))
    business.attributes = attrs
    db.session.commit()
    return jsonify({'is_open': is_donations_open(business)})


@nonprofit_dashboard_api.route('/businesses/<int:business_id>/dashboard', methods=['GET'])
@staff_required
def dashboard(staff, business_id):
    err = _check_business(staff, business_id)
    if err:
        return err
    config = NonprofitPaymentConfig.query.filter_by(business_id=business_id).first()

    total_paid_donations_cents = db.session.query(db.func.coalesce(db.func.sum(NonprofitDonation.amount_cents), 0)).filter_by(
        business_id=business_id, status='paid',
    ).scalar()
    active_members = NonprofitMembership.query.filter_by(business_id=business_id, status='active').count()
    open_followups = NonprofitPaymentFollowUp.query.filter_by(business_id=business_id, status='open').count()
    other_transactions_total_cents = db.session.query(db.func.coalesce(db.func.sum(NonprofitExternalTransaction.amount_cents), 0)).filter_by(
        business_id=business_id,
    ).scalar()

    return jsonify({
        'total_paid_donations_cents': int(total_paid_donations_cents or 0),
        'active_members': active_members,
        'open_followups': open_followups,
        'other_transactions_total_cents': int(other_transactions_total_cents or 0),
        'family_portal_url': _family_portal_url(business_id),
        'warnings': {
            'nedarim_not_configured': not (config and config.is_configured),
            'nedarim_reports_not_configured': not (config and config.reports_configured),
            'email_not_configured': not bool(os.environ.get('RESEND_API_KEY') and os.environ.get('EMAIL_FROM')),
        },
    })
