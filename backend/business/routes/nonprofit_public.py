"""Public (no staff-auth) nonprofit routes -- donations, memberships,
holiday-seat sales, dynamic form submission, and the post-payment
thank-you/status lookup. Mirrors business_site_public.py's own "only ever
serve what's actually public" framing: everything here is scoped by
subdomain -> BusinessSite with the 'nonprofit' module enabled, never by a
client-supplied business_id.
"""
import os
from urllib.parse import urlparse

from flask import Blueprint, jsonify, request, redirect

from config import db
from backend.guest.modals.guest_throttle import check_and_record_guest_submission
from backend.business.modals.business import Business
from backend.business.modals.business_site import BusinessSite
from backend.business.modals.nonprofit import (
    NonprofitDonation, NonprofitMembership, NonprofitPaymentLink, NonprofitHoliday,
    NonprofitBill, NonprofitSignup, NonprofitForm, NonprofitFormResponse,
    NonprofitPaymentConfig, MEMBERSHIP_TIERS,
)
from backend.business.nonprofit_payments.nedarim import build_payment_link, build_recurring_payment_link
from backend.business.nonprofit_billid import new_reference_code as _new_reference_code
from backend.business.routes.nonprofit_webhook import maybe_detect_payment_failures
from backend.business.routes.business_site_public import _verify_captcha

nonprofit_public_api = Blueprint('nonprofit_public_api', __name__, url_prefix='/nonprofit/public')


def _site_and_business(subdomain):
    site = BusinessSite.query.filter_by(subdomain=(subdomain or '').strip().lower(), status='published').first()
    if not site or not site.has_module('nonprofit'):
        return None, None, None
    business = db.session.get(Business, site.business_id)
    if not business:
        return None, None, None
    config = NonprofitPaymentConfig.query.filter_by(business_id=business.id).first()
    return site, business, config


def _public_site_origin(subdomain):
    """The nonprofit's own public site origin, built directly from
    BUSINESS_SITE_BASE_DOMAIN -- unlike _origin() below (which reflects
    the calling fetch()'s own Origin header, correct for the donate/
    membership/holiday-seats routes that are always called FROM that
    site), this is used for a plain top-level browser navigation (a link
    clicked in an email) that never sends an Origin header at all, so
    reflecting one would silently fall through to this BACKEND's own
    host instead of the actual public-facing site."""
    base = os.environ.get('BUSINESS_SITE_BASE_DOMAIN')
    if base:
        return f'https://{subdomain}.{base}'
    return os.environ.get('BACKEND_PUBLIC_URL', request.host_url.rstrip('/'))


def _origin(subdomain):
    origin = request.headers.get('Origin')
    allowed_base = os.environ.get('BUSINESS_SITE_BASE_DOMAIN')
    if origin:
        parsed = urlparse(origin)
        if parsed.scheme in ('http', 'https') and parsed.hostname:
            expected = f'{subdomain}.{allowed_base}' if allowed_base else None
            if parsed.hostname in ('localhost', '127.0.0.1') or (expected and parsed.hostname == expected) or not allowed_base:
                return f'{parsed.scheme}://{parsed.netloc}'
    return os.environ.get('BACKEND_PUBLIC_URL', request.host_url.rstrip('/'))


def _throttle_or_error():
    if not check_and_record_guest_submission(request):
        return jsonify({'message': 'Too many submissions today -- try again tomorrow'}), 429
    return None


