"""Staff-facing admin CRUD + actions for Donations, Memberships, and
Payment Links -- the three "payable" record types a donor/member pays
against (the fourth, holiday-seat Bills, lives in nonprofit_holidays.py
since it has its own line-item shape).

Mark-paid/cancel/reactivate are plain-staff actions. Freehand override of
a payment's recorded details, and any creation/cancellation of a Payment
Link, and any LIVE write against the real Nedarim Plus standing order
(amount/delete/disable/enable), are superadmin-only -- mirrors the ported
system's own role split exactly (see modals/nonprofit.py:NonprofitStaff's
docstring)."""
from datetime import datetime

from flask import Blueprint, jsonify, request

from config import db
from backend.business.modals.nonprofit import (
    NonprofitDonation, NonprofitMembership, NonprofitPaymentLink, NonprofitTransaction,
    NonprofitPaymentConfig,
)
from backend.business.nonprofit_auth import staff_required, superadmin_required
from backend.business.nonprofit_billid import new_reference_code
from backend.business.nonprofit_payments import nedarim_admin
from backend.business.routes.nonprofit_audit import diff_fields, record_audit_log
from backend.business.routes.nonprofit_import_helpers import csv_response

nonprofit_donations_api = Blueprint('nonprofit_donations_api', __name__, url_prefix='/nonprofit')


def _check_business(staff, business_id):
    if staff.business_id != business_id:
        return jsonify({'message': 'Not authorized for this organization'}), 403
    return None


def _serialize_donation(d):
    return {
        'id': d.id, 'reference_code': d.reference_code, 'full_name': d.full_name, 'email': d.email,
        'phone': d.phone, 'address': d.address, 'city': d.city, 'amount_cents': d.amount_cents,
        'purpose': d.purpose, 'status': d.status, 'created_by': d.created_by, 'family_id': d.family_id,
        'family_name': d.family.full_name if d.family else None,
        'created_at': d.created_at.isoformat() if d.created_at else None,
    }


def _serialize_membership(m):
    return {
        'id': m.id, 'reference_code': m.reference_code, 'full_name': m.full_name, 'email': m.email,
        'phone': m.phone, 'address': m.address, 'city': m.city, 'tier': m.tier,
        'monthly_cents': m.monthly_cents, 'monthly_is_estimated': m.monthly_is_estimated,
        'nedarim_payments_made': m.nedarim_payments_made, 'nedarim_payments_remaining': m.nedarim_payments_remaining,
        'nedarim_deleted_at': m.nedarim_deleted_at.isoformat() if m.nedarim_deleted_at else None,
        'nedarim_disabled_at': m.nedarim_disabled_at.isoformat() if m.nedarim_disabled_at else None,
        'keva_id': m.keva_id, 'status': m.status,
        'next_charge_date': m.next_charge_date.isoformat() if m.next_charge_date else None,
        'last_charge_at': m.last_charge_at.isoformat() if m.last_charge_at else None,
        'family_id': m.family_id, 'family_name': m.family.full_name if m.family else None,
        'created_at': m.created_at.isoformat() if m.created_at else None,
    }


def _serialize_link(p):
    return {
        'id': p.id, 'reference_code': p.reference_code, 'label': p.label, 'full_name': p.full_name,
        'phone': p.phone, 'email': p.email, 'amount_cents': p.amount_cents, 'status': p.status,
        'family_id': p.family_id, 'family_name': p.family.full_name if p.family else None,
        'created_at': p.created_at.isoformat() if p.created_at else None,
    }


# ── Donations ───────────────────────────────────────────────────────────

@nonprofit_donations_api.route('/businesses/<int:business_id>/donations', methods=['GET'])
@staff_required
def list_donations(staff, business_id):
    err = _check_business(staff, business_id)
    if err:
        return err
    rows = NonprofitDonation.query.filter_by(business_id=business_id).order_by(NonprofitDonation.created_at.desc()).all()
    return jsonify({'donations': [_serialize_donation(d) for d in rows]})


@nonprofit_donations_api.route('/businesses/<int:business_id>/donations/export', methods=['GET'])
@staff_required
def export_donations(staff, business_id):
    err = _check_business(staff, business_id)
    if err:
        return err
    rows = NonprofitDonation.query.filter_by(business_id=business_id).order_by(NonprofitDonation.created_at.desc()).all()
    header = ['Reference', 'Name', 'Email', 'Phone', 'Amount', 'Purpose', 'Status', 'Created']
    data = [[d.reference_code, d.full_name, d.email, d.phone or '', f'{d.amount_cents / 100:.2f}',
             d.purpose or '', d.status, d.created_at.isoformat() if d.created_at else ''] for d in rows]
    return csv_response(header, data, 'donations.csv')


