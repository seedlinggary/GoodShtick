"""The family portal -- "put in your email, get a 6-digit code, see your
own family's donations/membership/holiday seats/payment links/form
responses." No account, no password: see
modals/nonprofit.py:NonprofitFamilyLoginCode's docstring for why a code-by-
email exchange was chosen over a real login, and nonprofit_family_auth.py
for the token this issues once that exchange succeeds.

Deliberately its own blueprint, not folded into nonprofit_public.py --
that file is already the single largest public-routes file in this
module; this keeps the login-code lifecycle (request/verify) and the one
authenticated read (`/me`) together and separable.
"""
import os
import secrets
from datetime import datetime, timedelta

from flask import Blueprint, jsonify, request
from sqlalchemy import func
from werkzeug.security import check_password_hash, generate_password_hash

from config import db
from backend.business.modals.nonprofit import (
    NonprofitFamily, NonprofitFamilyLoginCode, NonprofitBill, NonprofitDonation,
    NonprofitMembership, NonprofitPaymentLink, NonprofitExternalTransaction, NonprofitFormResponse,
)
from backend.business.nonprofit_family_auth import generate_family_token, family_required
from backend.business.routes.nonprofit_public import _site_and_business, _throttle_or_error
from backend.business.routes.business_site_public import _verify_captcha

nonprofit_family_portal_api = Blueprint('nonprofit_family_portal_api', __name__, url_prefix='/nonprofit/family-portal')

CODE_TTL_MINUTES = 10
MAX_CODE_ATTEMPTS = 5
# Generic wording on purpose for both the "no family with that email"
# and the "we sent it" cases on request-code -- distinguishing them would
# let anyone probe which emails are on file for this organization.
GENERIC_SENT_MESSAGE = "If that email matches a family on file, we've sent a 6-digit code -- check your inbox."


def _find_family(business_id, email):
    email = (email or '').strip().lower()
    if not email:
        return None
    return NonprofitFamily.query.filter(
        NonprofitFamily.business_id == business_id,
        func.lower(NonprofitFamily.email) == email,
    ).first()


def _resend_configured():
    return bool(os.environ.get('RESEND_API_KEY') and os.environ.get('EMAIL_FROM'))


def _send_login_code_email(to_email, full_name, code, organization_name):
    """Best-effort, bilingual, same silent-skip-if-not-configured and
    never-raises convention as nonprofit_followups.py's
    _send_followup_email -- a family portal with no email delivery set up
    yet should fail the request cleanly (see request_code below), not
    crash."""
    if not _resend_configured():
        return False
    try:
        import resend
        resend.api_key = os.environ.get('RESEND_API_KEY')
        from_addr = os.environ.get('EMAIL_FROM')
        from_name = os.environ.get('EMAIL_FROM_NAME', organization_name or 'Gut Shtick')
        html = (
            f'<p>Hi {full_name},</p>'
            f'<p>Your code to view your family\'s info at {organization_name} is:</p>'
            f'<p style="font-size:28px;font-weight:bold;letter-spacing:4px;">{code}</p>'
            f'<p>This code expires in {CODE_TTL_MINUTES} minutes. If you didn\'t request this, you can ignore this email.</p>'
            f'<hr/>'
            f'<div dir="rtl">'
            f'<p>שלום {full_name},</p>'
            f'<p>הקוד שלך לצפייה בפרטי המשפחה שלך ב{organization_name} הוא:</p>'
            f'<p style="font-size:28px;font-weight:bold;letter-spacing:4px;">{code}</p>'
            f'<p>הקוד תקף ל-{CODE_TTL_MINUTES} דקות. אם לא ביקשת זאת, ניתן להתעלם מהודעה זו.</p>'
            f'</div>'
        )
        resend.Emails.send({
            'from': f'{from_name} <{from_addr}>', 'to': [to_email],
            'subject': f'Your {organization_name} login code / קוד הכניסה שלך',
            'html': html,
        })
        return True
    except Exception:
        return False


@nonprofit_family_portal_api.route('/<subdomain>/request-code', methods=['POST'])
def request_code(subdomain):
    site, business, _config = _site_and_business(subdomain)
    if not site:
        return jsonify({'message': 'Not found'}), 404

    throttled = _throttle_or_error()
    if throttled:
        return throttled

    body = request.get_json() or {}
    if not _verify_captcha(body.get('captcha_token'), request.remote_addr):
        return jsonify({'message': 'Please complete the verification challenge and try again'}), 400

    family = _find_family(business.id, body.get('email'))
    if family and family.email:
        if not _resend_configured():
            # Don't claim success if nothing can actually be sent -- this
            # is the one case worth telling the truth about, since a
            # family stuck here has no other way to reach their data.
            return jsonify({'message': 'Email delivery is not set up yet for this organization -- contact them directly.'}), 503
        code = f'{secrets.randbelow(1000000):06d}'
        db.session.add(NonprofitFamilyLoginCode(
            family_id=family.id,
            code_hash=generate_password_hash(code, method='pbkdf2:sha256'),
            expires_at=datetime.utcnow() + timedelta(minutes=CODE_TTL_MINUTES),
        ))
        db.session.commit()
        _send_login_code_email(family.email, family.full_name, code, business.name)

    return jsonify({'message': GENERIC_SENT_MESSAGE}), 200


