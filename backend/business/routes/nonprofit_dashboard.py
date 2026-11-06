"""Nedarim Plus credentials settings, membership pricing, and the admin
dashboard's own stat cards + configuration-warning banners."""
import os

from flask import Blueprint, jsonify, request

from config import db
from backend.business.modals.business import Business
from backend.business.modals.business_site import BusinessSite
from backend.business.modals.nonprofit import (
    NonprofitPaymentConfig, NonprofitDonation, NonprofitMembership,
    NonprofitPaymentFollowUp, NonprofitExternalTransaction, MEMBERSHIP_TIERS,
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


@nonprofit_dashboard_api.route('/businesses/<int:business_id>/membership-prices', methods=['GET'])
@staff_required
def get_membership_prices(staff, business_id):
    err = _check_business(staff, business_id)
    if err:
        return err
    business = db.session.get(Business, business_id)
    configured = ((business.attributes or {}).get('nonprofit_membership_prices_cents') or {}) if business else {}
    return jsonify({
        'associate': configured.get('associate', 10000),
        'full': configured.get('full', 20000),
    })


@nonprofit_dashboard_api.route('/businesses/<int:business_id>/membership-prices', methods=['PATCH'])
@superadmin_required
def update_membership_prices(staff, business_id):
    err = _check_business(staff, business_id)
    if err:
        return err
    business = db.session.get(Business, business_id)
    if not business:
        return jsonify({'message': 'Business not found'}), 404

    body = request.get_json() or {}
    attrs = dict(business.attributes or {})
    prices = dict(attrs.get('nonprofit_membership_prices_cents') or {})
    for tier in MEMBERSHIP_TIERS:
        if tier in body:
            try:
                prices[tier] = int(body[tier])
            except (TypeError, ValueError):
                return jsonify({'message': f'{tier} must be an integer'}), 400
    attrs['nonprofit_membership_prices_cents'] = prices
    business.attributes = attrs
    db.session.commit()
    return jsonify(prices)


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
