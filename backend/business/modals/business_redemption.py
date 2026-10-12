import secrets

from config import db
from datetime import datetime

REDEMPTION_STATUSES = ('issued', 'redeemed')


class BusinessRedemption(db.Model):
    """Issued when a logged-in customer taps 'Get this deal' on a
    BusinessPost. `code` is what the QR encodes and what an owner
    types/scans to mark it redeemed. Triple duty: the customer's deal wallet
    (their issued/redeemed rows with the post's own expires_at), the
    owner's redemption analytics, and the source of truth for a review's
    `verified` flag (see BusinessRating.verified)."""
    __tablename__ = 'business_redemption'

    id = db.Column(db.Integer, primary_key=True)
    business_post_id = db.Column(db.Integer, db.ForeignKey('business_post.id'), nullable=False, index=True)
    business_id = db.Column(db.Integer, db.ForeignKey('business.id'), nullable=False, index=True)
    user_id = db.Column(db.String(50), db.ForeignKey('user.public_id'), nullable=False, index=True)

    code = db.Column(db.String(12), nullable=False, unique=True, index=True)
    status = db.Column(db.String(20), nullable=False, default='issued', server_default='issued', index=True)

    issued_at = db.Column(db.DateTime, default=datetime.utcnow)
    redeemed_at = db.Column(db.DateTime, nullable=True)

    __table_args__ = (
        db.UniqueConstraint('business_post_id', 'user_id', name='uq_redemption_post_user'),
    )

    post = db.relationship('BusinessPost', backref=db.backref('redemptions', lazy=True, cascade='all, delete-orphan'))
    business = db.relationship('Business', backref=db.backref('redemptions', lazy=True, cascade='all, delete-orphan'))
    user = db.relationship('User', foreign_keys=[user_id], backref=db.backref('deal_redemptions', lazy=True))

    def __init__(self, business_post_id, business_id, user_id, code=None):
        self.business_post_id = business_post_id
        self.business_id = business_id
        self.user_id = user_id
        self.code = code or self.generate_code()

    @staticmethod
    def generate_code():
        return secrets.token_hex(4).upper()  # 8 hex chars, e.g. "A1B2C3D4"

    def __repr__(self):
        return f'BusinessRedemption({self.id}) post={self.business_post_id} user={self.user_id} [{self.status}]'
