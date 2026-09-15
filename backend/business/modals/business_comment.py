from config import db
from datetime import datetime


class BusinessComment(db.Model):
    __tablename__ = 'business_comment'

    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(db.Integer, db.ForeignKey('business.id'), nullable=False, index=True)
    user_id = db.Column(db.String(50), db.ForeignKey('user.public_id'), nullable=False, index=True)
    body = db.Column(db.Text, nullable=False)
    pub_date = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    # Visible by default -- a moderation takedown switch for admins, not a
    # pre-publish gate. Same pattern as HockComment.approved_to_publish.
    approved_to_publish = db.Column(db.Boolean, default=True, server_default='true', nullable=False)

    business = db.relationship('Business', backref=db.backref('comments', lazy=True, cascade='all, delete-orphan'))
    user = db.relationship('User', backref=db.backref('business_comments', lazy=True))

    def __init__(self, business_id, user_id, body):
        self.business_id = business_id
        self.user_id = user_id
        self.body = body

    def __repr__(self):
        return f'BusinessComment({self.id}) business={self.business_id} by={self.user_id}'
