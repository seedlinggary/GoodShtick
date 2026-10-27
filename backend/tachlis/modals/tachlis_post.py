from config import db
from datetime import datetime

# Enforced at the Python/route level (not a Postgres enum) to match this
# project's convention of avoiding DB-level enums elsewhere.
POST_TYPES = ('job', 'resume')


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

    def __repr__(self):
        return f'TachlisPost({self.id}) [{self.post_type}] {self.title}'
