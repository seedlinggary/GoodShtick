"""Payment follow-ups (decline/stale-pending tracking) and the "Other
Transactions" ledger (Nedarim Plus activity that didn't match anything
this system generated). Nedarim Plus has NO decline webhook at all -- see
nonprofit_webhook.py for the two automatic detectors (stale-pending sweep,
standing-order ErrorText scan); this file covers the staff-facing side:
viewing/resolving/dismissing follow-ups, sending the retry email, and the
third (manual) detector -- pasting a forwarded Nedarim Plus decline
email.
"""
import os
import re
from datetime import datetime

from flask import Blueprint, jsonify, request

from config import db
from backend.business.modals.nonprofit import (
    NonprofitPaymentFollowUp, NonprofitExternalTransaction, NonprofitFamily,
    NonprofitBill, NonprofitDonation, NonprofitMembership, NonprofitPaymentLink,
)
from backend.business.modals.business_site import BusinessSite
from backend.business.nonprofit_auth import staff_required
from backend.business.nonprofit_billid import new_reference_code
from backend.business.routes.nonprofit_audit import record_audit_log
from backend.business.routes.nonprofit_import_helpers import csv_response

nonprofit_followups_api = Blueprint('nonprofit_followups_api', __name__, url_prefix='/nonprofit')

_MODEL_BY_FIELD = {
    'bill_id': NonprofitBill, 'donation_id': NonprofitDonation,
    'membership_id': NonprofitMembership, 'payment_link_id': NonprofitPaymentLink,
}


def _pay_link_url(business_id, linked_record):
    """The follow-up email's "complete your payment" CTA -- a BACKEND
    route (nonprofit_public.py's pay_link_redirect), not a frontend one:
    clicking it 302-redirects straight to a freshly-built Nedarim Plus
    payment page, so it works even though the email itself has no
    stored Nedarim link lying around (and even if the record's amount/
    contact info was corrected since it was created)."""
    if not linked_record or not hasattr(linked_record, 'reference_code'):
        return ''
    site = BusinessSite.query.filter_by(business_id=business_id).first()
    if not site:
        return ''
    backend_base = os.environ.get('BACKEND_PUBLIC_URL', '')
    return f'{backend_base}/nonprofit/public/{site.subdomain}/pay-link/{linked_record.reference_code}'


def _check_business(staff, business_id):
    if staff.business_id != business_id:
        return jsonify({'message': 'Not authorized for this organization'}), 403
    return None


def _linked_record(followup):
    for field, model in _MODEL_BY_FIELD.items():
        rid = getattr(followup, field)
        if rid:
            return model.query.get(rid)
    return None


def _serialize_followup(f):
    linked = _linked_record(f)
    return {
        'id': f.id, 'reason': f.reason, 'status': f.status, 'notes': f.notes,
        'emails_sent_count': f.emails_sent_count,
        'last_email_sent_at': f.last_email_sent_at.isoformat() if f.last_email_sent_at else None,
        'resolved_at': f.resolved_at.isoformat() if f.resolved_at else None,
        'is_standalone': f.is_standalone,
        'full_name': (linked.full_name if linked else f.external_full_name),
        'email': (linked.email if linked else f.external_email),
        'phone': (linked.phone if linked else f.external_phone),
        'amount_cents': (
            (linked.total_cents if isinstance(linked, NonprofitBill) else getattr(linked, 'amount_cents', None) or getattr(linked, 'monthly_cents', None))
            if linked else f.external_amount_cents
        ),
        'failure_reason': f.failure_reason, 'card_last4': f.card_last4,
        'created_at': f.created_at.isoformat() if f.created_at else None,
    }


@nonprofit_followups_api.route('/businesses/<int:business_id>/payment-followups', methods=['GET'])
@staff_required
def list_followups(staff, business_id):
    err = _check_business(staff, business_id)
    if err:
        return err
    query = NonprofitPaymentFollowUp.query.filter_by(business_id=business_id)
    status = request.args.get('status')
    if status:
        query = query.filter_by(status=status)
    rows = query.order_by(NonprofitPaymentFollowUp.created_at.desc()).all()
    return jsonify({'followups': [_serialize_followup(f) for f in rows]})