@nonprofit_donations_api.route('/donations/<int:donation_id>', methods=['PATCH'])
@staff_required
def update_donation_status(staff, donation_id):
    donation = NonprofitDonation.query.get(donation_id)
    if not donation or donation.business_id != staff.business_id:
        return jsonify({'message': 'Donation not found'}), 404

    body = request.get_json() or {}
    action = body.get('action')
    before = donation.status
    if action == 'mark_paid':
        donation.status = 'paid'
    elif action == 'cancel':
        donation.status = 'cancelled'
    elif action == 'reactivate':
        donation.status = 'pending'
    else:
        return jsonify({'message': 'action must be one of mark_paid, cancel, reactivate'}), 400

    record_audit_log(donation.business_id, staff.email, f'donation_{action}', 'NonprofitDonation', donation.id,
                      diff_fields({'status': before}, {'status': donation.status}))
    db.session.commit()
    return jsonify(_serialize_donation(donation))


@nonprofit_donations_api.route('/donations/<int:donation_id>/override', methods=['PUT'])
@superadmin_required
def override_donation(staff, donation_id):
    donation = NonprofitDonation.query.get(donation_id)
    if not donation or donation.business_id != staff.business_id:
        return jsonify({'message': 'Donation not found'}), 404

    body = request.get_json() or {}
    before = _serialize_donation(donation)
    for field in ('full_name', 'email', 'phone', 'address', 'city', 'purpose'):
        if field in body:
            setattr(donation, field, body[field])
    if 'amount_cents' in body:
        try:
            donation.amount_cents = int(body['amount_cents'])
        except (TypeError, ValueError):
            return jsonify({'message': 'amount_cents must be an integer'}), 400

    after = _serialize_donation(donation)
    record_audit_log(donation.business_id, staff.email, 'donation_override', 'NonprofitDonation', donation.id,
                      diff_fields(before, after))
    db.session.commit()
    return jsonify(_serialize_donation(donation))


# ── Memberships ─────────────────────────────────────────────────────────

@nonprofit_donations_api.route('/businesses/<int:business_id>/memberships', methods=['GET'])
@staff_required
def list_memberships(staff, business_id):
    err = _check_business(staff, business_id)
    if err:
        return err
    rows = NonprofitMembership.query.filter_by(business_id=business_id).order_by(NonprofitMembership.created_at.desc()).all()
    return jsonify({'memberships': [_serialize_membership(m) for m in rows]})


@nonprofit_donations_api.route('/businesses/<int:business_id>/memberships/export', methods=['GET'])
@staff_required
def export_memberships(staff, business_id):
    err = _check_business(staff, business_id)
    if err:
        return err
    rows = NonprofitMembership.query.filter_by(business_id=business_id).order_by(NonprofitMembership.created_at.desc()).all()
    header = ['Reference', 'Name', 'Email', 'Tier', 'Monthly', 'Status', 'Next charge', 'Created']
    data = [[m.reference_code, m.full_name, m.email, m.tier, f'{m.monthly_cents / 100:.2f}', m.status,
             m.next_charge_date.isoformat() if m.next_charge_date else '', m.created_at.isoformat() if m.created_at else '']
            for m in rows]
    return csv_response(header, data, 'memberships.csv')


@nonprofit_donations_api.route('/memberships/<int:membership_id>', methods=['GET'])
@staff_required
def get_membership(staff, membership_id):
    membership = NonprofitMembership.query.get(membership_id)
    if not membership or membership.business_id != staff.business_id:
        return jsonify({'message': 'Membership not found'}), 404
    txns = NonprofitTransaction.query.filter_by(membership_id=membership.id).order_by(NonprofitTransaction.received_at.desc()).all()
    return jsonify({
        'membership': _serialize_membership(membership),
        'transactions': [{'id': t.id, 'amount_cents': t.amount_cents, 'amount_is_estimated': t.amount_is_estimated,
                           'received_at': t.received_at.isoformat() if t.received_at else None} for t in txns],
    })


