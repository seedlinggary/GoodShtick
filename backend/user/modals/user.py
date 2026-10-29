import secrets

from config import db
from datetime import datetime

# Stage 4's "Profile and personal feed" -- enforced at the Python/route
# level, not a DB enum, same convention as SEARCH_TYPES elsewhere.
LINE_OF_WORK_OPTIONS = (
    'tech', 'healthcare', 'education', 'sales_marketing', 'finance_accounting',
    'skilled_trade', 'hospitality', 'legal', 'government', 'self_employed', 'student', 'other',
)


class User(db.Model):
    __tablename__ = 'user'

    id = db.Column(db.Integer, primary_key=True)
    public_id = db.Column(db.String(50), unique=True)
    first_name = db.Column(db.String(20))
    last_name = db.Column(db.String(20))
    profile_name = db.Column(db.String(120), unique=True)
    email = db.Column(db.String(120), unique=True)
    password = db.Column(db.String(200))
    pub_date = db.Column(db.DateTime, default=datetime.utcnow)
    role = db.Column(db.String(20), default='user')  # viewer, user, admin, super_admin
    last_login = db.Column(db.DateTime, nullable=True)

    # Optional, self-reported — used only for ad targeting. Never required at signup.
    birthdate = db.Column(db.Date, nullable=True)
    gender = db.Column(db.String(20), nullable=True)
    location_country = db.Column(db.String(100), nullable=True)
    location_city = db.Column(db.String(100), nullable=True)

    # Stage 4's "one profile, one personal feed" -- also optional, drives
    # /feed/aggregate's personalization (see backend/feed/routes/aggregate.py)
    # rather than gating anything. profile_area is free text (a city or
    # neighborhood name, matched the same loose way search filters already do).
    profile_area = db.Column(db.String(100), nullable=True)
    # Stamped only when profile_area actually changes to a new non-null
    # value (see update_profile in backend/user/routes/user.py) -- used by
    # the weekly digest's "did they just move" detection. Deliberately a
    # single bare timestamp, not a full change-history/audit table.
    profile_area_changed_at = db.Column(db.DateTime, nullable=True)
    budget_min = db.Column(db.Integer, nullable=True)
    budget_max = db.Column(db.Integer, nullable=True)
    family_size = db.Column(db.Integer, nullable=True)
    line_of_work = db.Column(db.String(30), nullable=True)

    # Stage 4's "Your week" digest -- opt-out token so the one-click
    # unsubscribe link in that email needs no login (same pattern as
    # Alert.unsubscribe_token). Defaults to on for every existing user.
    weekly_digest_enabled = db.Column(db.Boolean, nullable=False, default=True, server_default='true')
    weekly_digest_token = db.Column(db.String(64), nullable=True, unique=True)
    last_weekly_digest_at = db.Column(db.DateTime, nullable=True)

    # Stage 5's "Job profile and one-tap apply" -- all optional. cv_contact
    # is deliberately separate from the account's own email: a member opts
    # in to the public "open to work" browse (GET /tachlis/talent) only once
    # they've set BOTH open_to_work and a contact they're fine with
    # employers seeing, rather than this ever exposing their login email.
    cv_summary = db.Column(db.Text, nullable=True)
    cv_contact = db.Column(db.String(300), nullable=True)
    open_to_work = db.Column(db.Boolean, nullable=False, default=False, server_default='false')

    def __init__(self, public_id, first_name, last_name, password, email, profile_name):
        self.public_id = public_id
        self.first_name = first_name
        self.last_name = last_name
        self.password = password
        self.email = email
        self.profile_name = profile_name
        self.weekly_digest_token = secrets.token_urlsafe(32)

    @property
    def is_boss(self):
        return self.role in ('admin', 'super_admin')

    @property
    def is_super_admin(self):
        return self.role == 'super_admin'

    @property
    def age(self):
        """Whole years old as of today, or None if birthdate isn't set. Ad-targeting only."""
        if not self.birthdate:
            return None
        today = datetime.utcnow().date()
        years = today.year - self.birthdate.year
        if (today.month, today.day) < (self.birthdate.month, self.birthdate.day):
            years -= 1
        return years

    def __repr__(self):
        return f'{self.first_name} {self.last_name}'
