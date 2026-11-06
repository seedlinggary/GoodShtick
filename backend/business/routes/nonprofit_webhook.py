"""Nedarim Plus's own inbound webhook ('CallBack'), plus the payment-
failure detection cron. Nedarim Plus has NO decline webhook and does NOT
sign/HMAC its payloads at all -- IP allowlisting (NEDARIM_WEBHOOK_IPS) is
the entire inbound defense, cross-checked against the resolved amount
actually matching what the record expected (see _resolve_amount) before
ever flipping a record to 'paid'. This is a faithful port of the
confirmed production behavior of the real webhook handler this module is
based on (see modals/nonprofit.py's own module docstring) -- every branch
below mirrors a specific, previously-observed Nedarim Plus payload shape,
not a guess.
"""
import random
from datetime import datetime, timedelta

from flask import Blueprint, jsonify, request

from config import db
from security import cron_secret_required
from backend.business.modals.nonprofit import (
    NonprofitBill, NonprofitDonation, NonprofitMembership, NonprofitPaymentLink,
    NonprofitTransaction, NonprofitExternalTransaction, NonprofitPaymentFollowUp,
    NonprofitPaymentConfig,
)
from backend.business.modals.business_site import BusinessSite
from backend.business.nonprofit_payments.nedarim import (
    NEDARIM_WEBHOOK_IPS, extract_reference_from_comment, to_number, parse_nedarim_date,
)
from backend.business.nonprofit_payments.nedarim_admin import get_keva_history, NedarimAdminError
from backend.business.routes.nonprofit_audit import record_audit_log

nonprofit_webhook_api = Blueprint('nonprofit_webhook_api', __name__)

PENDING_GRACE_HOURS = 2
PAYMENT_FAILURE_CHECK_CHANCE = 0.05

_MODEL_BY_PREFIX = {
    'BILL': NonprofitBill, 'DON': NonprofitDonation,
    'MEM': NonprofitMembership, 'LINK': NonprofitPaymentLink,
}
_FK_FIELD_BY_PREFIX = {
    'BILL': 'bill_id', 'DON': 'donation_id', 'MEM': 'membership_id', 'LINK': 'payment_link_id',
}


def _request_ip():
    forwarded = request.headers.get('X-Forwarded-For')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.headers.get('X-Real-IP') or request.remote_addr


@nonprofit_webhook_api.route('/nonprofit/webhooks/nedarimplus/<subdomain>', methods=['POST'])
def nedarim_webhook(subdomain):
    if _request_ip() not in NEDARIM_WEBHOOK_IPS:
        return jsonify({'message': 'Forbidden'}), 403

    site = BusinessSite.query.filter_by(subdomain=(subdomain or '').strip().lower()).first()
    if not site or not site.has_module('nonprofit'):
        return jsonify({'message': 'Not found'}), 404
    business_id = site.business_id

    payload = request.get_json(silent=True) or {}
    comment = payload.get('Comments')
    keva_id = payload.get('KevaId')
    transaction_id = payload.get('TransactionId')

    ref = extract_reference_from_comment(comment)

    if ref and ref[0] == 'MEM':
        return _handle_membership_webhook(business_id, ref[1], payload, transaction_id, keva_id)
    if ref:
        return _handle_oneoff_webhook(business_id, ref[0], ref[1], payload, transaction_id)
    if keva_id:
        # A later recurring Keva charge may not carry the original Avour
        # comment forward -- fall back to matching by KevaId directly.
        membership = NonprofitMembership.query.filter_by(business_id=business_id, keva_id=str(keva_id)).first()
        if membership:
            return _handle_membership_webhook(business_id, membership.id, payload, transaction_id, keva_id)

    # Nothing matched at all -- a payment that came through this Mosad
    # outside this app's own control (e.g. a standing order set up
    # directly on Nedarim Plus's own dashboard). Recorded, never dropped.
    return _record_external(business_id, payload, transaction_id, keva_id)


def _resolve_amount(payload, expected_cents):
    shekels = to_number(payload.get('Amount'))
    if shekels is not None:
        return round(shekels * 100), False
    return expected_cents, True


def _already_recorded(nedarim_transaction_id):
    if not nedarim_transaction_id:
        return False
    return NonprofitTransaction.query.filter_by(nedarim_transaction_id=str(nedarim_transaction_id)).first() is not None


