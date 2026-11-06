"""Holiday/event seat sales -- Holiday CRUD, per-holiday stats, and the
admin-side Bill/Signup correction tools (manual signup entry for a cash/
in-person sale, paid/cancelled/reopened status, re-pricing a line item
when membership status changes).

Status lives on NonprofitBill, not NonprofitSignup, in the ported
schema -- a signup is purely a line item (seats + its own total). The
admin UI still offers "mark this signup paid/cancelled/reopened" per
line, since in practice an admin-created manual signup is almost always
its own single-line bill; those actions here act on signup.bill.status
accordingly. A bill with multiple holiday line items is still only ever
flipped as a whole (the public purchase flow locks the whole bill to one
payment, see nonprofit_public.py's submit_holiday_seats).
"""
from flask import Blueprint, jsonify, request

from config import db
from backend.business.modals.nonprofit import NonprofitHoliday, NonprofitBill, NonprofitSignup
from backend.business.nonprofit_auth import staff_required
from backend.business.nonprofit_billid import new_reference_code
from backend.business.routes.nonprofit_audit import diff_fields, record_audit_log
from backend.business.routes.nonprofit_import_helpers import csv_response

nonprofit_holidays_api = Blueprint('nonprofit_holidays_api', __name__, url_prefix='/nonprofit')


def _check_business(staff, business_id):
    if staff.business_id != business_id:
        return jsonify({'message': 'Not authorized for this organization'}), 403
    return None


def _serialize_holiday(h):
    return {
        'id': h.id, 'slug': h.slug, 'name_en': h.name_en, 'name_he': h.name_he,
        'description_en': h.description_en, 'description_he': h.description_he,
        'member_price_cents': h.member_price_cents, 'non_member_price_cents': h.non_member_price_cents,
        'is_open': h.is_open,
    }


def _serialize_signup(s):
    return {
        'id': s.id, 'bill_id': s.bill_id, 'holiday_id': s.holiday_id,
        'men_seats': s.men_seats, 'women_seats': s.women_seats, 'total_cents': s.total_cents,
        'bill_status': s.bill.status, 'full_name': s.bill.full_name, 'phone': s.bill.phone,
        'is_member': s.bill.is_member, 'reference_code': s.bill.reference_code,
        'family_id': s.bill.family_id, 'family_name': s.bill.family.full_name if s.bill.family else None,
    }


# ── Holidays ────────────────────────────────────────────────────────────

@nonprofit_holidays_api.route('/businesses/<int:business_id>/holidays', methods=['GET'])
@staff_required
def list_holidays(staff, business_id):
    err = _check_business(staff, business_id)
    if err:
        return err
    rows = NonprofitHoliday.query.filter_by(business_id=business_id).order_by(NonprofitHoliday.id).all()
    return jsonify({'holidays': [_serialize_holiday(h) for h in rows]})


@nonprofit_holidays_api.route('/businesses/<int:business_id>/holidays/stats', methods=['GET'])
@staff_required
def holiday_stats(staff, business_id):
    err = _check_business(staff, business_id)
    if err:
        return err
    rows = NonprofitHoliday.query.filter_by(business_id=business_id).order_by(NonprofitHoliday.id).all()
    stats = []
    for h in rows:
        signups = [s for s in h.signups if not s.deleted_at]
        paid = [s for s in signups if s.bill.status == 'paid']
        pending = [s for s in signups if s.bill.status == 'pending']
        stats.append({
            'holiday': _serialize_holiday(h),
            'total_seats': sum(s.men_seats + s.women_seats for s in signups),
            'paid_count': len(paid), 'pending_count': len(pending),
            'paid_revenue_cents': sum(s.total_cents for s in paid),
        })
    return jsonify({'stats': stats})


@nonprofit_holidays_api.route('/businesses/<int:business_id>/holidays', methods=['POST'])
@staff_required
def create_holiday(staff, business_id):
    err = _check_business(staff, business_id)
    if err:
        return err
    body = request.get_json() or {}
    slug = (body.get('slug') or '').strip().lower()
    name_en = (body.get('name_en') or '').strip()
    try:
        member_price_cents = int(body.get('member_price_cents'))
        non_member_price_cents = int(body.get('non_member_price_cents'))
    except (TypeError, ValueError):
        return jsonify({'message': 'member_price_cents and non_member_price_cents are required'}), 400
    if not slug or not name_en:
        return jsonify({'message': 'slug and name_en are required'}), 400
    if NonprofitHoliday.query.filter_by(business_id=business_id, slug=slug).first():
        return jsonify({'message': 'A holiday with that slug already exists'}), 409

    holiday = NonprofitHoliday(
        business_id=business_id, slug=slug, name_en=name_en, member_price_cents=member_price_cents,
        non_member_price_cents=non_member_price_cents, name_he=body.get('name_he'),
        description_en=body.get('description_en'), description_he=body.get('description_he'),
        is_open=bool(body.get('is_open', True)),
    )
    db.session.add(holiday)
    db.session.flush()
    record_audit_log(business_id, staff.email, 'holiday_create', 'NonprofitHoliday', holiday.id, None)
    db.session.commit()
    return jsonify(_serialize_holiday(holiday)), 201


