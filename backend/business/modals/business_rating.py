from config import db
from datetime import datetime


class BusinessRating(db.Model):
    __tablename__ = 'business_rating'

    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(db.Integer, db.ForeignKey('business.id'), nullable=False, index=True)
    user_id = db.Column(db.String(50), db.ForeignKey('user.public_id'), nullable=False, index=True)
    stars = db.Column(db.Integer, nullable=False)
    review_text = db.Column(db.Text, nullable=True)

    # True when the reviewer has a redeemed BusinessRedemption for this
    # business at the time the review is written -- see _recompute_rating's
    # caller in routes/business_rating.py. Not editable by the user; it's a
    # trust signal derived from real activity, not a claim they can make.
    verified = db.Column(db.Boolean, default=False, server_default='false', nullable=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('business_id', 'user_id', name='uq_business_rating_user'),
    )

    business = db.relationship('Business', backref=db.backref('ratings', lazy=True, cascade='all, delete-orphan'))
    user = db.relationship('User', backref=db.backref('business_ratings', lazy=True))

    def __init__(self, business_id, user_id, stars, review_text=None, verified=False):
        self.business_id = business_id
        self.user_id = user_id
        self.stars = stars
        self.review_text = review_text
        self.verified = verified

    def __repr__(self):
        return f'BusinessRating({self.id}) business={self.business_id} user={self.user_id} stars={self.stars}'