@nonprofit_family_portal_api.route('/<subdomain>/verify-code', methods=['POST'])
def verify_code(subdomain):
    site, business, _config = _site_and_business(subdomain)
    if not site:
        return jsonify({'message': 'Not found'}), 404

    body = request.get_json() or {}
    family = _find_family(business.id, body.get('email'))
    code = (body.get('code') or '').strip()
    invalid = (jsonify({'message': 'That code is invalid or has expired -- request a new one.'}), 400)
    if not family or not code:
        return invalid

    code_row = (NonprofitFamilyLoginCode.query
                .filter_by(family_id=family.id, consumed_at=None)
                .order_by(NonprofitFamilyLoginCode.id.desc())
                .first())
    if not code_row or code_row.expires_at < datetime.utcnow() or code_row.attempts >= MAX_CODE_ATTEMPTS:
        return invalid
    if not check_password_hash(code_row.code_hash, code):
        code_row.attempts += 1
        db.session.commit()
        return invalid

    code_row.consumed_at = datetime.utcnow()
    db.session.commit()
    token = generate_family_token(family)
    return jsonify({'token': token, 'family': {'id': family.id, 'full_name': family.full_name}})


def _payable(type_label, row, amount_field):
    return {
        'type': type_label,
        'id': row.id,
        'reference_code': row.reference_code,
        'amount_cents': getattr(row, amount_field),
        'status': row.status,
        'created_at': row.created_at.isoformat() if row.created_at else None,
    }


def _seat_summary(s):
    """A plain {label: count} map a family member can read, from
    whichever shape this signup actually has -- tiered (seat_breakdown,
    resolved to each tier's current label) or legacy (men/women seats)."""
    if s.seat_breakdown:
        tiers_by_id = {t.id: t.label for t in s.holiday.tiers}
        return {tiers_by_id.get(int(tid), f'Tier #{tid}'): count for tid, count in s.seat_breakdown.items() if count}
    summary = {}
    if s.men_seats:
        summary['Men'] = s.men_seats
    if s.women_seats:
        summary['Women'] = s.women_seats
    return summary


def _serialize_bill(bill):
    data = _payable('holiday_seats', bill, 'total_cents')
    data['holidays'] = [
        {'name_en': s.holiday.name_en, 'name_he': s.holiday.name_he, 'seats': _seat_summary(s), 'total_cents': s.total_cents}
        for s in bill.line_items if not s.deleted_at
    ]
    return data


def _serialize_membership(m):
    data = _payable('membership', m, 'monthly_cents')
    data['tier'] = m.tier
    return data


def _serialize_payment_link(link):
    data = _payable('payment_link', link, 'amount_cents')
    data['label'] = link.label
    return data


def _serialize_donation(d):
    data = _payable('donation', d, 'amount_cents')
    data['purpose'] = d.purpose
    return data


def _serialize_external(ext):
    # Already a completed, successful transaction -- no status/reference
    # code/pay link, just a record of money received.
    return {
        'type': 'external_transaction', 'id': ext.id, 'amount_cents': ext.amount_cents,
        'description': ext.groupe or ext.comments, 'created_at': ext.received_at.isoformat() if ext.received_at else None,
    }


def _serialize_form_response(resp):
    labels = {str(f.id): (f.label if f.label else '') for f in resp.form.fields}
    answers = [{'label': labels.get(fid, fid), 'value': value} for fid, value in (resp.answers or {}).items()]
    return {
        'type': 'form_response', 'id': resp.id, 'form_title': resp.form.title,
        'answers': answers, 'created_at': resp.created_at.isoformat() if resp.created_at else None,
    }


@nonprofit_family_portal_api.route('/<subdomain>/me', methods=['GET'])
@family_required
def get_my_family(family, subdomain):
    site, business, _config = _site_and_business(subdomain)
    if not site or family.business_id != business.id:
        return jsonify({'message': 'Not found'}), 404

    bills = NonprofitBill.query.filter_by(family_id=family.id).order_by(NonprofitBill.created_at.desc()).all()
    donations = NonprofitDonation.query.filter_by(family_id=family.id).order_by(NonprofitDonation.created_at.desc()).all()
    memberships = NonprofitMembership.query.filter_by(family_id=family.id).order_by(NonprofitMembership.created_at.desc()).all()
    links = NonprofitPaymentLink.query.filter_by(family_id=family.id).order_by(NonprofitPaymentLink.created_at.desc()).all()
    externals = NonprofitExternalTransaction.query.filter_by(family_id=family.id).order_by(NonprofitExternalTransaction.received_at.desc()).all()
    responses = (NonprofitFormResponse.query
                 .filter_by(family_id=family.id, deleted_at=None)
                 .order_by(NonprofitFormResponse.created_at.desc()).all())

    return jsonify({
        'family': {
            'full_name': family.full_name, 'email': family.email, 'phone': family.phone,
            'address': family.address, 'city': family.city,
        },
        'organization_name': business.name,
        'records': (
            [_serialize_bill(b) for b in bills]
            + [_serialize_donation(d) for d in donations]
            + [_serialize_membership(m) for m in memberships]
            + [_serialize_payment_link(link) for link in links]
            + [_serialize_external(ext) for ext in externals]
        ),
        'form_responses': [_serialize_form_response(r) for r in responses],
    })
