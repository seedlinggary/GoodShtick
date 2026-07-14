from config import db
from datetime import datetime

# Enforced at the Python/route level (not a Postgres enum) to match this
# project's convention of avoiding DB-level enums elsewhere.
POST_TYPES = ('job', 'resume', 'service')


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
    approved_to_publish = db.Column(db.Boolean, default=None)
    approved_by = db.Column(db.String(50), db.ForeignKey('user.public_id'), nullable=True)
    expires_at = db.Column(db.DateTime, nullable=True)

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
                 location=None, compensation=None, expires_at=None):
        self.post_type = post_type
        self.title = title
        self.body = body
        self.contact = contact
        self.user_id = user_id
        self.location = location
        self.compensation = compensation
        self.expires_at = expires_at

    def __repr__(self):
        return f'TachlisPost({self.id}) [{self.post_type}] {self.title}'