@nonprofit_public_api.route('/<subdomain>/donate', methods=['POST'])
def submit_donation(subdomain):
    site, business, config = _site_and_business(subdomain)
    if not site:
        return jsonify({'message': 'Not found'}), 404
    if not config or not config.is_configured:
        return jsonify({'message': 'Online giving is not set up yet for this organization'}), 400

    throttled = _throttle_or_error()
    if throttled:
        return throttled

    body = request.get_json() or {}
    if not _verify_captcha(body.get('captcha_token'), request.remote_addr):
        return jsonify({'message': 'Please complete the verification challenge and try again'}), 400
    full_name = (body.get('full_name') or '').strip()
    email = (body.get('email') or '').strip().lower()
    phone = (body.get('phone') or '').strip() or None
    address = (body.get('address') or '').strip() or None
    city = (body.get('city') or '').strip() or None
    purpose = (body.get('purpose') or '').strip() or None
    try:
        amount_cents = int(round(float(body.get('amount') or 0) * 100))
    except (TypeError, ValueError):
        amount_cents = 0

    if not full_name or not email or '@' not in email:
        return jsonify({'message': 'A name and valid email are required'}), 400
    if amount_cents <= 0:
        return jsonify({'message': 'Amount must be greater than 0'}), 400

    donation = NonprofitDonation(
        business_id=business.id, reference_code=_new_reference_code(), full_name=full_name,
        email=email, amount_cents=amount_cents, phone=phone, address=address, city=city, purpose=purpose,
    )
    db.session.add(donation)
    db.session.commit()
    maybe_detect_payment_failures(business.id)

    redirect_url = f'{_origin(subdomain)}/pay/thank-you?donation={donation.reference_code}'
    link = build_payment_link(
        config.mosad_id, 'DON', donation.id, amount_cents, full_name, redirect_url,
        phone=phone, email=email, street=address, city=city, groupe=purpose,
    )
    return jsonify({'reference_code': donation.reference_code, 'payment_url': link}), 201


@nonprofit_public_api.route('/<subdomain>/membership', methods=['POST'])
def submit_membership(subdomain):
    site, business, config = _site_and_business(subdomain)
    if not site:
        return jsonify({'message': 'Not found'}), 404
    if not config or not config.is_configured:
        return jsonify({'message': 'Online membership payments are not set up yet for this organization'}), 400

    throttled = _throttle_or_error()
    if throttled:
        return throttled

    body = request.get_json() or {}
    if not _verify_captcha(body.get('captcha_token'), request.remote_addr):
        return jsonify({'message': 'Please complete the verification challenge and try again'}), 400
    full_name = (body.get('full_name') or '').strip()
    email = (body.get('email') or '').strip().lower()
    phone = (body.get('phone') or '').strip() or None
    address = (body.get('address') or '').strip() or None
    city = (body.get('city') or '').strip() or None
    tier = body.get('tier') or 'associate'

    if not full_name or not email or '@' not in email:
        return jsonify({'message': 'A name and valid email are required'}), 400
    if tier not in MEMBERSHIP_TIERS:
        return jsonify({'message': f'tier must be one of {MEMBERSHIP_TIERS}'}), 400

    prices = _membership_prices(business.id)
    monthly_cents = prices.get(tier)
    if not monthly_cents:
        return jsonify({'message': 'Membership pricing is not configured yet'}), 400

    membership = NonprofitMembership(
        business_id=business.id, reference_code=_new_reference_code(), full_name=full_name,
        email=email, tier=tier, monthly_cents=monthly_cents, phone=phone, address=address, city=city,
    )
    db.session.add(membership)
    db.session.commit()
    maybe_detect_payment_failures(business.id)

    redirect_url = f'{_origin(subdomain)}/pay/thank-you?membership={membership.reference_code}'
    link = build_recurring_payment_link(
        config.mosad_id, membership.id, monthly_cents, full_name, redirect_url,
        phone=phone, email=email, street=address, city=city, groupe=tier,
    )
    return jsonify({'reference_code': membership.reference_code, 'payment_url': link}), 201


def _membership_prices(business_id):
    """Fixed per-business pricing, stored on the Business's own
    `attributes` JSON catch-all (same convention Business already uses
    for small per-business config -- no new table needed for two numbers).
    Falls back to the ported system's own default prices (associate
    ₪100/mo, full ₪200/mo) if the owner hasn't set their own yet."""
    business = db.session.get(Business, business_id)
    attrs = (business.attributes or {}) if business else {}
    configured = attrs.get('nonprofit_membership_prices_cents') or {}
    return {
        'associate': configured.get('associate', 10000),
        'full': configured.get('full', 20000),
    }


@nonprofit_public_api.route('/<subdomain>/holidays', methods=['GET'])
def list_public_holidays(subdomain):
    site, business, _config = _site_and_business(subdomain)
    if not site:
        return jsonify({'message': 'Not found'}), 404
    rows = NonprofitHoliday.query.filter_by(business_id=business.id, is_open=True).order_by(NonprofitHoliday.id).all()
    return jsonify({'holidays': [_public_holiday(h) for h in rows]})


def _public_holiday(h):
    return {
        'id': h.id, 'slug': h.slug, 'name_en': h.name_en, 'name_he': h.name_he,
        'description_en': h.description_en, 'description_he': h.description_he,
        'member_price_cents': h.member_price_cents, 'non_member_price_cents': h.non_member_price_cents,
    }