@nonprofit_holidays_api.route('/holidays/<int:holiday_id>', methods=['PATCH'])
@staff_required
def update_holiday(staff, holiday_id):
    holiday = NonprofitHoliday.query.get(holiday_id)
    if not holiday or holiday.business_id != staff.business_id:
        return jsonify({'message': 'Holiday not found'}), 404
    body = request.get_json() or {}
    before = _serialize_holiday(holiday)
    for field in ('name_en', 'name_he', 'description_en', 'description_he'):
        if field in body:
            setattr(holiday, field, body[field])
    for field in ('member_price_cents', 'non_member_price_cents'):
        if field in body:
            try:
                setattr(holiday, field, int(body[field]))
            except (TypeError, ValueError):
                return jsonify({'message': f'{field} must be an integer'}), 400
    if 'is_open' in body:
        holiday.is_open = bool(body['is_open'])
    after = _serialize_holiday(holiday)
    record_audit_log(holiday.business_id, staff.email, 'holiday_update', 'NonprofitHoliday', holiday.id, diff_fields(before, after))
    db.session.commit()
    return jsonify(after)


# ── Bills / Signups ─────────────────────────────────────────────────────

@nonprofit_holidays_api.route('/holidays/<int:holiday_id>/signups', methods=['GET'])
@staff_required
def list_signups(staff, holiday_id):
    holiday = NonprofitHoliday.query.get(holiday_id)
    if not holiday or holiday.business_id != staff.business_id:
        return jsonify({'message': 'Holiday not found'}), 404
    rows = NonprofitSignup.query.filter_by(holiday_id=holiday_id, deleted_at=None).all()
    return jsonify({'signups': [_serialize_signup(s) for s in rows]})


@nonprofit_holidays_api.route('/holidays/<int:holiday_id>/signups/export', methods=['GET'])
@staff_required
def export_signups(staff, holiday_id):
    holiday = NonprofitHoliday.query.get(holiday_id)
    if not holiday or holiday.business_id != staff.business_id:
        return jsonify({'message': 'Holiday not found'}), 404
    rows = NonprofitSignup.query.filter_by(holiday_id=holiday_id, deleted_at=None).all()
    header = ['Name', 'Phone', 'Member', 'Men seats', 'Women seats', 'Total', 'Status']
    data = [[s.bill.full_name, s.bill.phone, 'Yes' if s.bill.is_member else 'No', s.men_seats, s.women_seats,
             f'{s.total_cents / 100:.2f}', s.bill.status] for s in rows]
    return csv_response(header, data, f'{holiday.slug}-signups.csv')


@nonprofit_holidays_api.route('/businesses/<int:business_id>/holiday-bills', methods=['POST'])
@staff_required
def create_manual_bill(staff, business_id):
    """Admin-side manual signup entry -- e.g. a cash/in-person sale, or
    correcting what a congregant called in about. Creates a Bill (always
    status='pending' until a staff action below marks it paid) +
    its Signup line items, same shape the public flow produces."""
    err = _check_business(staff, business_id)
    if err:
        return err
    body = request.get_json() or {}
    full_name = (body.get('full_name') or '').strip()
    phone = (body.get('phone') or '').strip()
    is_member = bool(body.get('is_member'))
    items = body.get('items') or []
    if not full_name or not phone:
        return jsonify({'message': 'Name and phone are required'}), 400

    bill = NonprofitBill(
        business_id=business_id, reference_code=new_reference_code(), full_name=full_name, phone=phone,
        email=(body.get('email') or '').strip() or None, is_member=is_member,
        notes=(body.get('notes') or '').strip() or None, created_by=staff.email,
    )
    db.session.add(bill)
    db.session.flush()

    total_cents = 0
    for item in items:
        holiday = NonprofitHoliday.query.filter_by(id=item.get('holiday_id'), business_id=business_id).first()
        if not holiday:
            continue
        men, women = max(0, int(item.get('men_seats') or 0)), max(0, int(item.get('women_seats') or 0))
        if men + women <= 0:
            continue
        line_total = holiday.price_for(is_member) * (men + women)
        db.session.add(NonprofitSignup(bill_id=bill.id, holiday_id=holiday.id, men_seats=men, women_seats=women, total_cents=line_total))
        total_cents += line_total

    bill.total_cents = total_cents
    record_audit_log(business_id, staff.email, 'bill_create_manual', 'NonprofitBill', bill.id, None)
    db.session.commit()
    return jsonify({'bill_id': bill.id, 'reference_code': bill.reference_code, 'total_cents': total_cents}), 201


