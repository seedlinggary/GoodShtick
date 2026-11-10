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
from backend.business.modals.nonprofit import NonprofitHoliday, NonprofitHolidayTier, NonprofitBill, NonprofitSignup
from backend.business.nonprofit_auth import staff_required
from backend.business.nonprofit_billid import new_reference_code
from backend.business.routes.nonprofit_audit import diff_fields, record_audit_log
from backend.business.routes.nonprofit_import_helpers import csv_response

nonprofit_holidays_api = Blueprint('nonprofit_holidays_api', __name__, url_prefix='/nonprofit')


def _check_business(staff, business_id):
    if staff.business_id != business_id:
        return jsonify({'message': 'Not authorized for this organization'}), 403
    return None


def _legacy_price_for(holiday, is_member):
    """Only ever used for a signup with no `seat_breakdown` -- one
    created before this holiday had real tiers. A holiday created since
    has no member/non_member price columns set at all, so this is purely
    a read path for old data, never for pricing a new signup."""
    price = holiday.member_price_cents if is_member else holiday.non_member_price_cents
    return price or 0


def _serialize_holiday(h):
    return {
        'id': h.id, 'slug': h.slug, 'name_en': h.name_en, 'name_he': h.name_he,
        'description_en': h.description_en, 'description_he': h.description_he,
        'is_open': h.is_open,
        'tiers': [{'id': t.id, 'label': t.label, 'price_cents': t.price_cents, 'archived': bool(t.archived_at)} for t in h.tiers],
    }


def _serialize_signup(s):
    if s.seat_breakdown:
        tiers_by_id = {t.id: t for t in s.holiday.tiers}
        seats = [{'tier_id': int(tid), 'label': tiers_by_id[int(tid)].label if int(tid) in tiers_by_id else f'Tier #{tid}', 'count': count}
                  for tid, count in s.seat_breakdown.items() if count]
    else:
        seats = []
        if s.men_seats:
            seats.append({'label': 'Men', 'count': s.men_seats})
        if s.women_seats:
            seats.append({'label': 'Women', 'count': s.women_seats})
    return {
        'id': s.id, 'bill_id': s.bill_id, 'holiday_id': s.holiday_id,
        'seats': seats, 'total_cents': s.total_cents,
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
            'total_seats': sum(sum(s.seat_breakdown.values()) if s.seat_breakdown else (s.men_seats + s.women_seats) for s in signups),
            'paid_count': len(paid), 'pending_count': len(pending),
            'paid_revenue_cents': sum(s.total_cents for s in paid),
        })
    return jsonify({'stats': stats})


def _apply_tiers(holiday, tiers_in):
    """Full-list-replace, same reconciliation shape as the membership
    tiers endpoint (nonprofit_dashboard.py): each incoming item with an
    `id` matching one of this holiday's own tiers updates it in place;
    one with no `id` (or an id that isn't this holiday's) is created; any
    EXISTING tier not present in the incoming list gets archived rather
    than deleted, so a past signup's seat_breakdown (which stores tier
    ids) keeps resolving to a real label."""
    if not isinstance(tiers_in, list) or not tiers_in or len(tiers_in) > 20:
        return 'tiers must be a non-empty list of at most 20 items'
    existing_by_id = {t.id: t for t in holiday.tiers}
    seen_ids = set()
    for order, t in enumerate(tiers_in):
        if not isinstance(t, dict):
            return 'Each tier must be an object'
        label = (t.get('label') or '').strip()
        if not label:
            return 'Each tier needs a label'
        try:
            price_cents = int(t.get('price_cents'))
        except (TypeError, ValueError):
            return f'"{label}" needs a valid price'
        if price_cents <= 0:
            return f'"{label}" needs a price greater than 0'
        tier = existing_by_id.get(t.get('id'))
        if tier:
            tier.label, tier.price_cents, tier.order, tier.archived_at = label, price_cents, order, None
            seen_ids.add(tier.id)
        else:
            new_tier = NonprofitHolidayTier(holiday_id=holiday.id, label=label, price_cents=price_cents, order=order)
            db.session.add(new_tier)
    from datetime import datetime
    for tid, tier in existing_by_id.items():
        if tid not in seen_ids:
            tier.archived_at = datetime.utcnow()
    return None


