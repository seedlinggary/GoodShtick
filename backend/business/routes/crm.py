"""The CRM view (Phase 6 of the site builder) is deliberately NOT backed
by its own customer table -- a "customer" here is just whoever shows up
as the identity on an Order, an Appointment, or a LoyaltyCard, all of
which already exist. This file only aggregates those by identity_key (see
customer_note.py) and layers the one genuinely new piece of data
(CustomerNote) on top.
"""
from flask import Blueprint, jsonify, request
from sqlalchemy import func

from config import db
from security import token_required
from backend.business.modals.business import Business
from backend.business.modals.commerce import Order
from backend.business.modals.booking import Appointment
from backend.business.modals.loyalty_card import LoyaltyCard
from backend.business.modals.customer_note import CustomerNote, identity_key
from backend.user.modals.user import User

crm_api = Blueprint('crm_api', __name__, url_prefix='/business')

NOTE_MAX = 2000


# TEMPORARY, prod-testing-only restriction -- see business_site.py's
# _can_manage for why (site builder is super-admin-only while testing on
# prod, not the usual is_boss-or-owner check).
def _can_manage(business, user):
    return bool(user and user.is_super_admin)


def _owned_business_or_error(business_id, user):
    business = db.session.get(Business, business_id)
    if not business:
        return None, (jsonify({'message': 'Business not found'}), 404)
    if not _can_manage(business, user):
        return None, (jsonify({'message': 'Not authorized'}), 403)
    return business, None


def _bump_activity(row, when):
    if when and (not row['last_activity_at'] or when > row['last_activity_at']):
        row['last_activity_at'] = when


@crm_api.route('/businesses/<int:business_id>/customers', methods=['GET'])
@token_required
def list_customers(current_user, business_id):
    business, err = _owned_business_or_error(business_id, current_user)
    if err:
        return err

    rows = {}

    def _row(key, label, email):
        if key not in rows:
            rows[key] = {
                'identity_key': key, 'label': label, 'email': email,
                'order_count': 0, 'total_spent_cents': 0,
                'appointment_count': 0, 'loyalty_stamps': 0,
                'notes_count': 0, 'last_activity_at': None,
            }
        return rows[key]

    for o in Order.query.filter_by(business_id=business.id).all():
        key = identity_key(o.customer_user_id, o.guest_email, o.guest_phone)
        row = _row(key, o.customer_label, o.customer.email if o.customer else o.guest_email)
        row['order_count'] += 1
        if o.status in ('paid', 'fulfilled'):
            row['total_spent_cents'] += o.total_cents
        _bump_activity(row, o.created_at)

    for a in Appointment.query.filter_by(business_id=business.id).all():
        key = identity_key(a.customer_user_id, a.guest_email, a.guest_phone)
        row = _row(key, a.customer_label, a.customer.email if a.customer else a.guest_email)
        row['appointment_count'] += 1
        _bump_activity(row, a.start_at)

    for lc in LoyaltyCard.query.filter_by(business_id=business.id).all():
        key = identity_key(lc.user_id, None, None)
        user = db.session.get(User, lc.user_id)
        row = _row(key, user.email if user else 'Unknown', user.email if user else None)
        row['loyalty_stamps'] = lc.stamps

    note_counts = dict(
        db.session.query(CustomerNote.identity_key, func.count(CustomerNote.id))
        .filter_by(business_id=business.id).group_by(CustomerNote.identity_key).all()
    )
    for key, count in note_counts.items():
        if key in rows:
            rows[key]['notes_count'] = count

    customers = sorted(rows.values(), key=lambda r: r['last_activity_at'] or '', reverse=True)
    for c in customers:
        c['last_activity_at'] = c['last_activity_at'].isoformat() if c['last_activity_at'] else None

    return jsonify({'customers': customers})


@crm_api.route('/businesses/<int:business_id>/customers/<identity>/notes', methods=['GET'])
@token_required
def list_customer_notes(current_user, business_id, identity):
    business, err = _owned_business_or_error(business_id, current_user)
    if err:
        return err
    notes = (CustomerNote.query.filter_by(business_id=business.id, identity_key=identity)
             .order_by(CustomerNote.created_at.desc()).all())
    return jsonify({'notes': [{'id': n.id, 'note': n.note, 'created_at': n.created_at.isoformat()} for n in notes]})


@crm_api.route('/businesses/<int:business_id>/customers/<identity>/notes', methods=['POST'])
@token_required
def add_customer_note(current_user, business_id, identity):
    business, err = _owned_business_or_error(business_id, current_user)
    if err:
        return err
    note_text = ((request.get_json() or {}).get('note') or '').strip()
    if not note_text or len(note_text) > NOTE_MAX:
        return jsonify({'message': f'note is required (max {NOTE_MAX} characters)'}), 400
    note = CustomerNote(business_id=business.id, identity_key=identity, note=note_text, created_by=current_user.public_id)
    db.session.add(note)
    db.session.commit()
    return jsonify({'id': note.id, 'note': note.note, 'created_at': note.created_at.isoformat()}), 201