@nonprofit_donations_api.route('/memberships/<int:membership_id>', methods=['PATCH'])
@staff_required
def update_membership_status(staff, membership_id):
    """Local-only status flip -- does NOT touch the real Nedarim Plus
    standing order (see the webhook's unexpected_charge_while_cancelled
    handling for why that distinction is load-bearing). Use the
    nedarim/* actions below to actually affect the live standing order."""
    membership = NonprofitMembership.query.get(membership_id)
    if not membership or membership.business_id != staff.business_id:
        return jsonify({'message': 'Membership not found'}), 404

    body = request.get_json() or {}
    action = body.get('action')
    before = membership.status
    if action == 'cancel':
        membership.status = 'cancelled'
    elif action == 'reactivate':
        membership.status = 'active'
    else:
        return jsonify({'message': 'action must be one of cancel, reactivate'}), 400

    record_audit_log(membership.business_id, staff.email, f'membership_{action}', 'NonprofitMembership', membership.id,
                      diff_fields({'status': before}, {'status': membership.status}))
    db.session.commit()
    return jsonify(_serialize_membership(membership))


@nonprofit_donations_api.route('/memberships/<int:membership_id>/override', methods=['PUT'])
@superadmin_required
def override_membership(staff, membership_id):
    membership = NonprofitMembership.query.get(membership_id)
    if not membership or membership.business_id != staff.business_id:
        return jsonify({'message': 'Membership not found'}), 404

    body = request.get_json() or {}
    before = _serialize_membership(membership)
    for field in ('full_name', 'email', 'phone', 'address', 'city'):
        if field in body:
            setattr(membership, field, body[field])
    if 'tier' in body:
        # Not validated against the current tier list on purpose -- this
        # is a freehand staff override of an EXISTING record (same as
        # monthly_cents right below, which isn't cross-checked against
        # any tier's price either), and may need to record a tier that
        # has since been renamed or archived for historical accuracy.
        tier = (body['tier'] or '').strip()
        if not tier:
            return jsonify({'message': 'tier cannot be empty'}), 400
        membership.tier = tier
    if 'monthly_cents' in body:
        try:
            membership.monthly_cents = int(body['monthly_cents'])
        except (TypeError, ValueError):
            return jsonify({'message': 'monthly_cents must be an integer'}), 400

    after = _serialize_membership(membership)
    record_audit_log(membership.business_id, staff.email, 'membership_override', 'NonprofitMembership', membership.id,
                      diff_fields(before, after))
    db.session.commit()
    return jsonify(_serialize_membership(membership))


def _require_config(business_id):
    config = NonprofitPaymentConfig.query.filter_by(business_id=business_id).first()
    if not config or not config.reports_configured:
        return None, (jsonify({'message': 'Nedarim Plus API credentials are not configured for live writes'}), 400)
    return config, None


@nonprofit_donations_api.route('/memberships/<int:membership_id>/nedarim/update-amount', methods=['POST'])
@superadmin_required
def nedarim_update_amount(staff, membership_id):
    """Genuinely still in testing, same caveat the ported system itself
    flags for this write path -- double-confirm this in the UI before
    calling it."""
    membership = NonprofitMembership.query.get(membership_id)
    if not membership or membership.business_id != staff.business_id or not membership.keva_id:
        return jsonify({'message': 'Membership (with a live standing order) not found'}), 404
    config, err = _require_config(membership.business_id)
    if err:
        return err

    body = request.get_json() or {}
    try:
        new_amount_cents = int(body.get('monthly_cents'))
    except (TypeError, ValueError):
        return jsonify({'message': 'monthly_cents is required'}), 400

    try:
        nedarim_admin.update_keva_amount(config, membership.keva_id, new_amount_cents)
    except nedarim_admin.NedarimAdminError as e:
        return jsonify({'message': str(e)}), 502

    before = membership.monthly_cents
    membership.monthly_cents = new_amount_cents
    record_audit_log(membership.business_id, staff.email, 'nedarim_update_keva_amount', 'NonprofitMembership', membership.id,
                      diff_fields({'monthly_cents': before}, {'monthly_cents': new_amount_cents}))
    db.session.commit()
    return jsonify(_serialize_membership(membership))


@nonprofit_donations_api.route('/memberships/<int:membership_id>/nedarim/delete', methods=['POST'])
@superadmin_required
def nedarim_delete(staff, membership_id):
    """PERMANENT on Nedarim Plus's side -- there is no undo."""
    membership = NonprofitMembership.query.get(membership_id)
    if not membership or membership.business_id != staff.business_id or not membership.keva_id:
        return jsonify({'message': 'Membership (with a live standing order) not found'}), 404
    config, err = _require_config(membership.business_id)
    if err:
        return err

    try:
        nedarim_admin.delete_keva(config, membership.keva_id)
    except nedarim_admin.NedarimAdminError as e:
        return jsonify({'message': str(e)}), 502

    membership.nedarim_deleted_at = datetime.utcnow()
    membership.status = 'cancelled'
    record_audit_log(membership.business_id, staff.email, 'nedarim_delete_keva', 'NonprofitMembership', membership.id,
                      {'nedarim_deleted_at': {'before': None, 'after': membership.nedarim_deleted_at.isoformat()}})
    db.session.commit()
    return jsonify(_serialize_membership(membership))