@nonprofit_public_api.route('/<subdomain>/holiday-seats', methods=['POST'])
def submit_holiday_seats(subdomain):
    site, business, config = _site_and_business(subdomain)
    if not site:
        return jsonify({'message': 'Not found'}), 404
    if not config or not config.is_configured:
        return jsonify({'message': 'Online payment is not set up yet for this organization'}), 400

    throttled = _throttle_or_error()
    if throttled:
        return throttled

    body = request.get_json() or {}
    if not _verify_captcha(body.get('captcha_token'), request.remote_addr):
        return jsonify({'message': 'Please complete the verification challenge and try again'}), 400
    full_name = (body.get('full_name') or '').strip()
    phone = (body.get('phone') or '').strip()
    email = (body.get('email') or '').strip().lower() or None
    is_member = bool(body.get('is_member'))
    notes = (body.get('notes') or '').strip() or None
    items = body.get('items') or []  # [{holiday_id, men_seats, women_seats}]

    if not full_name or not phone:
        return jsonify({'message': 'Name and phone are required'}), 400
    if not isinstance(items, list) or not items:
        return jsonify({'message': 'Select at least one holiday'}), 400

    # Re-validate server-side -- a holiday could have closed between page
    # load and submit. Closed/unknown holidays are silently dropped, not
    # an error, same as the ported system's own createBill.
    bill = NonprofitBill(
        business_id=business.id, reference_code=_new_reference_code(), full_name=full_name,
        phone=phone, email=email, is_member=is_member, notes=notes,
    )
    db.session.add(bill)
    db.session.flush()

    total_cents = 0
    names = []
    for item in items:
        holiday = NonprofitHoliday.query.filter_by(id=item.get('holiday_id'), business_id=business.id, is_open=True).first()
        if not holiday:
            continue
        men = max(0, int(item.get('men_seats') or 0))
        women = max(0, int(item.get('women_seats') or 0))
        if men + women <= 0:
            continue
        line_total = holiday.price_for(is_member) * (men + women)
        signup = NonprofitSignup(bill_id=bill.id, holiday_id=holiday.id, men_seats=men, women_seats=women, total_cents=line_total)
        db.session.add(signup)
        total_cents += line_total
        names.append(holiday.name_en)

    if total_cents <= 0:
        db.session.rollback()
        return jsonify({'message': 'Select at least one open holiday with seats'}), 400

    bill.total_cents = total_cents
    db.session.commit()
    maybe_detect_payment_failures(business.id)

    redirect_url = f'{_origin(subdomain)}/pay/thank-you?bill={bill.reference_code}'
    link = build_payment_link(
        config.mosad_id, 'BILL', bill.id, total_cents, full_name, redirect_url,
        phone=phone, email=email, groupe=', '.join(names),
    )
    return jsonify({'reference_code': bill.reference_code, 'payment_url': link}), 201


@nonprofit_public_api.route('/<subdomain>/pay/status', methods=['GET'])
def payment_status(subdomain):
    """Backs the thank-you page -- looks up whichever of bill/donation/
    membership/link a `?bill=`/`?donation=`/`?membership=`/`?link=` query
    param names, by its (unguessable, 7-char) reference_code, and reports
    its current status. Deliberately not cached/static on the frontend
    side (force-dynamic, same as the ported system) so it never shows a
    stale status right after a webhook lands."""
    site, business, _config = _site_and_business(subdomain)
    if not site:
        return jsonify({'message': 'Not found'}), 404

    for param, model, label in (
        ('bill', NonprofitBill, 'holiday_seats'),
        ('donation', NonprofitDonation, 'donation'),
        ('membership', NonprofitMembership, 'membership'),
        ('link', NonprofitPaymentLink, 'payment_link'),
    ):
        code = request.args.get(param)
        if not code:
            continue
        record = model.query.filter_by(business_id=business.id, reference_code=code).first()
        if not record:
            return jsonify({'message': 'Not found'}), 404
        return jsonify({'type': label, 'status': record.status, 'full_name': record.full_name})

    return jsonify({'message': 'No reference provided'}), 400


