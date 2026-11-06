"""The 'nonprofit' module -- donations, recurring memberships, holiday/
event seat sales, payment links, a Nedarim-Plus-funded payment-failure
follow-up pipeline, a household (Family) de-duplication + global-search
layer, admin-built dynamic intake forms, and an immutable audit log -- all
gated behind BusinessSite.enabled_modules['nonprofit'], the same additive
module-flag mechanism every other bolt-on here uses (see business_site.py's
MODULE_REGISTRY comment).

This is a faithful port of a real, already-running system (a synagogue's
own site, built independently on a different stack) rather than a feature
designed from scratch -- every nuance and edge case called out in a
docstring or comment below reflects a confirmed, production-observed
behavior of that system (or of Nedarim Plus itself), not a hypothetical.
Money is stored as an integer number of agorot (1/100 NIS) in `*_cents`
columns -- same "smallest currency unit, no floats" convention this
codebase already uses for USD cents elsewhere, just a different currency's
smallest unit by default (currency='ils').

One deliberate departure from the system being ported: it was single-
tenant (one shul, one developer with direct DB access), so its only staff-
account bootstrap mechanism was a seed script run by hand. This platform is
multi-tenant SaaS -- the platform operator can't SSH in and run a seed
script for every nonprofit customer -- so NonprofitStaff gains a real
self-service bootstrap/invite path (see routes/nonprofit_staff.py) that the
system being ported never needed.
"""
from datetime import datetime

from config import db

NONPROFIT_STAFF_ROLES = ('staff', 'superadmin')

BILL_STATUSES = ('pending', 'paid', 'cancelled')
MEMBERSHIP_TIERS = ('associate', 'full')
MEMBERSHIP_STATUSES = ('pending', 'active', 'past_due', 'cancelled')
FOLLOWUP_REASONS = ('stale_pending', 'manual', 'failure_email', 'api_decline')
FOLLOWUP_STATUSES = ('open', 'email_sent', 'resolved', 'dismissed')
FORM_FIELD_TYPES = (
    'short_text', 'long_text', 'email', 'phone', 'number', 'date',
    'single_choice', 'multi_choice', 'multi_text', 'name_date_list',
)
FIELD_CONDITION_MODES = ('show_if', 'hide_if')


