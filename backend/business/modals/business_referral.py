from config import db
from datetime import datetime


class BusinessReferralPost(db.Model):
    """A private vendor-referral board, visible only to users who own at
    least one claimed business (checked at the route level, not stored here)
    -- 'who do you use for X' among businesses that already trust the
    directory enough to have claimed a listing on it."""
    __tablename__ = 'business_referral_post'

    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(db.Integer, db.ForeignKey('business.id'), nullable=False, index=True)
    user_id = db.Column(db.String(50), db.ForeignKey('user.public_id'), nullable=False, index=True)
    title = db.Column(db.String(200), nullable=False)
    body = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    business = db.relationship('Business', backref=db.backref('referral_posts', lazy=True, cascade='all, delete-orphan'))
    user = db.relationship('User', foreign_keys=[user_id])
    replies = db.relationship('BusinessReferralReply', backref='post', lazy=True,
                               cascade='all, delete-orphan', order_by='BusinessReferralReply.created_at')

    def __init__(self, business_id, user_id, title, body):
        self.business_id = business_id
        self.user_id = user_id
        self.title = title
        self.body = body

    def __repr__(self):
        return f'BusinessReferralPost({self.id}) {self.title}'


class BusinessReferralReply(db.Model):
    __tablename__ = 'business_referral_reply'

    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey('business_referral_post.id'), nullable=False, index=True)
    business_id = db.Column(db.Integer, db.ForeignKey('business.id'), nullable=False)
    user_id = db.Column(db.String(50), db.ForeignKey('user.public_id'), nullable=False, index=True)
    body = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    business = db.relationship('Business', backref=db.backref('referral_replies', lazy=True, cascade='all, delete-orphan'))
    user = db.relationship('User', foreign_keys=[user_id])

    def __init__(self, post_id, business_id, user_id, body):
        self.post_id = post_id
        self.business_id = business_id
        self.user_id = user_id
        self.body = body

    def __repr__(self):
        return f'BusinessReferralReply({self.id}) post={self.post_id}'
