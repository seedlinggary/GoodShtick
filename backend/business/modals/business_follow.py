from config import db
from datetime import datetime


class BusinessFollow(db.Model):
    """A customer following a business -- what a follower count/broadcast
    list is built from, and the gate for the 'new deal' notify() a business
    fires when it broadcasts an update (see routes/business_follow.py)."""
    __tablename__ = 'business_follow'

    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(db.Integer, db.ForeignKey('business.id'), nullable=False, index=True)
    user_id = db.Column(db.String(50), db.ForeignKey('user.public_id'), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('business_id', 'user_id', name='uq_follow_business_user'),
    )

    business = db.relationship('Business', backref=db.backref('followers', lazy=True, cascade='all, delete-orphan'))
    user = db.relationship('User', backref=db.backref('followed_businesses', lazy=True))

    def __init__(self, business_id, user_id):
        self.business_id = business_id
        self.user_id = user_id

    def __repr__(self):
        return f'BusinessFollow(business={self.business_id} user={self.user_id})'
