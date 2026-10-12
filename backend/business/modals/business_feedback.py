from config import db
from datetime import datetime


class BusinessFeedback(db.Model):
    """Private feedback -- the low-star half of the review funnel (see
    routes/business_feedback.py). A public rating still goes through
    BusinessRating; this exists so a 1-3 star experience reaches the owner
    directly instead of becoming a public review, while a 4-5 star one gets
    routed to the business's real Google review link instead."""
    __tablename__ = 'business_feedback'

    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(db.Integer, db.ForeignKey('business.id'), nullable=False, index=True)
    user_id = db.Column(db.String(50), db.ForeignKey('user.public_id'), nullable=False, index=True)
    stars = db.Column(db.Integer, nullable=False)
    comment = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    business = db.relationship('Business', backref=db.backref('feedback', lazy=True, cascade='all, delete-orphan'))
    user = db.relationship('User', foreign_keys=[user_id])

    def __init__(self, business_id, user_id, stars, comment=None):
        self.business_id = business_id
        self.user_id = user_id
        self.stars = stars
        self.comment = comment

    def __repr__(self):
        return f'BusinessFeedback({self.id}) business={self.business_id} stars={self.stars}'
