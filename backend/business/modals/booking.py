from config import db
from datetime import datetime

APPOINTMENT_STATUSES = ('scheduled', 'completed', 'canceled', 'no_show')
RECURRENCE_TYPES = ('daily', 'weekly', 'biweekly', 'monthly')


class ServiceType(db.Model):
    """A bookable service a business offers (e.g. "Haircut", "60-min
    tutoring session"). Ported from the reference billing app's own
    ServiceType, generalized from therapist to business."""
    __tablename__ = 'service_type'

    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(db.Integer, db.ForeignKey('business.id'), nullable=False, index=True)

    name = db.Column(db.String(128), nullable=False)
    duration_minutes = db.Column(db.Integer, nullable=False, default=30, server_default='30')
    # NULL = price on request -- not every bookable service has to be
    # prepaid online (a consultation call, say); booking still works, it
    # just never reaches the checkout step.
    price_cents = db.Column(db.Integer, nullable=True)

    active = db.Column(db.Boolean, nullable=False, default=True, server_default='true', index=True)
    position = db.Column(db.Integer, nullable=False, default=0, server_default='0')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    business = db.relationship('Business', backref=db.backref('service_types', lazy=True, cascade='all, delete-orphan'))

    def __init__(self, business_id, name, duration_minutes=30, price_cents=None, active=True, position=0):
        self.business_id = business_id
        self.name = name
        self.duration_minutes = duration_minutes
        self.price_cents = price_cents
        self.active = active
        self.position = position

    def __repr__(self):
        return f'ServiceType({self.id}) business={self.business_id} {self.name!r}'


class AvailabilityRule(db.Model):
    """A recurring weekly open-hours window the owner defines themselves
    -- genuinely new vs. the reference app, which assumed an externally
    fixed schedule (a therapist's existing practice hours); self-serve
    booking needs the business to say when it's open at all.

    weekday follows Python's date.weekday() convention: 0=Monday .. 6=Sunday.
    service_type_id NULL means the window applies to every service.
    Conflict-checking for slot generation is GLOBAL per business (any
    existing Appointment blocks a slot regardless of which service it's
    for) -- the right assumption for a small/solo operator with one
    calendar, not one per service."""
    __tablename__ = 'availability_rule'

    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(db.Integer, db.ForeignKey('business.id'), nullable=False, index=True)
    service_type_id = db.Column(db.Integer, db.ForeignKey('service_type.id'), nullable=True, index=True)

    weekday = db.Column(db.Integer, nullable=False)
    start_time = db.Column(db.Time, nullable=False)
    end_time = db.Column(db.Time, nullable=False)
    slot_interval_minutes = db.Column(db.Integer, nullable=False, default=30, server_default='30')

    business = db.relationship('Business', backref=db.backref('availability_rules', lazy=True, cascade='all, delete-orphan'))
    service_type = db.relationship('ServiceType')

    def __init__(self, business_id, weekday, start_time, end_time, service_type_id=None, slot_interval_minutes=30):
        self.business_id = business_id
        self.weekday = weekday
        self.start_time = start_time
        self.end_time = end_time
        self.service_type_id = service_type_id
        self.slot_interval_minutes = slot_interval_minutes

    def __repr__(self):
        return f'AvailabilityRule({self.id}) business={self.business_id} weekday={self.weekday}'


