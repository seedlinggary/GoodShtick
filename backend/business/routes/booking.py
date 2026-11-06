"""Owner-facing service types, availability rules, and appointment list
(Phase 5 of the site builder). The public-facing half -- browsing open
slots and booking -- lives in business_site_public.py, same split this
feature already uses for pages (site_pages.py) and products (commerce.py).

Recurring-appointment generation reuses social.py's exact dual-trigger
pattern (a real cron endpoint + an opportunistic random-chance sweep from
a high-traffic route) -- NOT APScheduler/in-process cron, which would
silently do nothing on this serverless, pool_size=1 deployment.
"""
import calendar
import random
from datetime import date, datetime, time, timedelta

from flask import Blueprint, jsonify, request

from config import db
from security import token_required, cron_secret_required
from backend.business.modals.business import Business
from backend.business.modals.booking import ServiceType, AvailabilityRule, Appointment, RecurrenceRule
from backend.business.modals.commerce import Order

booking_api = Blueprint('booking_api', __name__, url_prefix='/business')

# Opportunistic trigger -- same reasoning/constant choice as social.py's
# PUBLISH_CHECK_CHANCE: converges on "checked roughly every N requests"
# without needing deploy-time cron config.
GENERATE_CHECK_CHANCE = 0.05
LOOKAHEAD_DAYS = 30
RULES_BATCH_LIMIT = 20
MAX_OCCURRENCES_PER_RULE = 500  # defensive cap, not a real-world limit

# How long a paid-service booking holds its slot while checkout is still
# pending, before the slot is freed back up for someone else. Closes a
# known gap from when Phase 5 first shipped: submit_booking_checkout (see
# business_site_public.py) reserves the Appointment row immediately, before
# payment completes, so an abandoned/failed Stripe Checkout used to hold
# that slot forever with no expiry.
BOOKING_PAYMENT_EXPIRY_MINUTES = 20
EXPIRE_BATCH_LIMIT = 50


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


# ── Service types ───────────────────────────────────────────────────────────

def _serialize_service(s):
    return {
        'id': s.id, 'business_id': s.business_id, 'name': s.name,
        'duration_minutes': s.duration_minutes, 'price_cents': s.price_cents, 'active': s.active,
    }


@booking_api.route('/businesses/<int:business_id>/service-types', methods=['GET'])
@token_required
def list_service_types(current_user, business_id):
    business, err = _owned_business_or_error(business_id, current_user)
    if err:
        return err
    rows = ServiceType.query.filter_by(business_id=business.id).order_by(ServiceType.position, ServiceType.id).all()
    return jsonify({'service_types': [_serialize_service(s) for s in rows]})


@booking_api.route('/businesses/<int:business_id>/service-types', methods=['POST'])
@token_required
def create_service_type(current_user, business_id):
    business, err = _owned_business_or_error(business_id, current_user)
    if err:
        return err
    body = request.get_json() or {}
    name = (body.get('name') or '').strip()
    if not name:
        return jsonify({'message': 'name is required'}), 400
    try:
        duration_minutes = int(body.get('duration_minutes') or 30)
    except (TypeError, ValueError):
        return jsonify({'message': 'duration_minutes must be a whole number'}), 400
    price_cents = body.get('price_cents')
    price_cents = int(price_cents) if price_cents not in (None, '') else None

    position = ServiceType.query.filter_by(business_id=business.id).count()
    service = ServiceType(business_id=business.id, name=name, duration_minutes=duration_minutes,
                           price_cents=price_cents, position=position)
    db.session.add(service)
    db.session.commit()
    return jsonify(_serialize_service(service)), 201


@booking_api.route('/service-types/<int:service_type_id>', methods=['PUT'])
@token_required
def update_service_type(current_user, service_type_id):
    service = db.session.get(ServiceType, service_type_id)
    if not service:
        return jsonify({'message': 'Service not found'}), 404
    _, err = _owned_business_or_error(service.business_id, current_user)
    if err:
        return err
    body = request.get_json() or {}
    if 'name' in body:
        name = (body['name'] or '').strip()
        if not name:
            return jsonify({'message': 'name cannot be empty'}), 400
        service.name = name
    if 'duration_minutes' in body:
        service.duration_minutes = int(body['duration_minutes'])
    if 'price_cents' in body:
        service.price_cents = int(body['price_cents']) if body['price_cents'] not in (None, '') else None
    if 'active' in body:
        service.active = bool(body['active'])
    db.session.commit()
    return jsonify(_serialize_service(service))


