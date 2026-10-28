import secrets
from datetime import datetime

from config import db

# Enforced at the Python/route level (not a DB enum) -- same convention as
# POST_TYPES/LISTING_TYPES elsewhere in this codebase.
SEARCH_TYPES = ('estates', 'tachlis')

# Stage 4's "full alert rules": how often to check (daily batch vs. as soon
# as a run notices a match) and where to send. 'whatsapp' is accepted and
# stored, but not yet actually delivered -- see emails.send_digest_email's
# caller in routes/alert.py, which sends every channel through email until
# GUT has its own WhatsApp Business number and Meta-approved templates
# (outside this agent's hands, per gut_next_level_agent.md). The frontend
# shows it as "coming soon" rather than hiding it, so the setting is already
# in place the day it's switched on.
CADENCES = ('daily', 'instant')
CHANNELS = ('email', 'whatsapp')


def _new_token():
    return secrets.token_urlsafe(32)


class Alert(db.Model):
    """"Get alerts for this search" (Stage 3 of gut_next_level_agent.md) --
    one saved search (Estates or Tachlis), as the exact query string that
    search's own listing page would send (e.g.
    "listing_type=long_term_lease&city=RBS+Gimmel"), so matching an alert
    against new posts reuses the SAME filter-building code the live search
    already uses (see routes/estates.py's/tachlis_post.py's shared
    _build_*_query() -- never two independently-maintained copies of "what
    counts as a match").

    No account required to create one (Stage 3's whole point) -- `user_id`
    starts NULL and is backfilled the moment a matching email signs up or
    logs in (see application.py's login() and user.py's add_user())."""
    __tablename__ = 'alert'

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(200), nullable=False, index=True)
    user_id = db.Column(db.String(50), db.ForeignKey('user.public_id'), nullable=True, index=True)

    search_type = db.Column(db.String(20), nullable=False, index=True)
    # The exact querystring (no leading '?') the matching search endpoint
    # already accepts -- e.g. GET /estates/listings?<filters>. Reused as-is
    # by the digest job so a match always agrees with what the live search
    # itself would return for the same filters.
    filters = db.Column(db.Text, nullable=False)
    # Human-readable summary shown back to the person in their confirmation
    # email and their "My Alerts" list -- built client-side from whatever
    # filter chips/inputs were active when they clicked "Get alerts", since
    # the frontend already has readable labels for each filter value.
    label = db.Column(db.String(300), nullable=True)

    confirmed = db.Column(db.Boolean, nullable=False, default=False, server_default='false')
    confirm_token = db.Column(db.String(64), nullable=False, unique=True, index=True)
    unsubscribe_token = db.Column(db.String(64), nullable=False, unique=True, index=True)
    paused = db.Column(db.Boolean, nullable=False, default=False, server_default='false')

    # Stage 4: a Member can upgrade their own alert past Stage 3's one-size-
    # fits-all daily digest. Left editable only from "My Alerts" (update_alert
    # requires a logged-in owner already) -- a Visitor's alert, made with just
    # an email, stays 'daily'/'email' until they sign in and change it.
    cadence = db.Column(db.String(20), nullable=False, default='daily', server_default='daily')
    channel = db.Column(db.String(20), nullable=False, default='email', server_default='email')

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    # Watermark: the digest job only ever sends items newer than this (by
    # the same coalesce(source_posted_at, pub_date) every "newest" sort
    # already uses), then advances it to "now" after a successful send --
    # simpler than a separate sent-items join table, and sufficient since
    # the digest only runs once a day (see routes/alert.py's send_digests()).
    last_notified_at = db.Column(db.DateTime, nullable=True)

    user = db.relationship('User', backref=db.backref('alerts', lazy=True))

    def __init__(self, email, search_type, filters, label=None, user_id=None):
        self.email = email
        self.search_type = search_type
        self.filters = filters
        self.label = label
        self.user_id = user_id
        self.confirm_token = _new_token()
        self.unsubscribe_token = _new_token()

    def __repr__(self):
        return f'Alert({self.id}) [{self.search_type}] {self.email}'


class AlertDigestSchedule(db.Model):
    """Single-row table (id is always 1) holding when the daily digest job
    should actually send, in Israel local time -- edited by a super admin
    from SuperAdminDashboard with no redeploy needed (see routes/alert.py's
    _get_schedule()/_maybe_run_scheduled_digest()). last_run_date is the
    watermark that keeps a frequently-polling external scheduler (or the
    opportunistic sweep) from sending twice on the same calendar day."""
    __tablename__ = 'alert_digest_schedule'

    id = db.Column(db.Integer, primary_key=True)
    send_hour = db.Column(db.Integer, nullable=False, default=9, server_default='9')
    send_minute = db.Column(db.Integer, nullable=False, default=0, server_default='0')
    last_run_date = db.Column(db.Date, nullable=True)
    updated_at = db.Column(db.DateTime, nullable=True)

    # Stage 4's "Your week" digest -- same Israel-local send_hour/send_minute
    # as the daily alert digest above, plus which day of the week (Python's
    # Monday=0..Sunday=6) it goes out on. Defaults to Sunday, the start of
    # the work/school week here (see gut_next_level_agent.md's own "Tab
    # posts... Sunday to Friday"). last_weekly_run_date is that watermark's
    # own week -- separate from last_run_date so changing one never
    # resets the other's cadence.
    weekly_weekday = db.Column(db.Integer, nullable=False, default=6, server_default='6')
    last_weekly_run_date = db.Column(db.Date, nullable=True)

    # Stage 5's "Still available?" check -- messages real posters and
    # auto-hides their content on silence, so this stays off until a super
    # admin explicitly turns it on (PATCH /alerts/admin/schedule), per
    # gut_next_level_agent.md's own "This messages posters, so only with
    # your OK." Unlike every other job here, there is deliberately no
    # "opportunistic sweep" fallback for this one -- see
    # _maybe_run_scheduled_digest()'s own comment.
    still_available_check_enabled = db.Column(db.Boolean, nullable=False, default=False, server_default='false')