@nonprofit_followups_api.route('/businesses/<int:business_id>/payment-followups/export', methods=['GET'])
@staff_required
def export_followups(staff, business_id):
    err = _check_business(staff, business_id)
    if err:
        return err
    query = NonprofitPaymentFollowUp.query.filter_by(business_id=business_id)
    status = request.args.get('status')
    if status:
        query = query.filter_by(status=status)
    rows = query.order_by(NonprofitPaymentFollowUp.created_at.desc()).all()
    header = ['Name', 'Email', 'Phone', 'Amount', 'Reason', 'Status', 'Failure reason', 'Emails sent', 'Created']
    data = []
    for f in rows:
        s = _serialize_followup(f)
        data.append([s['full_name'] or '', s['email'] or '', s['phone'] or '',
                     f"{(s['amount_cents'] or 0) / 100:.2f}", s['reason'], s['status'],
                     s['failure_reason'] or '', s['emails_sent_count'], s['created_at'] or ''])
    return csv_response(header, data, 'payment-followups.csv')


@nonprofit_followups_api.route('/payment-followups/<int:followup_id>/resolve', methods=['POST'])
@staff_required
def resolve_followup(staff, followup_id):
    f = NonprofitPaymentFollowUp.query.get(followup_id)
    if not f or f.business_id != staff.business_id:
        return jsonify({'message': 'Follow-up not found'}), 404
    f.status = 'resolved'
    f.resolved_at = datetime.utcnow()
    record_audit_log(f.business_id, staff.email, 'followup_resolve', 'NonprofitPaymentFollowUp', f.id, None)
    db.session.commit()
    return jsonify(_serialize_followup(f))


@nonprofit_followups_api.route('/payment-followups/<int:followup_id>/dismiss', methods=['POST'])
@staff_required
def dismiss_followup(staff, followup_id):
    f = NonprofitPaymentFollowUp.query.get(followup_id)
    if not f or f.business_id != staff.business_id:
        return jsonify({'message': 'Follow-up not found'}), 404
    f.status = 'dismissed'
    record_audit_log(f.business_id, staff.email, 'followup_dismiss', 'NonprofitPaymentFollowUp', f.id, None)
    db.session.commit()
    return jsonify(_serialize_followup(f))


def _is_email_configured():
    return bool(os.environ.get('RESEND_API_KEY') and os.environ.get('EMAIL_FROM'))


def _send_followup_email(to_email, full_name, amount_cents, pay_url, organization_name):
    """Best-effort, bilingual (English then Hebrew, same order the ported
    system's own email uses) -- never raises; a missing RESEND_API_KEY/
    EMAIL_FROM just silently skips sending (same 'not configured yet,
    don't crash' convention every other optional integration in this
    module follows)."""
    api_key = os.environ.get('RESEND_API_KEY')
    from_addr = os.environ.get('EMAIL_FROM')
    if not api_key or not from_addr:
        return False
    try:
        import resend
        resend.api_key = api_key
        from_name = os.environ.get('EMAIL_FROM_NAME', organization_name or 'Gut Shtick')
        amount = f'{amount_cents / 100:.2f}' if amount_cents else ''
        html = (
            f'<p>Hi {full_name},</p>'
            f'<p>We noticed your recent payment of ₪{amount} to {organization_name} didn\'t go through. '
            f'You can complete it here: <a href="{pay_url}">{pay_url}</a></p>'
            f'<p>Thank you,<br/>{organization_name}</p>'
            f'<hr/>'
            f'<div dir="rtl">'
            f'<p>שלום {full_name},</p>'
            f'<p>שמנו לב שהתשלום האחרון שלך בסך ₪{amount} ל{organization_name} לא הושלם. '
            f'ניתן להשלים אותו כאן: <a href="{pay_url}">{pay_url}</a></p>'
            f'<p>תודה,<br/>{organization_name}</p>'
            f'</div>'
        )
        resend.Emails.send({
            'from': f'{from_name} <{from_addr}>', 'to': [to_email],
            'subject': f'Complete your payment to {organization_name} / השלמת תשלום',
            'html': html,
        })
        return True
    except Exception:
        return False


def _provision_payment_link_for_standalone(followup):
    """The first time an email is sent for a STANDALONE follow-up (no FK
    at all), a real NonprofitPaymentLink gets created for it so it
    becomes properly trackable going forward -- its webhook can then
    auto-resolve it like anything else, instead of staying a dead-end
    external_* record forever."""
    link = NonprofitPaymentLink(
        business_id=followup.business_id, reference_code=new_reference_code(),
        label=f'Follow-up: {followup.external_category or "payment"}',
        amount_cents=followup.external_amount_cents or 0,
        full_name=followup.external_full_name, phone=followup.external_phone, email=followup.external_email,
    )
    db.session.add(link)
    db.session.flush()
    followup.payment_link_id = link.id
    return link