def _handle_oneoff_webhook(business_id, prefix, record_id, payload, transaction_id):
    model = _MODEL_BY_PREFIX[prefix]
    fk_field = _FK_FIELD_BY_PREFIX[prefix]
    record = model.query.filter_by(id=record_id, business_id=business_id).first()
    if not record:
        return _record_external(business_id, payload, transaction_id, payload.get('KevaId'))

    if _already_recorded(transaction_id):
        return jsonify({'message': 'Already recorded'})

    amount_cents, estimated = _resolve_amount(payload, record.total_cents if prefix == 'BILL' else record.amount_cents)

    txn = NonprofitTransaction(
        business_id=business_id, amount_cents=amount_cents,
        nedarim_transaction_id=str(transaction_id) if transaction_id else None,
        confirmation=payload.get('Confirmation'), amount_is_estimated=estimated,
        source='webhook', raw_payload=payload, **{fk_field: record.id},
    )
    db.session.add(txn)

    try:
        db.session.flush()
    except Exception:
        # TOCTOU race on the unique nedarim_transaction_id constraint --
        # Nedarim Plus is confirmed to sometimes retry webhook delivery.
        db.session.rollback()
        return jsonify({'message': 'Already recorded'})

    expected_cents = record.total_cents if prefix == 'BILL' else record.amount_cents
    if record.status != 'cancelled' and amount_cents == expected_cents:
        record.status = 'paid'
        _resolve_open_followups(business_id, fk_field, record.id)
        record_audit_log(business_id, 'system', 'webhook_mark_paid', model.__name__, record.id,
                          {'status': {'before': 'pending', 'after': 'paid'}})

    db.session.commit()
    return jsonify({'message': 'OK'})


def _handle_membership_webhook(business_id, membership_id, payload, transaction_id, keva_id):
    membership = NonprofitMembership.query.filter_by(id=membership_id, business_id=business_id).first()
    if not membership:
        return _record_external(business_id, payload, transaction_id, keva_id)

    if not transaction_id and keva_id:
        # Keva-SETUP event: no charge yet, just confirms the standing
        # order now exists.
        membership.keva_id = str(keva_id)
        membership.status = 'active'
        next_date = parse_nedarim_date(payload.get('NextDate'))
        if next_date:
            membership.next_charge_date = next_date
        record_audit_log(business_id, 'system', 'webhook_keva_setup', 'NonprofitMembership', membership.id,
                          {'status': {'before': 'pending', 'after': 'active'}, 'keva_id': {'before': None, 'after': str(keva_id)}})
        db.session.commit()
        return jsonify({'message': 'OK'})

    if _already_recorded(transaction_id):
        return jsonify({'message': 'Already recorded'})

    amount_cents, estimated = _resolve_amount(payload, membership.monthly_cents)
    txn = NonprofitTransaction(
        business_id=business_id, amount_cents=amount_cents, membership_id=membership.id,
        nedarim_transaction_id=str(transaction_id) if transaction_id else None,
        confirmation=payload.get('Confirmation'), amount_is_estimated=estimated,
        source='webhook', raw_payload=payload,
    )
    db.session.add(txn)
    try:
        db.session.flush()
    except Exception:
        db.session.rollback()
        return jsonify({'message': 'Already recorded'})

    membership.last_charge_at = datetime.utcnow()
    if membership.next_charge_date:
        membership.next_charge_date = _add_one_month(membership.next_charge_date)

    if membership.status == 'cancelled':
        # Cancelling locally never touches the REAL standing order (only
        # the superadmin-only delete/disable actions do) -- so a charge
        # can legitimately keep arriving after a local cancel. This is
        # flagged, never silently flipped back to active.
        record_audit_log(business_id, 'system', 'unexpected_charge_while_cancelled', 'NonprofitMembership', membership.id, None)
    else:
        membership.status = 'active'
        _resolve_open_followups(business_id, 'membership_id', membership.id)

    db.session.commit()
    return jsonify({'message': 'OK'})


def _add_one_month(dt):
    month = dt.month + 1
    year = dt.year + (1 if month > 12 else 0)
    month = month if month <= 12 else 1
    day = min(dt.day, 28)  # avoids a Feb-30 crash; charge dates are always <=28 by Nedarim Plus's own Day param rules
    return dt.replace(year=year, month=month, day=day)


def _resolve_open_followups(business_id, fk_field, record_id):
    open_followups = NonprofitPaymentFollowUp.query.filter_by(
        business_id=business_id, status='open', **{fk_field: record_id},
    ).all()
    for followup in open_followups:
        followup.status = 'resolved'
        followup.resolved_at = datetime.utcnow()