@nonprofit_donations_api.route('/memberships/<int:membership_id>/nedarim/disable', methods=['POST'])
@superadmin_required
def nedarim_disable(staff, membership_id):
    membership = NonprofitMembership.query.get(membership_id)
    if not membership or membership.business_id != staff.business_id or not membership.keva_id:
        return jsonify({'message': 'Membership (with a live standing order) not found'}), 404
    config, err = _require_config(membership.business_id)
    if err:
        return err

    try:
        nedarim_admin.disable_keva(config, membership.keva_id)
    except nedarim_admin.NedarimAdminError as e:
        return jsonify({'message': str(e)}), 502

    membership.nedarim_disabled_at = datetime.utcnow()
    record_audit_log(membership.business_id, staff.email, 'nedarim_disable_keva', 'NonprofitMembership', membership.id,
                      {'nedarim_disabled_at': {'before': None, 'after': membership.nedarim_disabled_at.isoformat()}})
    db.session.commit()
    return jsonify(_serialize_membership(membership))


@nonprofit_donations_api.route('/memberships/<int:membership_id>/nedarim/enable', methods=['POST'])
@superadmin_required
def nedarim_enable(staff, membership_id):
    membership = NonprofitMembership.query.get(membership_id)
    if not membership or membership.business_id != staff.business_id or not membership.keva_id:
        return jsonify({'message': 'Membership (with a live standing order) not found'}), 404
    config, err = _require_config(membership.business_id)
    if err:
        return err

    try:
        next_date = nedarim_admin.enable_keva(config, membership.keva_id)
    except nedarim_admin.NedarimAdminError as e:
        return jsonify({'message': str(e)}), 502

    membership.nedarim_disabled_at = None
    if next_date:
        membership.next_charge_date = next_date
    record_audit_log(membership.business_id, staff.email, 'nedarim_enable_keva', 'NonprofitMembership', membership.id,
                      {'nedarim_disabled_at': {'before': 'set', 'after': None}})
    db.session.commit()
    return jsonify(_serialize_membership(membership))


@nonprofit_donations_api.route('/businesses/<int:business_id>/nedarim/import-members', methods=['POST'])
@superadmin_required
def import_nedarim_members(staff, business_id):
    """Pulls pre-existing standing orders from Nedarim Plus (set up
    directly on their dashboard before this site existed) and backfills
    local Membership + Transaction rows, matched/deduped by keva_id and
    nedarim_transaction_id respectively -- safe to re-run repeatedly.
    Deliberately batched (BATCH_SIZE standing orders per call, driven by
    a "Continue Import" button client-side) -- a full run WILL get cut
    off by a serverless function's time limit after a few dozen members,
    same confirmed behavior as the ported system's own import."""
    err = _check_business(staff, business_id)
    if err:
        return err
    config, cfg_err = _require_config(business_id)
    if cfg_err:
        return cfg_err

    body = request.get_json() or {}
    last_id = body.get('last_id')
    batch_size = min(20, max(1, int(body.get('batch_size', 5))))

    try:
        rows = nedarim_admin.get_keva_history(config, last_id=last_id, max_id=2000)
    except nedarim_admin.NedarimAdminError as e:
        return jsonify({'message': str(e)}), 502

    if not isinstance(rows, list):
        rows = []
    batch = rows[:batch_size]
    imported, skipped = 0, 0

    for row in batch:
        keva_id = row.get('KevaId')
        if not keva_id:
            skipped += 1
            continue
        existing = NonprofitMembership.query.filter_by(business_id=business_id, keva_id=str(keva_id)).first()
        if existing:
            skipped += 1
            continue
        amount_cents = round((row.get('Amount') or 0) * 100) if isinstance(row.get('Amount'), (int, float)) else 0
        membership = NonprofitMembership(
            business_id=business_id, reference_code=new_reference_code(),
            full_name=row.get('ClientName') or 'Unknown', email=row.get('Mail') or '',
            tier='associate', monthly_cents=amount_cents or 10000, phone=row.get('Phone'),
            address=row.get('Adresse'), city=row.get('City'), status='active' if row.get('Enabled') else 'cancelled',
            created_by='nedarim-import',
        )
        membership.keva_id = str(keva_id)
        db.session.add(membership)
        imported += 1

    record_audit_log(business_id, staff.email, 'nedarim_import_members', 'NonprofitMembership', 0,
                      {'imported': {'before': None, 'after': imported}})
    db.session.commit()

    new_last_id = rows[-1].get('KevaId') if rows and len(rows) == len(batch) else (batch[-1].get('KevaId') if batch else last_id)
    return jsonify({'imported': imported, 'skipped': skipped, 'has_more': len(rows) > len(batch), 'last_id': new_last_id})


