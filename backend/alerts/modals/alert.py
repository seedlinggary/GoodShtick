import secrets
from datetime import datetime

from config import db

# Enforced at the Python/route level (not a DB enum) -- same convention as
# POST_TYPES/LISTING_TYPES elsewhere in this codebase.
SEARCH_TYPES = ('estates', 'tachlis')


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