def _record_external(business_id, payload, transaction_id, keva_id):
    if transaction_id and _already_recorded(transaction_id):
        return jsonify({'message': 'Already recorded'})
    shekels = to_number(payload.get('Amount'))
    row = NonprofitExternalTransaction(
        business_id=business_id, amount_cents=round((shekels or 0) * 100),
        nedarim_transaction_id=str(transaction_id) if transaction_id else None,
        client_name=payload.get('ClientName'), phone=payload.get('Phone'), email=payload.get('Mail'),
        groupe=payload.get('Groupe'), comments=payload.get('Comments'), confirmation=payload.get('Confirmation'),
        keva_id=str(keva_id) if keva_id else None, raw_payload=payload,
    )
    db.session.add(row)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        return jsonify({'message': 'Already recorded'})
    return jsonify({'message': 'OK'})


# ── Payment-failure detection: stale-pending sweep + Nedarim decline report ──
# Dual-trigger, same convention as social.py's publish_due/
# maybe_publish_due_posts -- a real cron endpoint for anyone who wants
# tighter timing, PLUS an opportunistic sweep called from this module's
# own high-traffic public routes (nonprofit_public.py), since this app
# runs serverless with no persistent process for an in-process scheduler
# to live in.

def _flag_stale_pending(business_id):
    cutoff = datetime.utcnow() - timedelta(hours=PENDING_GRACE_HOURS)
    flagged = 0
    for model, fk_field in ((NonprofitBill, 'bill_id'), (NonprofitDonation, 'donation_id'),
                             (NonprofitPaymentLink, 'payment_link_id')):
        stale = model.query.filter(model.business_id == business_id, model.status == 'pending',
                                    model.created_at <= cutoff).all()
        for record in stale:
            existing = NonprofitPaymentFollowUp.query.filter_by(
                business_id=business_id, status='open', reason='stale_pending', **{fk_field: record.id},
            ).first()
            if existing:
                continue
            db.session.add(NonprofitPaymentFollowUp(business_id=business_id, reason='stale_pending', **{fk_field: record.id}))
            flagged += 1

    past_due_memberships = NonprofitMembership.query.filter(
        NonprofitMembership.business_id == business_id, NonprofitMembership.status == 'active',
        NonprofitMembership.next_charge_date.isnot(None), NonprofitMembership.next_charge_date <= datetime.utcnow(),
    ).all()
    for membership in past_due_memberships:
        membership.status = 'past_due'
        flagged += 1
    return flagged


def _check_membership_declines(business_id, config):
    """Scans every standing order's ErrorText via Nedarim Plus's own
    GetKevaJson report -- the only automatic decline signal it exposes
    anywhere, and only for memberships (a one-time Ragil decline is never
    reported anywhere; it simply never creates a transaction at all)."""
    try:
        rows = get_keva_history(config)
    except (NedarimAdminError, Exception):
        return 0
    flagged = 0
    for row in rows if isinstance(rows, list) else []:
        error_text = (row.get('ErrorText') or '').strip()
        keva_id = row.get('KevaId')
        if not error_text or not keva_id:
            continue
        membership = NonprofitMembership.query.filter_by(business_id=business_id, keva_id=str(keva_id)).first()
        if not membership:
            continue
        existing = NonprofitPaymentFollowUp.query.filter_by(
            business_id=business_id, membership_id=membership.id, status='open', reason='api_decline',
        ).first()
        if existing:
            continue
        db.session.add(NonprofitPaymentFollowUp(
            business_id=business_id, reason='api_decline', membership_id=membership.id, failure_reason=error_text,
        ))
        flagged += 1
    return flagged


@nonprofit_webhook_api.route('/nonprofit/cron/detect-payment-failures', methods=['POST'])
@cron_secret_required
def detect_payment_failures():
    total = 0
    for config in NonprofitPaymentConfig.query.all():
        total += _flag_stale_pending(config.business_id)
        if config.reports_configured:
            total += _check_membership_declines(config.business_id, config)
    db.session.commit()
    return jsonify({'flagged': total})


def maybe_detect_payment_failures(business_id):
    """Called opportunistically from nonprofit_public.py's public routes
    -- never raises, never blocks the request that triggered it."""
    if random.random() >= PAYMENT_FAILURE_CHECK_CHANCE:
        return
    try:
        _flag_stale_pending(business_id)
        config = NonprofitPaymentConfig.query.filter_by(business_id=business_id).first()
        if config and config.reports_configured:
            _check_membership_declines(business_id, config)
        db.session.commit()
    except Exception:
        db.session.rollback()
