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
    NonprofitHolidayTier, NonprofitBill, NonprofitSignup, NonprofitForm, NonprofitFormResponse,
    NonprofitPaymentConfig, get_membership_tiers, is_membership_open, is_donations_open,
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


def _site_and_business_for_forms(subdomain):
    """Same shape as _site_and_business above, but used ONLY by the two
    form routes below -- the dynamic form builder (NonprofitForm et al.)
    stopped being nonprofit-exclusive (see backend/business/routes/
    site_forms.py's own docstring for why: any business can turn on the
    'custom_forms' module now, same as Products/Bookings/CRM/Invoices).
    Every OTHER route in this file (donations, memberships, holidays) is
    still strictly nonprofit-only on purpose -- only this helper accepts
    either module flag."""
    site = BusinessSite.query.filter_by(subdomain=(subdomain or '').strip().lower(), status='published').first()
    if not site or not (site.has_module('nonprofit') or site.has_module('custom_forms')):
        return None, None
    business = db.session.get(Business, site.business_id)
    if not business:
        return None, None
    return site, business


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


@nonprofit_public_api.route('/<subdomain>/donate-status', methods=['GET'])
def donate_status(subdomain):
    site, business, _config = _site_and_business(subdomain)
    if not site:
        return jsonify({'message': 'Not found'}), 404
    return jsonify({'is_open': is_donations_open(business)})


@nonprofit_public_api.route('/<subdomain>/donate', methods=['POST'])
def submit_donation(subdomain):
    site, business, config = _site_and_business(subdomain)
    if not site:
        return jsonify({'message': 'Not found'}), 404
    if not config or not config.is_configured:
        return jsonify({'message': 'Online giving is not set up yet for this organization'}), 400
    if not is_donations_open(business):
        return jsonify({'message': 'This organization is not accepting online donations right now'}), 400

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


@nonprofit_public_api.route('/<subdomain>/membership-tiers', methods=['GET'])
def list_public_membership_tiers(subdomain):
    site, business, _config = _site_and_business(subdomain)
    if not site:
        return jsonify({'message': 'Not found'}), 404
    tiers = [t for t in get_membership_tiers(business) if not t.get('archived')]
    return jsonify({'tiers': tiers, 'is_open': is_membership_open(business)})


@nonprofit_public_api.route('/<subdomain>/membership', methods=['POST'])
def submit_membership(subdomain):
    site, business, config = _site_and_business(subdomain)
    if not site:
        return jsonify({'message': 'Not found'}), 404
    if not config or not config.is_configured:
        return jsonify({'message': 'Online membership payments are not set up yet for this organization'}), 400
    if not is_membership_open(business):
        return jsonify({'message': 'This organization is not accepting new members online right now'}), 400

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
    tier_id = body.get('tier')

    if not full_name or not email or '@' not in email:
        return jsonify({'message': 'A name and valid email are required'}), 400

    tier = next((t for t in get_membership_tiers(business) if t['id'] == tier_id and not t.get('archived')), None)
    if not tier:
        return jsonify({'message': 'Choose a valid membership tier'}), 400
    monthly_cents = tier['monthly_cents']

    membership = NonprofitMembership(
        business_id=business.id, reference_code=_new_reference_code(), full_name=full_name,
        email=email, tier=tier['id'], monthly_cents=monthly_cents, phone=phone, address=address, city=city,
    )
    db.session.add(membership)
    db.session.commit()
    maybe_detect_payment_failures(business.id)

    redirect_url = f'{_origin(subdomain)}/pay/thank-you?membership={membership.reference_code}'
    link = build_recurring_payment_link(
        config.mosad_id, membership.id, monthly_cents, full_name, redirect_url,
        phone=phone, email=email, street=address, city=city, groupe=tier['label'],
    )
    return jsonify({'reference_code': membership.reference_code, 'payment_url': link}), 201


@nonprofit_public_api.route('/<subdomain>/holidays', methods=['GET'])
def list_public_holidays(subdomain):
    site, business, _config = _site_and_business(subdomain)
    if not site:
        return jsonify({'message': 'Not found'}), 404
    rows = NonprofitHoliday.query.filter_by(business_id=business.id, is_open=True).order_by(NonprofitHoliday.id).all()
    # Only holidays that still have at least one active tier are worth
    # showing -- an event whose owner archived every tier (or never added
    # one) has nothing a visitor could actually buy.
    return jsonify({'holidays': [_public_holiday(h) for h in rows if any(not t.archived_at for t in h.tiers)]})


def _public_holiday(h):
    return {
        'id': h.id, 'slug': h.slug, 'name_en': h.name_en, 'name_he': h.name_he,
        'description_en': h.description_en, 'description_he': h.description_he,
        'tiers': [{'id': t.id, 'label': t.label, 'price_cents': t.price_cents}
                  for t in h.tiers if not t.archived_at],
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
    notes = (body.get('notes') or '').strip() or None
    items = body.get('items') or []  # [{holiday_id, seats: {tier_id: count}}]

    if not full_name or not phone:
        return jsonify({'message': 'Name and phone are required'}), 400
    if not isinstance(items, list) or not items:
        return jsonify({'message': 'Select at least one holiday'}), 400

    # Re-validate server-side -- a holiday/tier could have closed between
    # page load and submit. Closed/unknown holidays and tiers are
    # silently dropped, not an error, same as the ported system's own
    # createBill. `is_member` no longer drives pricing (tiers do), but the
    # bill still records it for the family/membership context elsewhere
    # (exports, family portal) -- best-effort true if ANY seat was bought
    # on a tier whose label looks like a member tier isn't reliable, so
    # it's just left false; staff can set it by hand if needed.
    bill = NonprofitBill(
        business_id=business.id, reference_code=_new_reference_code(), full_name=full_name,
        phone=phone, email=email, is_member=False, notes=notes,
    )
    db.session.add(bill)
    db.session.flush()

    total_cents = 0
    names = []
    for item in items:
        holiday = NonprofitHoliday.query.filter_by(id=item.get('holiday_id'), business_id=business.id, is_open=True).first()
        if not holiday:
            continue
        seats = item.get('seats') or {}
        if not isinstance(seats, dict):
            continue
        active_tiers = {t.id: t for t in holiday.tiers if not t.archived_at}
        breakdown = {}
        line_total = 0
        for tier_id_raw, count_raw in seats.items():
            try:
                tier_id, count = int(tier_id_raw), max(0, int(count_raw or 0))
            except (TypeError, ValueError):
                continue
            tier = active_tiers.get(tier_id)
            if not tier or count <= 0:
                continue
            breakdown[str(tier_id)] = count
            line_total += tier.price_cents * count
        if line_total <= 0:
            continue
        signup = NonprofitSignup(bill_id=bill.id, holiday_id=holiday.id, total_cents=line_total, seat_breakdown=breakdown)
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
    site, business = _site_and_business_for_forms(subdomain)
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
    site, business = _site_and_business_for_forms(subdomain)
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