# ── Payment Links ───────────────────────────────────────────────────────

@nonprofit_donations_api.route('/businesses/<int:business_id>/payment-links', methods=['GET'])
@staff_required
def list_payment_links(staff, business_id):
    err = _check_business(staff, business_id)
    if err:
        return err
    rows = NonprofitPaymentLink.query.filter_by(business_id=business_id).order_by(NonprofitPaymentLink.created_at.desc()).all()
    return jsonify({'payment_links': [_serialize_link(p) for p in rows]})


@nonprofit_donations_api.route('/businesses/<int:business_id>/payment-links/export', methods=['GET'])
@staff_required
def export_payment_links(staff, business_id):
    err = _check_business(staff, business_id)
    if err:
        return err
    rows = NonprofitPaymentLink.query.filter_by(business_id=business_id).order_by(NonprofitPaymentLink.created_at.desc()).all()
    header = ['Reference', 'Label', 'Name', 'Amount', 'Status', 'Created']
    data = [[p.reference_code, p.label, p.full_name or '', f'{p.amount_cents / 100:.2f}', p.status,
             p.created_at.isoformat() if p.created_at else ''] for p in rows]
    return csv_response(header, data, 'payment-links.csv')


@nonprofit_donations_api.route('/businesses/<int:business_id>/payment-links', methods=['POST'])
@superadmin_required
def create_payment_link(staff, business_id):
    err = _check_business(staff, business_id)
    if err:
        return err

    body = request.get_json() or {}
    label = (body.get('label') or '').strip()
    full_name = (body.get('full_name') or '').strip() or None
    phone = (body.get('phone') or '').strip() or None
    email = (body.get('email') or '').strip().lower() or None
    try:
        amount_cents = int(body.get('amount_cents'))
    except (TypeError, ValueError):
        return jsonify({'message': 'amount_cents is required'}), 400
    if not label:
        return jsonify({'message': 'label is required'}), 400
    if amount_cents <= 0:
        return jsonify({'message': 'amount_cents must be greater than 0'}), 400

    link = NonprofitPaymentLink(
        business_id=business_id, reference_code=new_reference_code(), label=label,
        amount_cents=amount_cents, full_name=full_name, phone=phone, email=email,
    )
    db.session.add(link)
    db.session.flush()
    record_audit_log(business_id, staff.email, 'payment_link_create', 'NonprofitPaymentLink', link.id, None)
    db.session.commit()
    return jsonify(_serialize_link(link)), 201


@nonprofit_donations_api.route('/payment-links/<int:link_id>/override', methods=['PUT'])
@superadmin_required
def override_payment_link(staff, link_id):
    link = NonprofitPaymentLink.query.get(link_id)
    if not link or link.business_id != staff.business_id:
        return jsonify({'message': 'Payment link not found'}), 404

    body = request.get_json() or {}
    before = _serialize_link(link)
    for field in ('label', 'full_name', 'phone', 'email'):
        if field in body:
            setattr(link, field, body[field])
    if 'amount_cents' in body:
        try:
            link.amount_cents = int(body['amount_cents'])
        except (TypeError, ValueError):
            return jsonify({'message': 'amount_cents must be an integer'}), 400

    after = _serialize_link(link)
    record_audit_log(link.business_id, staff.email, 'payment_link_override', 'NonprofitPaymentLink', link.id,
                      diff_fields(before, after))
    db.session.commit()
    return jsonify(_serialize_link(link))


@nonprofit_donations_api.route('/payment-links/<int:link_id>/cancel', methods=['POST'])
@superadmin_required
def cancel_payment_link(staff, link_id):
    link = NonprofitPaymentLink.query.get(link_id)
    if not link or link.business_id != staff.business_id:
        return jsonify({'message': 'Payment link not found'}), 404
    before = link.status
    link.status = 'cancelled'
    record_audit_log(link.business_id, staff.email, 'payment_link_cancel', 'NonprofitPaymentLink', link.id,
                      diff_fields({'status': before}, {'status': 'cancelled'}))
    db.session.commit()
    return jsonify(_serialize_link(link))