@nonprofit_public_api.route('/<subdomain>/pay-link/<reference_code>', methods=['GET'])
def pay_link_redirect(subdomain, reference_code):
    """What a follow-up retry email's CTA actually points at -- looks up
    `reference_code` across all four payable types and 302-redirects
    straight to a freshly-built Nedarim Plus payment page for it (one-
    time for Bill/Donation/PaymentLink, recurring for Membership). Built
    fresh every time rather than reusing a stored link, since the record
    may have been corrected (amount, contact info) since it was created."""
    site, business, config = _site_and_business(subdomain)
    if not site:
        return jsonify({'message': 'Not found'}), 404
    if not config or not config.is_configured:
        return jsonify({'message': 'Online payment is not set up for this organization'}), 400

    for prefix, model in (('BILL', NonprofitBill), ('DON', NonprofitDonation), ('LINK', NonprofitPaymentLink)):
        record = model.query.filter_by(business_id=business.id, reference_code=reference_code).first()
        if record:
            amount_cents = record.total_cents if prefix == 'BILL' else record.amount_cents
            param_name = {'BILL': 'bill', 'DON': 'donation', 'LINK': 'link'}[prefix]
            redirect_url = f'{_public_site_origin(subdomain)}/pay/thank-you?{param_name}={record.reference_code}'
            link = build_payment_link(
                config.mosad_id, prefix, record.id, amount_cents, record.full_name or 'Unknown', redirect_url,
                phone=getattr(record, 'phone', None), email=getattr(record, 'email', None),
            )
            return redirect(link)

    membership = NonprofitMembership.query.filter_by(business_id=business.id, reference_code=reference_code).first()
    if membership:
        redirect_url = f'{_public_site_origin(subdomain)}/pay/thank-you?membership={membership.reference_code}'
        link = build_recurring_payment_link(
            config.mosad_id, membership.id, membership.monthly_cents, membership.full_name, redirect_url,
            phone=membership.phone, email=membership.email,
        )
        return redirect(link)

    return jsonify({'message': 'Not found'}), 404


@nonprofit_public_api.route('/<subdomain>/forms/<slug>', methods=['GET'])
def get_public_form(subdomain, slug):
    site, business, _config = _site_and_business(subdomain)
    if not site:
        return jsonify({'message': 'Not found'}), 404
    form = NonprofitForm.query.filter_by(business_id=business.id, slug=(slug or '').strip().lower(), is_open=True).first()
    if not form:
        return jsonify({'message': 'Form not found'}), 404
    fields = [f for f in form.fields if not f.archived_at]
    return jsonify({
        'id': form.id, 'slug': form.slug, 'title': form.title, 'description': form.description,
        'fields': [_public_field(f) for f in fields],
    })


def _public_field(f):
    return {
        'id': f.id, 'label': f.label, 'type': f.type, 'required': f.required,
        'options': f.options, 'help_text': f.help_text, 'order': f.order,
        'condition_field_id': f.condition_field_id, 'condition_value': f.condition_value,
        'condition_mode': f.condition_mode, 'alt_label': f.alt_label,
    }


@nonprofit_public_api.route('/<subdomain>/forms/<slug>/responses', methods=['POST'])
def submit_public_form(subdomain, slug):
    site, business, _config = _site_and_business(subdomain)
    if not site:
        return jsonify({'message': 'Not found'}), 404
    form = NonprofitForm.query.filter_by(business_id=business.id, slug=(slug or '').strip().lower(), is_open=True).first()
    if not form:
        return jsonify({'message': 'Form not found'}), 404

    throttled = _throttle_or_error()
    if throttled:
        return throttled

    body = request.get_json() or {}
    answers = body.get('answers') or {}
    if not isinstance(answers, dict):
        return jsonify({'message': 'answers must be an object'}), 400

    live_field_ids = {str(f.id) for f in form.fields if not f.archived_at}
    required_ids = {str(f.id) for f in form.fields if not f.archived_at and f.required}
    # Strip anything the client sent for a field that doesn't exist (or is
    # archived) on this form -- defense in depth; the public form itself
    # already strips hidden-field answers before submit, but a direct API
    # call bypasses that client-side logic entirely.
    cleaned = {k: v for k, v in answers.items() if k in live_field_ids}
    missing = [fid for fid in required_ids if not cleaned.get(fid)]
    if missing:
        return jsonify({'message': 'Please fill in all required fields'}), 400

    response = NonprofitFormResponse(form_id=form.id, answers=cleaned)
    db.session.add(response)
    db.session.commit()
    return jsonify({'message': form.thank_you_message or 'Thank you -- your response has been received.'}), 201
