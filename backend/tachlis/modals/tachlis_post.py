from config import db
from datetime import datetime, timedelta

# Enforced at the Python/route level (not a Postgres enum) to match this
# project's convention of avoiding DB-level enums elsewhere.
POST_TYPES = ('job', 'resume')

# Stage 5's poster dashboard -- 'filled' is the job-board equivalent of
# Estates' 'rented'/'sold' (EstatesListing has no such column either; see
# its own POST_STATUSES below). A manually-marked status is independent of
# expires_at -- a 'filled' post still disappears from results the same way
# an expired one does (see routes/tachlis_post.py's list_posts), it just
# also tells the poster (and this model) WHY it's gone.
POST_STATUSES = ('active', 'filled')

EXPIRES_DAYS = {'job': 60, 'resume': 90}


class TachlisPost(db.Model):
    __tablename__ = 'tachlis_post'

    id = db.Column(db.Integer, primary_key=True)
    post_type = db.Column(db.String(20), nullable=False, index=True)
    title = db.Column(db.String(150), nullable=False)
    body = db.Column(db.Text, nullable=False)
    contact = db.Column(db.String(300), nullable=False)
    location = db.Column(db.String(120), nullable=True)
    compensation = db.Column(db.String(120), nullable=True)
    user_id = db.Column(db.String(50), db.ForeignKey('user.public_id'), nullable=False, index=True)
    pub_date = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    # When this post actually went up in its source WhatsApp group --
    # distinct from pub_date (when it was added to this DB). NULL for posts
    # made directly on-site, or any older imported post from before this
    # field existed; "newest" sorting falls back to pub_date in that case
    # (see routes/tachlis_post.py's list_posts), so this is purely additive.
    source_posted_at = db.Column(db.DateTime, nullable=True, index=True)
    approved_to_publish = db.Column(db.Boolean, default=None)
    approved_by = db.Column(db.String(50), db.ForeignKey('user.public_id'), nullable=True)
    expires_at = db.Column(db.DateTime, nullable=True)
    # Free-text job category (e.g. "Tech", "Healthcare", "Education") --
    # same free-text-not-enum convention as `location` below; only
    # meaningful for post_type='job' but not enforced, since a resume may
    # also want to say what field it's in.
    category = db.Column(db.String(60), nullable=True, index=True)
    # Only meaningful for jobs; None means "not specified" (same convention
    # as EstatesListing.is_agent) rather than implying on-site.
    remote = db.Column(db.Boolean, nullable=True, index=True)

    # Stage 5's poster dashboard -- same views_count idea as
    # EstatesListing's own column (incremented on GET /tachlis/posts/<id>,
    # never on a crawler-facing variant), plus contact_taps for "WhatsApp
    # taps" since Tachlis has only one free-text `contact` field, not a
    # dedicated WhatsApp column like Estates.
    views_count = db.Column(db.Integer, nullable=False, default=0, server_default='0')
    contact_taps = db.Column(db.Integer, nullable=False, default=0, server_default='0')
    status = db.Column(db.String(20), nullable=False, default='active', server_default='active')
    renewed_count = db.Column(db.Integer, nullable=False, default=0, server_default='0')

    # Stage 5's "Still available?" check -- set when the poster confirms;
    # cleared back to NULL on renew() so a renewed post is asked again at
    # its own next 14-day mark rather than being considered "confirmed
    # forever" from one reply months ago.
    still_available_confirmed_at = db.Column(db.DateTime, nullable=True)
    still_available_reminder_sent_at = db.Column(db.DateTime, nullable=True)
    still_available_token = db.Column(db.String(64), nullable=True, unique=True)

    __table_args__ = (
        # Matches the exact filter+sort pattern used by the public listing
        # query: WHERE approved_to_publish = ... ORDER BY pub_date DESC.
        db.Index('ix_tachlis_post_approved_pub_date', 'approved_to_publish', 'pub_date'),
    )

    # Relationships
    user = db.relationship('User', foreign_keys=[user_id],
                            backref=db.backref('tachlis_posts', lazy=True))
    approver = db.relationship('User', foreign_keys=[approved_by],
                                backref=db.backref('approved_tachlis_posts', lazy=True))

    def __init__(self, post_type, title, body, contact, user_id,
                 location=None, compensation=None, expires_at=None,
                 category=None, remote=None, source_posted_at=None):
        self.post_type = post_type
        self.title = title
        self.body = body
        self.contact = contact
        self.user_id = user_id
        self.location = location
        self.compensation = compensation
        self.expires_at = expires_at
        self.category = category
        self.remote = remote
        self.source_posted_at = source_posted_at

    @property
    def is_expired(self):
        return self.expires_at is not None and self.expires_at < datetime.utcnow()

    def renew(self):
        """Stage 5's poster dashboard "renew" button -- same shape as
        EstatesListing.renew(): a fresh full lifetime from now, not an
        additive bump (so a post renewed well before expiry doesn't stack
        lifetimes), plus clearing the "still available?" confirmation so a
        renewed post is asked again at its own next 14-day mark."""
        self.expires_at = datetime.utcnow() + timedelta(days=EXPIRES_DAYS[self.post_type])
        self.renewed_count += 1
        self.status = 'active'
        self.still_available_confirmed_at = None
        self.still_available_reminder_sent_at = None

    def __repr__(self):
        return f'TachlisPost({self.id}) [{self.post_type}] {self.title}'