class RecurrenceRule(db.Model):
    """Template for auto-generating future Appointments -- ported near-
    verbatim from the reference app's recurrence_rule.py, with the
    customer identity fields added (that app's recurrence was set up BY
    the therapist FOR a known client; here a customer sets up their own
    recurring booking through the public widget, so there's no existing
    "whose recurrence is this" owner-side record to attach to)."""
    __tablename__ = 'recurrence_rule'

    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(db.Integer, db.ForeignKey('business.id'), nullable=False, index=True)
    service_type_id = db.Column(db.Integer, db.ForeignKey('service_type.id'), nullable=False, index=True)

    customer_user_id = db.Column(db.String(50), db.ForeignKey('user.public_id'), nullable=True)
    guest_email = db.Column(db.String(150), nullable=True)
    guest_phone = db.Column(db.String(40), nullable=True)

    recurrence_type = db.Column(db.String(16), nullable=False)
    interval = db.Column(db.Integer, nullable=False, default=1, server_default='1')
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=True)            # NULL if using occurrence_count
    occurrence_count = db.Column(db.Integer, nullable=True)  # NULL if using end_date

    # Template fields for each generated appointment.
    start_hour = db.Column(db.Integer, nullable=False)
    start_minute = db.Column(db.Integer, nullable=False, default=0)

    active = db.Column(db.Boolean, nullable=False, default=True, server_default='true', index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    business = db.relationship('Business', backref=db.backref('recurrence_rules', lazy=True, cascade='all, delete-orphan'))
    service_type = db.relationship('ServiceType')
    appointments = db.relationship('Appointment', backref='recurrence_rule', lazy=True)

    def __init__(self, business_id, service_type_id, recurrence_type, start_date, start_hour, start_minute=0,
                 interval=1, end_date=None, occurrence_count=None, customer_user_id=None,
                 guest_email=None, guest_phone=None):
        self.business_id = business_id
        self.service_type_id = service_type_id
        self.recurrence_type = recurrence_type
        self.start_date = start_date
        self.start_hour = start_hour
        self.start_minute = start_minute
        self.interval = interval
        self.end_date = end_date
        self.occurrence_count = occurrence_count
        self.customer_user_id = customer_user_id
        self.guest_email = guest_email
        self.guest_phone = guest_phone

    def __repr__(self):
        return f'RecurrenceRule({self.id}) business={self.business_id} [{self.recurrence_type}]'


class Appointment(db.Model):
    """One booked slot. Customer is either a real User or a guest, same
    no-account convention used across this feature (Order, SitePage's
    guest contact, etc). order_id is set once a paid booking's checkout
    completes (see routes/payments.py's webhook handler) -- a free/price-
    on-request service's appointment never gets one."""
    __tablename__ = 'appointment'

    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(db.Integer, db.ForeignKey('business.id'), nullable=False, index=True)
    service_type_id = db.Column(db.Integer, db.ForeignKey('service_type.id'), nullable=False, index=True)
    recurrence_id = db.Column(db.Integer, db.ForeignKey('recurrence_rule.id'), nullable=True, index=True)
    order_id = db.Column(db.Integer, db.ForeignKey('order.id'), nullable=True)

    customer_user_id = db.Column(db.String(50), db.ForeignKey('user.public_id'), nullable=True, index=True)
    guest_email = db.Column(db.String(150), nullable=True)
    guest_phone = db.Column(db.String(40), nullable=True)
    guest_manage_token = db.Column(db.String(64), nullable=True, unique=True, index=True)

    start_at = db.Column(db.DateTime, nullable=False, index=True)
    end_at = db.Column(db.DateTime, nullable=False)

    status = db.Column(db.String(20), nullable=False, default='scheduled', server_default='scheduled', index=True)
    override_price_cents = db.Column(db.Integer, nullable=True)
    notes = db.Column(db.Text, nullable=True)

    # Set once this appointment is pushed to the owner's connected Google
    # Calendar (see calendar/google.py) -- NULL for a business with no
    # CalendarAccount, or for an appointment that existed before this
    # feature. Lets update_appointment delete the right event on cancel.
    google_event_id = db.Column(db.String(255), nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    business = db.relationship('Business', backref=db.backref('appointments', lazy=True, cascade='all, delete-orphan'))
    service_type = db.relationship('ServiceType')
    customer = db.relationship('User', foreign_keys=[customer_user_id])
    order = db.relationship('Order')

    def __init__(self, business_id, service_type_id, start_at, end_at, customer_user_id=None,
                 guest_email=None, guest_phone=None, guest_manage_token=None,
                 recurrence_id=None, override_price_cents=None):
        self.business_id = business_id
        self.service_type_id = service_type_id
        self.start_at = start_at
        self.end_at = end_at
        self.customer_user_id = customer_user_id
        self.guest_email = guest_email
        self.guest_phone = guest_phone
        self.guest_manage_token = guest_manage_token
        self.recurrence_id = recurrence_id
        self.override_price_cents = override_price_cents

    @property
    def customer_label(self):
        if self.customer:
            return self.customer.email
        return self.guest_email or self.guest_phone or 'Unknown'

    def __repr__(self):
        return f'Appointment({self.id}) business={self.business_id} {self.start_at} [{self.status}]'