@nonprofit_holidays_api.route('/bills/<int:bill_id>', methods=['PATCH'])
@staff_required
def update_bill(staff, bill_id):
    """Changing is_member recomputes EVERY line item's total, since
    membership status is shared across the whole bill, not per line
    item -- this is the exact nuance the ported system calls out as a
    reason updateSignup touches more than just the one row being edited."""
    bill = NonprofitBill.query.get(bill_id)
    if not bill or bill.business_id != staff.business_id:
        return jsonify({'message': 'Bill not found'}), 404
    body = request.get_json() or {}
    before = {'status': bill.status, 'is_member': bill.is_member}

    if 'is_member' in body and bool(body['is_member']) != bill.is_member:
        bill.is_member = bool(body['is_member'])
        new_total = 0
        for signup in bill.line_items:
            if signup.deleted_at:
                continue
            signup.total_cents = signup.holiday.price_for(bill.is_member) * (signup.men_seats + signup.women_seats)
            new_total += signup.total_cents
        bill.total_cents = new_total

    if 'action' in body:
        action = body['action']
        if action == 'mark_paid':
            bill.status = 'paid'
        elif action == 'cancel':
            bill.status = 'cancelled'
        elif action == 'reopen':
            bill.status = 'pending'
        else:
            return jsonify({'message': 'action must be one of mark_paid, cancel, reopen'}), 400

    record_audit_log(bill.business_id, staff.email, 'bill_update', 'NonprofitBill', bill.id,
                      diff_fields(before, {'status': bill.status, 'is_member': bill.is_member}))
    db.session.commit()
    return jsonify({'id': bill.id, 'status': bill.status, 'is_member': bill.is_member, 'total_cents': bill.total_cents})


@nonprofit_holidays_api.route('/signups/<int:signup_id>', methods=['PATCH'])
@staff_required
def update_signup(staff, signup_id):
    signup = NonprofitSignup.query.get(signup_id)
    if not signup or signup.bill.business_id != staff.business_id:
        return jsonify({'message': 'Signup not found'}), 404
    body = request.get_json() or {}

    if 'men_seats' in body or 'women_seats' in body:
        men = int(body.get('men_seats', signup.men_seats))
        women = int(body.get('women_seats', signup.women_seats))
        signup.men_seats, signup.women_seats = men, women
        signup.total_cents = signup.holiday.price_for(signup.bill.is_member) * (men + women)
        signup.bill.total_cents = sum(s.total_cents for s in signup.bill.line_items if not s.deleted_at)

    action = body.get('action')
    if action == 'mark_paid':
        signup.bill.status = 'paid'
    elif action == 'cancel':
        signup.bill.status = 'cancelled'
    elif action == 'reopen':
        signup.bill.status = 'pending'

    record_audit_log(signup.bill.business_id, staff.email, 'signup_update', 'NonprofitSignup', signup.id, None)
    db.session.commit()
    return jsonify(_serialize_signup(signup))


@nonprofit_holidays_api.route('/signups/<int:signup_id>', methods=['DELETE'])
@staff_required
def delete_signup(staff, signup_id):
    """Soft delete only -- excluded from every view/total/export from
    here on, never hard-removed."""
    from datetime import datetime

    signup = NonprofitSignup.query.get(signup_id)
    if not signup or signup.bill.business_id != staff.business_id:
        return jsonify({'message': 'Signup not found'}), 404
    signup.deleted_at = datetime.utcnow()
    signup.bill.total_cents = sum(s.total_cents for s in signup.bill.line_items if not s.deleted_at)
    record_audit_log(signup.bill.business_id, staff.email, 'signup_delete', 'NonprofitSignup', signup.id, None)
    db.session.commit()
    return jsonify({'message': 'Deleted'})