@nonprofit_holidays_api.route('/businesses/<int:business_id>/holidays', methods=['POST'])
@staff_required
def create_holiday(staff, business_id):
    err = _check_business(staff, business_id)
    if err:
        return err
    body = request.get_json() or {}
    slug = (body.get('slug') or '').strip().lower()
    name_en = (body.get('name_en') or '').strip()
    if not slug or not name_en:
        return jsonify({'message': 'slug and name_en are required'}), 400
    if NonprofitHoliday.query.filter_by(business_id=business_id, slug=slug).first():
        return jsonify({'message': 'A holiday with that slug already exists'}), 409

    holiday = NonprofitHoliday(
        business_id=business_id, slug=slug, name_en=name_en, name_he=body.get('name_he'),
        description_en=body.get('description_en'), description_he=body.get('description_he'),
        is_open=bool(body.get('is_open', True)),
    )
    db.session.add(holiday)
    db.session.flush()

    tier_err = _apply_tiers(holiday, body.get('tiers') or [])
    if tier_err:
        db.session.rollback()
        return jsonify({'message': tier_err}), 400

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
    if 'tiers' in body:
        tier_err = _apply_tiers(holiday, body['tiers'])
        if tier_err:
            return jsonify({'message': tier_err}), 400
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
    # One column per tier this holiday has EVER had (active or archived,
    # in `holiday.tiers` order), so every row -- whichever tier set was
    # live when it was created -- lines up under the right column; plus
    # the legacy Men/Women columns for any signup from before tiers
    # existed (seat_breakdown is empty for those).
    tier_cols = [(t.id, t.label) for t in holiday.tiers]
    header = ['Name', 'Phone', 'Member'] + [label for _, label in tier_cols] + ['Men seats', 'Women seats', 'Total', 'Status']
    data = []
    for s in rows:
        breakdown = s.seat_breakdown or {}
        row = [s.bill.full_name, s.bill.phone, 'Yes' if s.bill.is_member else 'No']
        row += [breakdown.get(str(tid), 0) for tid, _ in tier_cols]
        row += [s.men_seats, s.women_seats, f'{s.total_cents / 100:.2f}', s.bill.status]
        data.append(row)
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
    items = body.get('items') or []  # [{holiday_id, seats: {tier_id: count}}]
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
        tiers_by_id = {t.id: t for t in holiday.tiers if not t.archived_at}
        breakdown = {}
        line_total = 0
        for tid_raw, count_raw in (item.get('seats') or {}).items():
            try:
                tid, count = int(tid_raw), max(0, int(count_raw or 0))
            except (TypeError, ValueError):
                continue
            tier = tiers_by_id.get(tid)
            if not tier or count <= 0:
                continue
            breakdown[str(tid)] = count
            line_total += tier.price_cents * count
        if line_total <= 0:
            continue
        db.session.add(NonprofitSignup(bill_id=bill.id, holiday_id=holiday.id, total_cents=line_total, seat_breakdown=breakdown))
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
        # Only a LEGACY signup (no seat_breakdown) needs re-pricing here --
        # its total still comes from the holiday's old fixed member/non-
        # member columns. A tiered signup's price is fixed by the tiers
        # the visitor actually picked, independent of is_member, so it's
        # left untouched.
        new_total = 0
        for signup in bill.line_items:
            if signup.deleted_at:
                continue
            if not signup.seat_breakdown:
                signup.total_cents = _legacy_price_for(signup.holiday, bill.is_member) * (signup.men_seats + signup.women_seats)
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

    if 'seats' in body:
        tiers_by_id = {t.id: t for t in signup.holiday.tiers if not t.archived_at}
        breakdown = {}
        total = 0
        for tid_raw, count_raw in (body['seats'] or {}).items():
            try:
                tid, count = int(tid_raw), max(0, int(count_raw or 0))
            except (TypeError, ValueError):
                continue
            tier = tiers_by_id.get(tid)
            if not tier or count <= 0:
                continue
            breakdown[str(tid)] = count
            total += tier.price_cents * count
        signup.seat_breakdown, signup.men_seats, signup.women_seats = breakdown, 0, 0
        signup.total_cents = total
        signup.bill.total_cents = sum(s.total_cents for s in signup.bill.line_items if not s.deleted_at)
    elif 'men_seats' in body or 'women_seats' in body:
        # Legacy-only edit path -- a signup that still has no
        # seat_breakdown at all (created before this holiday had tiers).
        men = int(body.get('men_seats', signup.men_seats))
        women = int(body.get('women_seats', signup.women_seats))
        signup.men_seats, signup.women_seats = men, women
        signup.total_cents = _legacy_price_for(signup.holiday, signup.bill.is_member) * (men + women)
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