class NonprofitStaff(db.Model):
    """A nonprofit's own staff login -- deliberately NOT the same account
    system as the platform's community User accounts (mirrors the ported
    system's own Admin model being entirely separate from any public-
    facing accounts). Scoped to one business; the same email can be staff
    at two different nonprofits as two unrelated rows. Exactly two roles,
    flat (no finer-grained permission table) -- this was a deliberate
    design choice in the system being ported, not a gap: 'staff' can view
    everything, send follow-ups, mark paid/cancel/reactivate; only
    'superadmin' can freehand-override a payment's recorded details,
    create/cancel a fixed-amount payment link, or touch a LIVE Nedarim
    Plus standing order (amount/delete/disable/enable)."""
    __tablename__ = 'nonprofit_staff'

    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(db.Integer, db.ForeignKey('business.id'), nullable=False, index=True)

    email = db.Column(db.String(150), nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    name = db.Column(db.String(150), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='staff', server_default='staff')

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    business = db.relationship('Business', backref=db.backref('nonprofit_staff', lazy=True, cascade='all, delete-orphan'))

    __table_args__ = (db.UniqueConstraint('business_id', 'email', name='uq_nonprofit_staff_business_email'),)

    def __init__(self, business_id, email, password_hash, name, role='staff'):
        self.business_id = business_id
        self.email = email.strip().lower()
        self.password_hash = password_hash
        self.name = name
        self.role = role

    @property
    def is_superadmin(self):
        return self.role == 'superadmin'

    def __repr__(self):
        return f'NonprofitStaff({self.id}) business={self.business_id} {self.email!r} [{self.role}]'


class NonprofitFamily(db.Model):
    """A household/congregant grouping used purely for admin-side de-
    duplication -- Nedarim Plus itself never de-dupes (a husband and wife
    each submitting their own donation form becomes two unrelated
    records). Nothing is ever required to belong to a Family; every FK
    into this table is nullable with ON DELETE SET NULL, never CASCADE --
    deleting a Family only unlinks its records, never deletes them."""
    __tablename__ = 'nonprofit_family'

    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(db.Integer, db.ForeignKey('business.id'), nullable=False, index=True)

    full_name = db.Column(db.String(150), nullable=False)
    email = db.Column(db.String(150), nullable=True, index=True)
    phone = db.Column(db.String(40), nullable=True)
    address = db.Column(db.String(200), nullable=True)
    city = db.Column(db.String(100), nullable=True)
    notes = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    business = db.relationship('Business', backref=db.backref('nonprofit_families', lazy=True, cascade='all, delete-orphan'))

    def __init__(self, business_id, full_name, email=None, phone=None, address=None, city=None, notes=None):
        self.business_id = business_id
        self.full_name = full_name
        self.email = email
        self.phone = phone
        self.address = address
        self.city = city
        self.notes = notes

    def __repr__(self):
        return f'NonprofitFamily({self.id}) business={self.business_id} {self.full_name!r}'


class NonprofitFamilyLoginCode(db.Model):
    """A one-time 6-digit code emailed to a family's own address so they
    can view their giving/membership/signup history without a staff-style
    account -- the family portal's equivalent of NonprofitStaff, but
    deliberately not a real login: there's no password to set or forget,
    just "prove you own this inbox right now." code_hash follows the exact
    same werkzeug convention NonprofitStaff.password_hash uses (see
    nonprofit_staff.py) rather than inventing a second hashing scheme for
    a shorter secret. CASCADE on family delete -- an orphaned code is
    meaningless on its own, unlike every other FK into NonprofitFamily
    (which deliberately SET NULL instead, to keep the record itself)."""
    __tablename__ = 'nonprofit_family_login_code'

    id = db.Column(db.Integer, primary_key=True)
    family_id = db.Column(db.Integer, db.ForeignKey('nonprofit_family.id', ondelete='CASCADE'), nullable=False, index=True)
    code_hash = db.Column(db.String(255), nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    attempts = db.Column(db.Integer, nullable=False, default=0, server_default='0')
    consumed_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    family = db.relationship('NonprofitFamily', backref=db.backref('login_codes', lazy=True, cascade='all, delete-orphan'))

    def __init__(self, family_id, code_hash, expires_at):
        self.family_id = family_id
        self.code_hash = code_hash
        self.expires_at = expires_at

    def __repr__(self):
        return f'NonprofitFamilyLoginCode(family={self.family_id})'


class NonprofitHoliday(db.Model):
    """A holiday/event with per-seat pricing (member vs. non-member),
    sold via NonprofitBill/NonprofitSignup below. Prices in agorot, like
    everything else in this module."""
    __tablename__ = 'nonprofit_holiday'

    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(db.Integer, db.ForeignKey('business.id'), nullable=False, index=True)

    slug = db.Column(db.String(80), nullable=False)
    name_en = db.Column(db.String(150), nullable=False)
    name_he = db.Column(db.String(150), nullable=True)
    description_en = db.Column(db.Text, nullable=True)
    description_he = db.Column(db.Text, nullable=True)
    member_price_cents = db.Column(db.Integer, nullable=False)
    non_member_price_cents = db.Column(db.Integer, nullable=False)
    is_open = db.Column(db.Boolean, nullable=False, default=True, server_default='true')

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    business = db.relationship('Business', backref=db.backref('nonprofit_holidays', lazy=True, cascade='all, delete-orphan'))
    signups = db.relationship('NonprofitSignup', backref='holiday', lazy=True)

    __table_args__ = (db.UniqueConstraint('business_id', 'slug', name='uq_nonprofit_holiday_business_slug'),)

    def __init__(self, business_id, slug, name_en, member_price_cents, non_member_price_cents,
                 name_he=None, description_en=None, description_he=None, is_open=True):
        self.business_id = business_id
        self.slug = slug
        self.name_en = name_en
        self.name_he = name_he
        self.description_en = description_en
        self.description_he = description_he
        self.member_price_cents = member_price_cents
        self.non_member_price_cents = non_member_price_cents
        self.is_open = is_open

    def price_for(self, is_member):
        return self.member_price_cents if is_member else self.non_member_price_cents

    def __repr__(self):
        return f'NonprofitHoliday({self.id}) business={self.business_id} {self.slug!r}'


class NonprofitBill(db.Model):
    """One holiday-seat purchase -- one or more NonprofitSignup line
    items. `is_member` is shared across the whole bill (not per line
    item), so editing it must recompute every line item's total (see
    routes/nonprofit_holidays.py's update path, ported verbatim from the
    equivalent nuance in the system this is based on)."""
    __tablename__ = 'nonprofit_bill'

    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(db.Integer, db.ForeignKey('business.id'), nullable=False, index=True)
    family_id = db.Column(db.Integer, db.ForeignKey('nonprofit_family.id', ondelete='SET NULL'), nullable=True, index=True)

    reference_code = db.Column(db.String(16), nullable=False, unique=True, index=True)
    full_name = db.Column(db.String(150), nullable=False)
    phone = db.Column(db.String(40), nullable=False)
    email = db.Column(db.String(150), nullable=True)
    is_member = db.Column(db.Boolean, nullable=False, default=False)
    notes = db.Column(db.Text, nullable=True)
    total_cents = db.Column(db.Integer, nullable=False, default=0)
    status = db.Column(db.String(20), nullable=False, default='pending', server_default='pending', index=True)
    created_by = db.Column(db.String(50), nullable=False, default='public', server_default='public')

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    business = db.relationship('Business', backref=db.backref('nonprofit_bills', lazy=True, cascade='all, delete-orphan'))
    family = db.relationship('NonprofitFamily', backref=db.backref('bills', lazy=True))
    line_items = db.relationship('NonprofitSignup', backref='bill', lazy=True, cascade='all, delete-orphan')
    transactions = db.relationship('NonprofitTransaction', backref='bill', lazy=True)
    follow_ups = db.relationship('NonprofitPaymentFollowUp', backref='bill', lazy=True)

    def __init__(self, business_id, reference_code, full_name, phone, email=None, is_member=False,
                 notes=None, total_cents=0, status='pending', created_by='public', family_id=None):
        self.business_id = business_id
        self.reference_code = reference_code
        self.full_name = full_name
        self.phone = phone
        self.email = email
        self.is_member = is_member
        self.notes = notes
        self.total_cents = total_cents
        self.status = status
        self.created_by = created_by
        self.family_id = family_id

    def __repr__(self):
        return f'NonprofitBill({self.id}) {self.reference_code} [{self.status}]'


class NonprofitSignup(db.Model):
    """One holiday within one bill. Soft-deleted only (deleted_at) --
    excluded from every admin view/total/CSV export but never hard-
    deleted, same convention used for FormField/FormResponse below."""
    __tablename__ = 'nonprofit_signup'

    id = db.Column(db.Integer, primary_key=True)
    bill_id = db.Column(db.Integer, db.ForeignKey('nonprofit_bill.id'), nullable=False, index=True)
    holiday_id = db.Column(db.Integer, db.ForeignKey('nonprofit_holiday.id'), nullable=False, index=True)

    men_seats = db.Column(db.Integer, nullable=False, default=0, server_default='0')
    women_seats = db.Column(db.Integer, nullable=False, default=0, server_default='0')
    total_cents = db.Column(db.Integer, nullable=False, default=0)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    deleted_at = db.Column(db.DateTime, nullable=True)

    __table_args__ = (db.UniqueConstraint('bill_id', 'holiday_id', name='uq_nonprofit_signup_bill_holiday'),)

    def __init__(self, bill_id, holiday_id, men_seats=0, women_seats=0, total_cents=0):
        self.bill_id = bill_id
        self.holiday_id = holiday_id
        self.men_seats = men_seats
        self.women_seats = women_seats
        self.total_cents = total_cents

    def __repr__(self):
        return f'NonprofitSignup({self.id}) bill={self.bill_id} holiday={self.holiday_id}'


class NonprofitDonation(db.Model):
    """A one-time donation. Email is mandatory -- it's the only reliable
    contact channel if the payment fails (no decline webhook exists; see
    NonprofitPaymentFollowUp)."""
    __tablename__ = 'nonprofit_donation'

    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(db.Integer, db.ForeignKey('business.id'), nullable=False, index=True)
    family_id = db.Column(db.Integer, db.ForeignKey('nonprofit_family.id', ondelete='SET NULL'), nullable=True, index=True)

    reference_code = db.Column(db.String(16), nullable=False, unique=True, index=True)
    full_name = db.Column(db.String(150), nullable=False)
    email = db.Column(db.String(150), nullable=False)
    phone = db.Column(db.String(40), nullable=True)
    address = db.Column(db.String(200), nullable=True)
    city = db.Column(db.String(100), nullable=True)
    amount_cents = db.Column(db.Integer, nullable=False)
    purpose = db.Column(db.String(200), nullable=True)
    status = db.Column(db.String(20), nullable=False, default='pending', server_default='pending', index=True)
    created_by = db.Column(db.String(50), nullable=False, default='public', server_default='public')

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    business = db.relationship('Business', backref=db.backref('nonprofit_donations', lazy=True, cascade='all, delete-orphan'))
    family = db.relationship('NonprofitFamily', backref=db.backref('donations', lazy=True))
    transactions = db.relationship('NonprofitTransaction', backref='donation', lazy=True)
    follow_ups = db.relationship('NonprofitPaymentFollowUp', backref='donation', lazy=True)

    def __init__(self, business_id, reference_code, full_name, email, amount_cents, phone=None,
                 address=None, city=None, purpose=None, status='pending', created_by='public', family_id=None):
        self.business_id = business_id
        self.reference_code = reference_code
        self.full_name = full_name
        self.email = email
        self.phone = phone
        self.address = address
        self.city = city
        self.amount_cents = amount_cents
        self.purpose = purpose
        self.status = status
        self.created_by = created_by
        self.family_id = family_id

    def __repr__(self):
        return f'NonprofitDonation({self.id}) {self.reference_code} [{self.status}]'


class NonprofitMembership(db.Model):
    """Recurring monthly dues via Nedarim Plus's standing-order ('Keva')
    mechanism. `monthly_cents` is SNAPSHOTTED at signup -- a later price
    change (NONPROFIT_MEMBERSHIP_PRICES_CENTS) never rewrites an existing
    member's history. `nedarim_deleted_at`/`nedarim_disabled_at` only ever
    get set by a REAL Nedarim Plus write call (DeleteKeva/DisableKeva) --
    cancelling locally (status='cancelled') does NOT touch the real
    standing order; see the webhook handler's explicit
    unexpected_charge_while_cancelled audit case for why that distinction
    matters."""
    __tablename__ = 'nonprofit_membership'

    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(db.Integer, db.ForeignKey('business.id'), nullable=False, index=True)
    family_id = db.Column(db.Integer, db.ForeignKey('nonprofit_family.id', ondelete='SET NULL'), nullable=True, index=True)

    reference_code = db.Column(db.String(16), nullable=False, unique=True, index=True)
    full_name = db.Column(db.String(150), nullable=False)
    email = db.Column(db.String(150), nullable=False)
    phone = db.Column(db.String(40), nullable=True)
    address = db.Column(db.String(200), nullable=True)
    city = db.Column(db.String(100), nullable=True)

    tier = db.Column(db.String(20), nullable=False, default='associate', server_default='associate')
    monthly_cents = db.Column(db.Integer, nullable=False)
    monthly_is_estimated = db.Column(db.Boolean, nullable=False, default=False, server_default='false')

    nedarim_payments_made = db.Column(db.Integer, nullable=True)
    nedarim_payments_remaining = db.Column(db.Integer, nullable=True)
    nedarim_deleted_at = db.Column(db.DateTime, nullable=True)
    nedarim_disabled_at = db.Column(db.DateTime, nullable=True)
    keva_id = db.Column(db.String(64), nullable=True, unique=True, index=True)

    status = db.Column(db.String(20), nullable=False, default='pending', server_default='pending', index=True)
    next_charge_date = db.Column(db.DateTime, nullable=True)
    last_charge_at = db.Column(db.DateTime, nullable=True)
    created_by = db.Column(db.String(50), nullable=False, default='public', server_default='public')

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    business = db.relationship('Business', backref=db.backref('nonprofit_memberships', lazy=True, cascade='all, delete-orphan'))
    family = db.relationship('NonprofitFamily', backref=db.backref('memberships', lazy=True))
    transactions = db.relationship('NonprofitTransaction', backref='membership', lazy=True)
    follow_ups = db.relationship('NonprofitPaymentFollowUp', backref='membership', lazy=True)

    def __init__(self, business_id, reference_code, full_name, email, tier, monthly_cents, phone=None,
                 address=None, city=None, status='pending', created_by='public', family_id=None):
        self.business_id = business_id
        self.reference_code = reference_code
        self.full_name = full_name
        self.email = email
        self.phone = phone
        self.address = address
        self.city = city
        self.tier = tier
        self.monthly_cents = monthly_cents
        self.status = status
        self.created_by = created_by
        self.family_id = family_id

    def __repr__(self):
        return f'NonprofitMembership({self.id}) {self.reference_code} [{self.status}]'


class NonprofitPaymentLink(db.Model):
    """An admin-generated fixed-amount payment link (a pledge, an event
    fee, an underpayment correction) -- a fixed amount someone can just
    pay without filling out a public form. Creation/cancellation is
    superadmin-only (see routes/nonprofit_donations.py)."""
    __tablename__ = 'nonprofit_payment_link'

    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(db.Integer, db.ForeignKey('business.id'), nullable=False, index=True)
    family_id = db.Column(db.Integer, db.ForeignKey('nonprofit_family.id', ondelete='SET NULL'), nullable=True, index=True)

    reference_code = db.Column(db.String(16), nullable=False, unique=True, index=True)
    label = db.Column(db.String(200), nullable=False)
    full_name = db.Column(db.String(150), nullable=True)
    phone = db.Column(db.String(40), nullable=True)
    email = db.Column(db.String(150), nullable=True)
    amount_cents = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(20), nullable=False, default='pending', server_default='pending', index=True)
    created_by = db.Column(db.String(50), nullable=False, default='admin', server_default='admin')

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    business = db.relationship('Business', backref=db.backref('nonprofit_payment_links', lazy=True, cascade='all, delete-orphan'))
    family = db.relationship('NonprofitFamily', backref=db.backref('payment_links', lazy=True))
    transactions = db.relationship('NonprofitTransaction', backref='payment_link', lazy=True)
    follow_ups = db.relationship('NonprofitPaymentFollowUp', backref='payment_link', lazy=True)

    def __init__(self, business_id, reference_code, label, amount_cents, full_name=None, phone=None,
                 email=None, status='pending', created_by='admin', family_id=None):
        self.business_id = business_id
        self.reference_code = reference_code
        self.label = label
        self.amount_cents = amount_cents
        self.full_name = full_name
        self.phone = phone
        self.email = email
        self.status = status
        self.created_by = created_by
        self.family_id = family_id

    def __repr__(self):
        return f'NonprofitPaymentLink({self.id}) {self.reference_code} [{self.status}]'


class NonprofitTransaction(db.Model):
    """One successful Nedarim Plus charge against exactly one of
    Bill/Donation/Membership/PaymentLink. `nedarim_transaction_id` is the
    DB-level dedupe backstop against Nedarim Plus's own confirmed webhook-
    retry behavior (nullable unique -- Postgres allows multiple NULLs
    under a unique constraint, and not every charge carries one, e.g. a
    manually-recorded 'other transaction'). `amount_is_estimated` is True
    when the webhook/report didn't carry a usable Amount and the resolved
    amount fell back to the record's own expected amount instead of
    recording a false 0."""
    __tablename__ = 'nonprofit_transaction'

    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(db.Integer, db.ForeignKey('business.id'), nullable=False, index=True)

    bill_id = db.Column(db.Integer, db.ForeignKey('nonprofit_bill.id'), nullable=True, index=True)
    donation_id = db.Column(db.Integer, db.ForeignKey('nonprofit_donation.id'), nullable=True, index=True)
    membership_id = db.Column(db.Integer, db.ForeignKey('nonprofit_membership.id'), nullable=True, index=True)
    payment_link_id = db.Column(db.Integer, db.ForeignKey('nonprofit_payment_link.id'), nullable=True, index=True)

    nedarim_transaction_id = db.Column(db.String(64), nullable=True, unique=True, index=True)
    confirmation = db.Column(db.String(64), nullable=True)
    amount_cents = db.Column(db.Integer, nullable=False)
    amount_is_estimated = db.Column(db.Boolean, nullable=False, default=False, server_default='false')
    source = db.Column(db.String(20), nullable=False, default='webhook', server_default='webhook')
    raw_payload = db.Column(db.JSON, nullable=True)

    received_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    business = db.relationship('Business', backref=db.backref('nonprofit_transactions', lazy=True, cascade='all, delete-orphan'))

    def __init__(self, business_id, amount_cents, bill_id=None, donation_id=None, membership_id=None,
                 payment_link_id=None, nedarim_transaction_id=None, confirmation=None,
                 amount_is_estimated=False, source='webhook', raw_payload=None):
        self.business_id = business_id
        self.amount_cents = amount_cents
        self.bill_id = bill_id
        self.donation_id = donation_id
        self.membership_id = membership_id
        self.payment_link_id = payment_link_id
        self.nedarim_transaction_id = nedarim_transaction_id
        self.confirmation = confirmation
        self.amount_is_estimated = amount_is_estimated
        self.source = source
        self.raw_payload = raw_payload

    def __repr__(self):
        return f'NonprofitTransaction({self.id}) business={self.business_id} {self.amount_cents}c'


class NonprofitExternalTransaction(db.Model):
    """A successful Nedarim Plus transaction whose Avour/Comments (and
    KevaId) didn't match anything this system generated -- e.g. a pre-
    existing standing order set up directly on the Nedarim Plus dashboard
    before this site existed. Pure record-keeping ledger; the only admin
    actions against it are merge-into-family / unlink, never edit."""
    __tablename__ = 'nonprofit_external_transaction'

    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(db.Integer, db.ForeignKey('business.id'), nullable=False, index=True)
    family_id = db.Column(db.Integer, db.ForeignKey('nonprofit_family.id', ondelete='SET NULL'), nullable=True, index=True)

    nedarim_transaction_id = db.Column(db.String(64), nullable=True, unique=True, index=True)
    amount_cents = db.Column(db.Integer, nullable=False)
    client_name = db.Column(db.String(150), nullable=True)
    phone = db.Column(db.String(40), nullable=True)
    email = db.Column(db.String(150), nullable=True)
    groupe = db.Column(db.String(200), nullable=True)
    comments = db.Column(db.Text, nullable=True)
    confirmation = db.Column(db.String(64), nullable=True)
    keva_id = db.Column(db.String(64), nullable=True)
    raw_payload = db.Column(db.JSON, nullable=True)

    received_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    business = db.relationship('Business', backref=db.backref('nonprofit_external_transactions', lazy=True, cascade='all, delete-orphan'))
    family = db.relationship('NonprofitFamily', backref=db.backref('external_transactions', lazy=True))

    def __init__(self, business_id, amount_cents, nedarim_transaction_id=None, client_name=None, phone=None,
                 email=None, groupe=None, comments=None, confirmation=None, keva_id=None, raw_payload=None, family_id=None):
        self.business_id = business_id
        self.amount_cents = amount_cents
        self.nedarim_transaction_id = nedarim_transaction_id
        self.client_name = client_name
        self.phone = phone
        self.email = email
        self.groupe = groupe
        self.comments = comments
        self.confirmation = confirmation
        self.keva_id = keva_id
        self.raw_payload = raw_payload
        self.family_id = family_id

    def __repr__(self):
        return f'NonprofitExternalTransaction({self.id}) business={self.business_id} {self.amount_cents}c'


class NonprofitPaymentFollowUp(db.Model):
    """Tracks a payment that may need staff follow-up (decline/stale
    pending). Nedarim Plus has NO decline webhook at all -- this is fed by
    three independent detectors: a stale-pending cron sweep, Nedarim
    Plus's own standing-order report API (the only automatic decline
    signal it exposes anywhere, and only for memberships), and staff
    manually pasting a forwarded Nedarim Plus decline email. A follow-up
    can be STANDALONE (every FK null, the external_* fields populated
    instead) when it's a decline on a standing order/link this system
    never created -- the first time an email is sent for a standalone
    follow-up, a real NonprofitPaymentLink is provisioned for it so it
    becomes properly trackable going forward."""
    __tablename__ = 'nonprofit_payment_followup'

    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(db.Integer, db.ForeignKey('business.id'), nullable=False, index=True)

    bill_id = db.Column(db.Integer, db.ForeignKey('nonprofit_bill.id'), nullable=True, index=True)
    donation_id = db.Column(db.Integer, db.ForeignKey('nonprofit_donation.id'), nullable=True, index=True)
    membership_id = db.Column(db.Integer, db.ForeignKey('nonprofit_membership.id'), nullable=True, index=True)
    payment_link_id = db.Column(db.Integer, db.ForeignKey('nonprofit_payment_link.id'), nullable=True, index=True)

    reason = db.Column(db.String(20), nullable=False)
    status = db.Column(db.String(20), nullable=False, default='open', server_default='open', index=True)
    notes = db.Column(db.Text, nullable=True)
    emails_sent_count = db.Column(db.Integer, nullable=False, default=0, server_default='0')
    last_email_sent_at = db.Column(db.DateTime, nullable=True)
    resolved_at = db.Column(db.DateTime, nullable=True)

    external_full_name = db.Column(db.String(150), nullable=True)
    external_phone = db.Column(db.String(40), nullable=True)
    external_email = db.Column(db.String(150), nullable=True)
    external_amount_cents = db.Column(db.Integer, nullable=True)
    external_category = db.Column(db.String(200), nullable=True)
    external_keva_id = db.Column(db.String(64), nullable=True)

    failure_reason = db.Column(db.String(300), nullable=True)
    card_last4 = db.Column(db.String(4), nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    business = db.relationship('Business', backref=db.backref('nonprofit_followups', lazy=True, cascade='all, delete-orphan'))

    def __init__(self, business_id, reason, bill_id=None, donation_id=None, membership_id=None,
                 payment_link_id=None, status='open', notes=None, external_full_name=None,
                 external_phone=None, external_email=None, external_amount_cents=None,
                 external_category=None, external_keva_id=None, failure_reason=None, card_last4=None):
        self.business_id = business_id
        self.reason = reason
        self.bill_id = bill_id
        self.donation_id = donation_id
        self.membership_id = membership_id
        self.payment_link_id = payment_link_id
        self.status = status
        self.notes = notes
        self.external_full_name = external_full_name
        self.external_phone = external_phone
        self.external_email = external_email
        self.external_amount_cents = external_amount_cents
        self.external_category = external_category
        self.external_keva_id = external_keva_id
        self.failure_reason = failure_reason
        self.card_last4 = card_last4

    @property
    def is_standalone(self):
        return not any([self.bill_id, self.donation_id, self.membership_id, self.payment_link_id])

    def __repr__(self):
        return f'NonprofitPaymentFollowUp({self.id}) business={self.business_id} [{self.status}]'


class NonprofitForm(db.Model):
    """An admin-built, never-publicly-listed dynamic intake form --
    reachable only via a direct /nonprofit/<subdomain>/forms/<slug> link
    or the staff portal, gated by is_open."""
    __tablename__ = 'nonprofit_form'

    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(db.Integer, db.ForeignKey('business.id'), nullable=False, index=True)

    slug = db.Column(db.String(80), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    thank_you_message = db.Column(db.Text, nullable=True)
    is_open = db.Column(db.Boolean, nullable=False, default=False, server_default='false')

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    business = db.relationship('Business', backref=db.backref('nonprofit_forms', lazy=True, cascade='all, delete-orphan'))
    fields = db.relationship('NonprofitFormField', backref='form', lazy=True, cascade='all, delete-orphan',
                              order_by='NonprofitFormField.order')
    responses = db.relationship('NonprofitFormResponse', backref='form', lazy=True, cascade='all, delete-orphan')

    __table_args__ = (db.UniqueConstraint('business_id', 'slug', name='uq_nonprofit_form_business_slug'),)

    def __init__(self, business_id, slug, title, description=None, thank_you_message=None, is_open=False):
        self.business_id = business_id
        self.slug = slug
        self.title = title
        self.description = description
        self.thank_you_message = thank_you_message
        self.is_open = is_open

    def __repr__(self):
        return f'NonprofitForm({self.id}) business={self.business_id} {self.slug!r}'


class NonprofitFormField(db.Model):
    """One field in a dynamic form. Soft-removed (archived_at), never
    hard-deleted, so an old FormResponse that answered this field stays
    resolvable. Supports one layer of conditional logic keyed to an
    EARLIER field's answer: condition_field_id/condition_value/
    condition_mode (show the field only if / hide it if that earlier
    field's answer matches condition_value), and separately alt_label
    (swaps this field's own label when the condition matches, independent
    of condition_mode -- lets a field stay always-visible but reword
    itself, e.g. 'Husband's Name' -> 'Your Name')."""
    __tablename__ = 'nonprofit_form_field'

    id = db.Column(db.Integer, primary_key=True)
    form_id = db.Column(db.Integer, db.ForeignKey('nonprofit_form.id'), nullable=False, index=True)

    label = db.Column(db.String(200), nullable=False)
    type = db.Column(db.String(20), nullable=False)
    required = db.Column(db.Boolean, nullable=False, default=False, server_default='false')
    options = db.Column(db.JSON, nullable=True)  # list[str] for choice types
    help_text = db.Column(db.String(300), nullable=True)
    order = db.Column(db.Integer, nullable=False, default=0, server_default='0')
    archived_at = db.Column(db.DateTime, nullable=True)

    condition_field_id = db.Column(db.Integer, db.ForeignKey('nonprofit_form_field.id', ondelete='SET NULL'), nullable=True)
    condition_value = db.Column(db.String(300), nullable=True)
    condition_mode = db.Column(db.String(10), nullable=True)  # 'show_if' | 'hide_if'
    alt_label = db.Column(db.String(200), nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __init__(self, form_id, label, type, required=False, options=None, help_text=None, order=0,
                 condition_field_id=None, condition_value=None, condition_mode=None, alt_label=None):
        self.form_id = form_id
        self.label = label
        self.type = type
        self.required = required
        self.options = options
        self.help_text = help_text
        self.order = order
        self.condition_field_id = condition_field_id
        self.condition_value = condition_value
        self.condition_mode = condition_mode
        self.alt_label = alt_label

    def __repr__(self):
        return f'NonprofitFormField({self.id}) form={self.form_id} {self.label!r}'


class NonprofitFormResponse(db.Model):
    """`answers` is a JSON map of {field_id (str): value} -- value is a
    plain string, a list[str] (MULTI_CHOICE/MULTI_TEXT), or a
    list[{name, date}] (NAME_DATE_LIST). No fixed identity columns, so
    search/family-matching best-effort-extracts name/email/phone/address/
    city by matching the FORM'S OWN field labels against keyword lists
    (see routes/nonprofit_forms.py:guess_identity_from_response)."""
    __tablename__ = 'nonprofit_form_response'

    id = db.Column(db.Integer, primary_key=True)
    form_id = db.Column(db.Integer, db.ForeignKey('nonprofit_form.id'), nullable=False, index=True)
    family_id = db.Column(db.Integer, db.ForeignKey('nonprofit_family.id', ondelete='SET NULL'), nullable=True, index=True)

    answers = db.Column(db.JSON, nullable=False, default=dict)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    deleted_at = db.Column(db.DateTime, nullable=True, index=True)

    family = db.relationship('NonprofitFamily', backref=db.backref('form_responses', lazy=True))

    def __init__(self, form_id, answers, family_id=None):
        self.form_id = form_id
        self.answers = answers
        self.family_id = family_id

    def __repr__(self):
        return f'NonprofitFormResponse({self.id}) form={self.form_id}'


class NonprofitAuditLog(db.Model):
    """Immutable one-way audit trail -- never edited or deleted.
    staff_email='system' means a webhook (not a human staff member) made
    the change. `changes` is {field: {before, after}}, only for fields
    that actually changed (see routes/nonprofit_audit.py:diff_fields) --
    an edit that changed nothing doesn't get logged at all."""
    __tablename__ = 'nonprofit_audit_log'

    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(db.Integer, db.ForeignKey('business.id'), nullable=False, index=True)

    staff_email = db.Column(db.String(150), nullable=False)
    action = db.Column(db.String(100), nullable=False)
    record_type = db.Column(db.String(50), nullable=False)
    record_id = db.Column(db.Integer, nullable=False)
    changes = db.Column(db.JSON, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    business = db.relationship('Business', backref=db.backref('nonprofit_audit_logs', lazy=True, cascade='all, delete-orphan'))

    __table_args__ = (db.Index('ix_nonprofit_audit_record', 'record_type', 'record_id'),)

    def __init__(self, business_id, staff_email, action, record_type, record_id, changes=None):
        self.business_id = business_id
        self.staff_email = staff_email
        self.action = action
        self.record_type = record_type
        self.record_id = record_id
        self.changes = changes

    def __repr__(self):
        return f'NonprofitAuditLog({self.id}) business={self.business_id} {self.action}'


class NonprofitPaymentConfig(db.Model):
    """Per-business Nedarim Plus credentials. The system being ported was
    single-tenant and read these from process env vars; here each
    nonprofit customer enters their OWN Mosad number/API credentials in
    their site settings, since this platform hosts many independent
    nonprofits side by side. `api_password` (ApiPassword, starts with
    npk_) is a real secret -- used server-side only, for the Reports/
    Manage3.aspx admin API (history sync, Keva writes, decline reports).
    `api_valid` (ApiValid) is NOT a secret -- it's sent client-side (to
    the Nedarim Plus iframe) purely to confirm the integration is
    authorized; exposing it in a page is not a risk."""
    __tablename__ = 'nonprofit_payment_config'

    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(db.Integer, db.ForeignKey('business.id'), nullable=False, unique=True, index=True)

    mosad_id = db.Column(db.String(10), nullable=True)
    api_password = db.Column(db.String(64), nullable=True)
    api_valid = db.Column(db.String(32), nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    business = db.relationship('Business', backref=db.backref('nonprofit_payment_config', uselist=False, cascade='all, delete-orphan'))

    def __init__(self, business_id, mosad_id=None, api_password=None, api_valid=None):
        self.business_id = business_id
        self.mosad_id = mosad_id
        self.api_password = api_password
        self.api_valid = api_valid

    @property
    def is_configured(self):
        return bool(self.mosad_id and self.api_valid)

    @property
    def reports_configured(self):
        """Mosad + ApiPassword -- needed for the admin-side Manage3.aspx
        calls (history sync, decline reports, live Keva writes). Separate
        from is_configured because a nonprofit can accept payments
        (Mosad + ApiValid only) without ever enabling these -- same
        'genuinely optional' framing the ported system uses."""
        return bool(self.mosad_id and self.api_password)

    def __repr__(self):
        return f'NonprofitPaymentConfig(business={self.business_id})'