@booking_api.route('/service-types/<int:service_type_id>', methods=['DELETE'])
@token_required
def delete_service_type(current_user, service_type_id):
    service = db.session.get(ServiceType, service_type_id)
    if not service:
        return jsonify({'message': 'Service not found'}), 404
    _, err = _owned_business_or_error(service.business_id, current_user)
    if err:
        return err
    db.session.delete(service)
    db.session.commit()
    return jsonify({'message': 'Deleted'})


# ── Availability rules ──────────────────────────────────────────────────────

def _serialize_rule(r):
    return {
        'id': r.id, 'business_id': r.business_id, 'service_type_id': r.service_type_id,
        'weekday': r.weekday, 'start_time': r.start_time.strftime('%H:%M'),
        'end_time': r.end_time.strftime('%H:%M'), 'slot_interval_minutes': r.slot_interval_minutes,
    }


def _parse_time(value):
    return datetime.strptime(value, '%H:%M').time()


@booking_api.route('/businesses/<int:business_id>/availability-rules', methods=['GET'])
@token_required
def list_availability_rules(current_user, business_id):
    business, err = _owned_business_or_error(business_id, current_user)
    if err:
        return err
    rows = AvailabilityRule.query.filter_by(business_id=business.id).order_by(AvailabilityRule.weekday).all()
    return jsonify({'availability_rules': [_serialize_rule(r) for r in rows]})


@booking_api.route('/businesses/<int:business_id>/availability-rules', methods=['POST'])
@token_required
def create_availability_rule(current_user, business_id):
    business, err = _owned_business_or_error(business_id, current_user)
    if err:
        return err
    body = request.get_json() or {}
    try:
        weekday = int(body.get('weekday'))
        start_time = _parse_time(body.get('start_time'))
        end_time = _parse_time(body.get('end_time'))
    except (TypeError, ValueError):
        return jsonify({'message': 'weekday (0-6) and start_time/end_time (HH:MM) are required'}), 400
    if not 0 <= weekday <= 6:
        return jsonify({'message': 'weekday must be 0 (Monday) through 6 (Sunday)'}), 400
    if start_time >= end_time:
        return jsonify({'message': 'start_time must be before end_time'}), 400

    service_type_id = body.get('service_type_id') or None
    rule = AvailabilityRule(
        business_id=business.id, weekday=weekday, start_time=start_time, end_time=end_time,
        service_type_id=service_type_id, slot_interval_minutes=int(body.get('slot_interval_minutes') or 30),
    )
    db.session.add(rule)
    db.session.commit()
    return jsonify(_serialize_rule(rule)), 201


@booking_api.route('/availability-rules/<int:rule_id>', methods=['DELETE'])
@token_required
def delete_availability_rule(current_user, rule_id):
    rule = db.session.get(AvailabilityRule, rule_id)
    if not rule:
        return jsonify({'message': 'Rule not found'}), 404
    _, err = _owned_business_or_error(rule.business_id, current_user)
    if err:
        return err
    db.session.delete(rule)
    db.session.commit()
    return jsonify({'message': 'Deleted'})


# ── Appointments ─────────────────────────────────────────────────────────────

def _serialize_appointment(a):
    return {
        'id': a.id, 'service_type_id': a.service_type_id,
        'service_name': a.service_type.name if a.service_type else None,
        'customer_label': a.customer_label,
        'start_at': a.start_at.isoformat(), 'end_at': a.end_at.isoformat(),
        'status': a.status, 'notes': a.notes,
        'recurrence_id': a.recurrence_id,
    }


@booking_api.route('/businesses/<int:business_id>/appointments', methods=['GET'])
@token_required
def list_appointments(current_user, business_id):
    business, err = _owned_business_or_error(business_id, current_user)
    if err:
        return err
    rows = (Appointment.query.filter_by(business_id=business.id)
            .order_by(Appointment.start_at.desc()).limit(300).all())
    return jsonify({'appointments': [_serialize_appointment(a) for a in rows]})


@booking_api.route('/appointments/<int:appointment_id>', methods=['PATCH'])
@token_required
def update_appointment(current_user, appointment_id):
    appointment = db.session.get(Appointment, appointment_id)
    if not appointment:
        return jsonify({'message': 'Appointment not found'}), 404
    _, err = _owned_business_or_error(appointment.business_id, current_user)
    if err:
        return err
    body = request.get_json() or {}
    if 'status' in body:
        if body['status'] not in ('scheduled', 'completed', 'canceled', 'no_show'):
            return jsonify({'message': 'Invalid status'}), 400
        appointment.status = body['status']
    if 'notes' in body:
        appointment.notes = (body['notes'] or '').strip() or None
    db.session.commit()
    return jsonify(_serialize_appointment(appointment))


