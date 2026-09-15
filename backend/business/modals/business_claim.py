from config import db
from datetime import datetime

CLAIM_STATUSES = ('pending', 'approved', 'rejected')


class BusinessClaim(db.Model):
    __tablename__ = 'business_claim'

    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(db.Integer, db.ForeignKey('business.id'), nullable=False, index=True)
    user_id = db.Column(db.String(50), db.ForeignKey('user.public_id'), nullable=False, index=True)
    status = db.Column(db.String(20), nullable=False, default='pending', server_default='pending', index=True)
    message = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    reviewed_by = db.Column(db.String(50), db.ForeignKey('user.public_id'), nullable=True)
    reviewed_at = db.Column(db.DateTime, nullable=True)

    business = db.relationship('Business', backref=db.backref('claims', lazy=True, cascade='all, delete-orphan'))
    user = db.relationship('User', foreign_keys=[user_id], backref=db.backref('business_claims', lazy=True))
    reviewer = db.relationship('User', foreign_keys=[reviewed_by])

    def __init__(self, business_id, user_id, message=None):
        self.business_id = business_id
        self.user_id = user_id
        self.message = message

    def __repr__(self):
        return f'BusinessClaim({self.id}) business={self.business_id} user={self.user_id} [{self.status}]'
