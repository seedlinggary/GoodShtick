from config import db
from datetime import datetime


def identity_key(customer_user_id=None, guest_email=None, guest_phone=None):
    """One stable string identifying a customer across Order/Appointment --
    a real account (user:<public_id>) or a guest (guest:<email-or-phone>,
    lowercased for email). Used both to group CRM rows and to key
    CustomerNote, so there's one definition of "who this is" shared by
    both instead of two slightly-different joins."""
    if customer_user_id:
        return f'user:{customer_user_id}'
    if guest_email:
        return f'guest:{guest_email.strip().lower()}'
    if guest_phone:
        return f'guest:{guest_phone.strip()}'
    return 'unknown'


class CustomerNote(db.Model):
    """A free-text note an owner leaves on a customer -- the one genuinely
    new piece of CRM data this feature needed (everything else the CRM
    view shows -- orders, appointments, loyalty stamps -- already exists
    as its own model; see routes/crm.py)."""
    __tablename__ = 'customer_note'

    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(db.Integer, db.ForeignKey('business.id'), nullable=False, index=True)
    identity_key = db.Column(db.String(200), nullable=False, index=True)

    note = db.Column(db.Text, nullable=False)
    created_by = db.Column(db.String(50), db.ForeignKey('user.public_id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    business = db.relationship('Business', backref=db.backref('customer_notes', lazy=True, cascade='all, delete-orphan'))
    creator = db.relationship('User', foreign_keys=[created_by])

    def __init__(self, business_id, identity_key, note, created_by=None):
        self.business_id = business_id
        self.identity_key = identity_key
        self.note = note
        self.created_by = created_by

    def __repr__(self):
        return f'CustomerNote({self.id}) business={self.business_id} identity={self.identity_key!r}'