# ── Recurring-appointment generation ────────────────────────────────────────

def _add_months(d, months):
    month_index = d.month - 1 + months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _occurrence_dates(rule, horizon_date):
    """Every occurrence DATE for this rule from its own start_date up to
    horizon_date, honoring whichever of end_date/occurrence_count caps it
    first. Re-walks the rule's full history every call rather than
    tracking a separate "last generated" pointer -- simpler, and the
    caller's own exists-check (by recurrence_id + start_at) makes this
    safe to call repeatedly regardless."""
    dates = []
    current = rule.start_date
    count = 0
    while current <= horizon_date and count < MAX_OCCURRENCES_PER_RULE:
        if rule.end_date and current > rule.end_date:
            break
        if rule.occurrence_count and count >= rule.occurrence_count:
            break
        dates.append(current)
        count += 1
        if rule.recurrence_type == 'daily':
            current = current + timedelta(days=rule.interval)
        elif rule.recurrence_type == 'weekly':
            current = current + timedelta(weeks=rule.interval)
        elif rule.recurrence_type == 'biweekly':
            current = current + timedelta(weeks=2 * rule.interval)
        elif rule.recurrence_type == 'monthly':
            current = _add_months(current, rule.interval)
        else:
            break
    return dates


def _generate_due_recurrences():
    horizon = date.today() + timedelta(days=LOOKAHEAD_DAYS)
    rules = RecurrenceRule.query.filter_by(active=True).limit(RULES_BATCH_LIMIT).all()
    created = 0
    for rule in rules:
        service = db.session.get(ServiceType, rule.service_type_id)
        if not service or not service.active:
            continue
        for occ_date in _occurrence_dates(rule, horizon):
            start_at = datetime.combine(occ_date, time(rule.start_hour, rule.start_minute))
            if Appointment.query.filter_by(recurrence_id=rule.id, start_at=start_at).first():
                continue
            end_at = start_at + timedelta(minutes=service.duration_minutes)
            conflict = Appointment.query.filter(
                Appointment.business_id == rule.business_id, Appointment.status == 'scheduled',
                Appointment.start_at < end_at, Appointment.end_at > start_at,
            ).first()
            if conflict:
                continue
            db.session.add(Appointment(
                business_id=rule.business_id, service_type_id=service.id, start_at=start_at, end_at=end_at,
                customer_user_id=rule.customer_user_id, guest_email=rule.guest_email, guest_phone=rule.guest_phone,
                recurrence_id=rule.id,
            ))
            created += 1
    if created:
        db.session.commit()
    return created


def _expire_unpaid_appointments():
    """Frees a slot that's been sitting on an unpaid order too long --
    cancels both the Appointment and its Order so neither the public slot
    list nor the owner's Orders/Appointments views keep showing a booking
    that's never going to complete. Safe to run repeatedly: once an
    appointment is no longer 'scheduled' it's never matched again."""
    cutoff = datetime.utcnow() - timedelta(minutes=BOOKING_PAYMENT_EXPIRY_MINUTES)
    stale = (Appointment.query.join(Order, Appointment.order_id == Order.id)
             .filter(Appointment.status == 'scheduled', Order.status == 'pending', Order.created_at < cutoff)
             .limit(EXPIRE_BATCH_LIMIT).all())
    count = 0
    for appointment in stale:
        appointment.status = 'canceled'
        if appointment.order:
            appointment.order.status = 'cancelled'
        count += 1
    if count:
        db.session.commit()
    return count


@booking_api.route('/cron/generate-recurring-appointments', methods=['POST'])
@cron_secret_required
def generate_recurring_appointments_cron():
    """For anyone who wants tighter timing than the opportunistic sweep
    below -- point a real external scheduler at this with the
    X-Cron-Secret header set to CRON_SECRET, same as social.py's
    /social/cron/publish-due. Also expires stale unpaid-booking holds (see
    _expire_unpaid_appointments) -- bundled into this same endpoint/sweep
    rather than a separate one, since both are booking-table housekeeping
    triggered by the same schedule."""
    created = _generate_due_recurrences()
    expired = _expire_unpaid_appointments()
    return jsonify({'created': created, 'expired': expired})


def maybe_generate_recurring_appointments():
    """Called opportunistically from a high-traffic public route (see
    business.py's list_businesses, right alongside social.py's own
    maybe_publish_due_posts()) -- never raises, never blocks the request
    that triggered it."""
    if random.random() >= GENERATE_CHECK_CHANCE:
        return
    try:
        _generate_due_recurrences()
        _expire_unpaid_appointments()
    except Exception:
        db.session.rollback()