@nonprofit_followups_api.route('/payment-followups/<int:followup_id>/send-email', methods=['POST'])
@staff_required
def send_followup_email(staff, followup_id):
    from backend.business.modals.business import Business

    f = NonprofitPaymentFollowUp.query.get(followup_id)
    if not f or f.business_id != staff.business_id:
        return jsonify({'message': 'Follow-up not found'}), 404

    linked = _linked_record(f)
    link = None
    if f.is_standalone:
        link = _provision_payment_link_for_standalone(f)
        linked = link

    email = (linked.email if linked else None) or f.external_email
    if not email:
        return jsonify({'message': 'No email on file for this record'}), 400

    business = db.session.get(Business, f.business_id)
    amount_cents = getattr(linked, 'amount_cents', None) or getattr(linked, 'monthly_cents', None) or \
        (linked.total_cents if isinstance(linked, NonprofitBill) else None) or f.external_amount_cents
    pay_url = _pay_link_url(f.business_id, linked)
    sent = _send_followup_email(email, (linked.full_name if linked else f.external_full_name) or 'there',
                                 amount_cents, pay_url, business.name if business else 'us')
    if not sent:
        return jsonify({'message': 'Email is not configured yet, or sending failed'}), 400

    f.emails_sent_count += 1
    f.last_email_sent_at = datetime.utcnow()
    f.status = 'email_sent'
    record_audit_log(f.business_id, staff.email, 'followup_send_email', 'NonprofitPaymentFollowUp', f.id, None)
    db.session.commit()
    return jsonify(_serialize_followup(f))


@nonprofit_followups_api.route('/businesses/<int:business_id>/payment-followups/send-all', methods=['POST'])
@staff_required
def send_all_followup_emails(staff, business_id):
    err = _check_business(staff, business_id)
    if err:
        return err
    rows = NonprofitPaymentFollowUp.query.filter_by(business_id=business_id, status='open').all()
    sent, skipped = 0, 0
    for f in rows:
        # send_followup_email is decorator-wrapped (staff_required reads
        # the token straight from request headers each call), so it can't
        # be called directly in a loop with an already-authenticated
        # staff -- the minimal send path is reimplemented inline instead.
        linked = _linked_record(f)
        if f.is_standalone:
            linked = _provision_payment_link_for_standalone(f)
        email = (linked.email if linked else None) or f.external_email
        if not email:
            skipped += 1
            continue
        from backend.business.modals.business import Business
        business = db.session.get(Business, business_id)
        amount_cents = getattr(linked, 'amount_cents', None) or getattr(linked, 'monthly_cents', None) or \
            (linked.total_cents if isinstance(linked, NonprofitBill) else None) or f.external_amount_cents
        pay_url = _pay_link_url(business_id, linked)
        if _send_followup_email(email, (linked.full_name if linked else f.external_full_name) or 'there',
                                 amount_cents, pay_url, business.name if business else 'us'):
            f.emails_sent_count += 1
            f.last_email_sent_at = datetime.utcnow()
            f.status = 'email_sent'
            sent += 1
        else:
            skipped += 1
    record_audit_log(business_id, staff.email, 'followup_send_all', 'NonprofitPaymentFollowUp', 0, {'sent': {'before': None, 'after': sent}})
    db.session.commit()
    return jsonify({'sent': sent, 'skipped': skipped})


@nonprofit_followups_api.route('/businesses/<int:business_id>/payment-followups/flag', methods=['POST'])
@staff_required
def flag_followup(staff, business_id):
    """Manual, immediate flag -- for when staff already know about a
    problem (e.g. a donor called in) without waiting for the cron or
    pasting a full decline email."""
    err = _check_business(staff, business_id)
    if err:
        return err
    body = request.get_json() or {}
    f = NonprofitPaymentFollowUp(
        business_id=business_id, reason='manual', notes=body.get('notes'),
        external_full_name=body.get('full_name'), external_phone=body.get('phone'),
        external_email=body.get('email'), external_amount_cents=body.get('amount_cents'),
        external_category=body.get('category'),
    )
    db.session.add(f)
    db.session.flush()
    record_audit_log(business_id, staff.email, 'followup_flag_manual', 'NonprofitPaymentFollowUp', f.id, None)
    db.session.commit()
    return jsonify(_serialize_followup(f)), 201


# ── Manual decline-email import (3rd detector) ──────────────────────────
# Nedarim Plus's own decline notification is a fixed-format Hebrew email,
# not an API call -- staff forward it and paste the body here. Fixed
# "label: value" line format, parsed defensively (a line that doesn't
# match any known label is simply ignored, never a hard error).
_EMAIL_FIELD_MAP = {
    'מספר הוראה': 'order_number', 'מספר עסקה': 'order_number',
    'שם לקוח': 'client_name', 'סכום': 'amount', 'סיבת שגיאה': 'failure_reason',
    '4 ספרות אחרונות': 'card_last4', 'טלפון': 'phone', 'מייל': 'email',
}


