from config import db
from datetime import datetime

# Enforced at the Python level, not a DB enum -- same convention as
# PaymentAccount.PAYMENT_PROVIDERS. 'google' is the only one implemented.
CALENDAR_PROVIDERS = ('google',)

CALENDAR_ACCOUNT_STATUSES = ('active', 'disabled')


class CalendarAccount(db.Model):
    """One connected calendar per business -- what a confirmed booking (see
    routes/business_site_public.py's submit_booking_checkout and
    routes/payments.py's _mark_order_paid) gets pushed to, and what
    get_booking_slots checks for busy time on top of this platform's own
    Appointment rows. Tokens are stored encrypted at rest, same Fernet
    helpers social/crypto.py already provides (generic, not social-specific)
    -- unlike PaymentAccount (a one-time Stripe Connect account id with no
    token to store), Calendar pushes keep happening long after the initial
    connect, so a refresh token really does need to be persisted here."""
    __tablename__ = 'calendar_account'

    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(db.Integer, db.ForeignKey('business.id'), nullable=False, unique=True, index=True)

    provider = db.Column(db.String(32), nullable=False, default='google', server_default='google')
    # Which calendar on the connected account events are written to --
    # resolved to the real primary calendar id on connect (see
    # routes/calendar.py's oauth_callback), not left as the literal
    # string 'primary' (Google's events API accepts either, but the real
    # id is what a free/busy query against calendarList expects).
    calendar_id = db.Column(db.String(255), nullable=False, default='primary', server_default='primary')

    access_token_enc = db.Column(db.Text, nullable=True)
    refresh_token_enc = db.Column(db.Text, nullable=True)
    expires_at = db.Column(db.DateTime, nullable=True)

    status = db.Column(db.String(20), nullable=False, default='active', server_default='active')
    account_email = db.Column(db.String(255), nullable=True)

    connected_by = db.Column(db.String(50), db.ForeignKey('user.public_id'), nullable=True)
    connected_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    business = db.relationship('Business', backref=db.backref('calendar_account', uselist=False, cascade='all, delete-orphan'))
    connector = db.relationship('User', foreign_keys=[connected_by])

    def __init__(self, business_id, provider='google'):
        self.business_id = business_id
        self.provider = provider

    def __repr__(self):
        return f'CalendarAccount({self.id}) business={self.business_id} [{self.provider}:{self.status}]'
