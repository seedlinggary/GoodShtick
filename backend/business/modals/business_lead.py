from config import db
from datetime import datetime

LEAD_STATUSES = ('new', 'read', 'archived')


class BusinessLead(db.Model):
    """A 'request a quote' submission -- for service businesses (caterers,
    contractors, photographers) where a phone call isn't the natural first
    step. Guests can submit (user_id is nullable); a logged-in user gets
    user_id recorded so a future 'my requests' view is possible without a
    migration."""
    __tablename__ = 'business_lead'

    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(db.Integer, db.ForeignKey('business.id'), nullable=False, index=True)
    user_id = db.Column(db.String(50), db.ForeignKey('user.public_id'), nullable=True, index=True)

    name = db.Column(db.String(150), nullable=False)
    email = db.Column(db.String(150), nullable=False)
    phone = db.Column(db.String(40), nullable=True)
    message = db.Column(db.Text, nullable=False)

    status = db.Column(db.String(20), nullable=False, default='new', server_default='new', index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    business = db.relationship('Business', backref=db.backref('leads', lazy=True, cascade='all, delete-orphan'))
    user = db.relationship('User', foreign_keys=[user_id])

    def __init__(self, business_id, name, email, message, user_id=None, phone=None):
        self.business_id = business_id
        self.user_id = user_id
        self.name = name
        self.email = email
        self.phone = phone
        self.message = message

    def __repr__(self):
        return f'BusinessLead({self.id}) business={self.business_id} [{self.status}]'