def parse_failure_email(text):
    parsed = {}
    for line in (text or '').splitlines():
        if ':' not in line:
            continue
        label, _, value = line.partition(':')
        key = _EMAIL_FIELD_MAP.get(label.strip())
        if key:
            parsed[key] = value.strip()
    return parsed


@nonprofit_followups_api.route('/businesses/<int:business_id>/payment-followups/import-failure-email', methods=['POST'])
@staff_required
def import_failure_email(staff, business_id):
    err = _check_business(staff, business_id)
    if err:
        return err
    body = request.get_json() or {}
    raw_text = body.get('email_text') or ''
    parsed = parse_failure_email(raw_text)
    if not parsed:
        return jsonify({'message': 'Could not recognize this as a Nedarim Plus decline email'}), 400

    order_number = parsed.get('order_number')
    membership = NonprofitMembership.query.filter_by(business_id=business_id, keva_id=order_number).first() if order_number else None

    amount_cents = None
    if parsed.get('amount'):
        try:
            amount_cents = round(float(re.sub(r'[^\d.]', '', parsed['amount'])) * 100)
        except ValueError:
            amount_cents = None

    f = NonprofitPaymentFollowUp(
        business_id=business_id, reason='failure_email',
        membership_id=membership.id if membership else None,
        external_full_name=None if membership else parsed.get('client_name'),
        external_phone=None if membership else parsed.get('phone'),
        external_email=None if membership else parsed.get('email'),
        external_amount_cents=None if membership else amount_cents,
        external_keva_id=None if membership else order_number,
        failure_reason=parsed.get('failure_reason'), card_last4=parsed.get('card_last4'),
    )
    db.session.add(f)
    db.session.flush()
    record_audit_log(business_id, staff.email, 'followup_import_failure_email', 'NonprofitPaymentFollowUp', f.id, None)
    db.session.commit()
    return jsonify(_serialize_followup(f)), 201


# ── Other Transactions (unmatched Nedarim Plus activity ledger) ────────

def _serialize_external(e):
    return {
        'id': e.id, 'amount_cents': e.amount_cents, 'client_name': e.client_name, 'phone': e.phone,
        'email': e.email, 'groupe': e.groupe, 'comments': e.comments, 'keva_id': e.keva_id,
        'family_id': e.family_id, 'family_name': e.family.full_name if e.family else None,
        'received_at': e.received_at.isoformat() if e.received_at else None,
    }


@nonprofit_followups_api.route('/businesses/<int:business_id>/other-transactions', methods=['GET'])
@staff_required
def list_external_transactions(staff, business_id):
    err = _check_business(staff, business_id)
    if err:
        return err
    rows = NonprofitExternalTransaction.query.filter_by(business_id=business_id).order_by(NonprofitExternalTransaction.received_at.desc()).all()
    return jsonify({'transactions': [_serialize_external(e) for e in rows]})


@nonprofit_followups_api.route('/businesses/<int:business_id>/other-transactions/export', methods=['GET'])
@staff_required
def export_external_transactions(staff, business_id):
    err = _check_business(staff, business_id)
    if err:
        return err
    rows = NonprofitExternalTransaction.query.filter_by(business_id=business_id).order_by(NonprofitExternalTransaction.received_at.desc()).all()
    header = ['Name', 'Amount', 'Category', 'Comments', 'Received']
    data = [[e.client_name or '', f'{e.amount_cents / 100:.2f}', e.groupe or '', e.comments or '',
             e.received_at.isoformat() if e.received_at else ''] for e in rows]
    return csv_response(header, data, 'other-transactions.csv')


@nonprofit_followups_api.route('/other-transactions/<int:txn_id>/link-family', methods=['PATCH'])
@staff_required
def link_external_to_family(staff, txn_id):
    txn = NonprofitExternalTransaction.query.get(txn_id)
    if not txn or txn.business_id != staff.business_id:
        return jsonify({'message': 'Transaction not found'}), 404
    body = request.get_json() or {}
    family_id = body.get('family_id')
    if family_id is not None:
        family = NonprofitFamily.query.get(family_id)
        if not family or family.business_id != staff.business_id:
            return jsonify({'message': 'Family not found'}), 404
    txn.family_id = family_id
    record_audit_log(txn.business_id, staff.email, 'external_transaction_link_family', 'NonprofitExternalTransaction', txn.id, None)
    db.session.commit()
    return jsonify(_serialize_external(txn))
