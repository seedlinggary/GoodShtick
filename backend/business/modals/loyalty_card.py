import secrets

from config import db
from datetime import datetime


class LoyaltyCard(db.Model):
    """One digital punch-card per (business, customer). `customer_code` is
    what the customer shows (as a QR / typed code, see routes) and what an
    owner enters to add a stamp -- same pattern as BusinessRedemption.code.
    A business opts in via attributes.loyalty_enabled /
    attributes.loyalty_threshold / attributes.loyalty_reward on Business."""
    __tablename__ = 'loyalty_card'

    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(db.Integer, db.ForeignKey('business.id'), nullable=False, index=True)
    user_id = db.Column(db.String(50), db.ForeignKey('user.public_id'), nullable=False, index=True)
    customer_code = db.Column(db.String(12), nullable=False, unique=True, index=True)

    stamps = db.Column(db.Integer, nullable=False, default=0, server_default='0')
    rewards_redeemed = db.Column(db.Integer, nullable=False, default=0, server_default='0')

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('business_id', 'user_id', name='uq_loyalty_card_business_user'),
    )

    business = db.relationship('Business', backref=db.backref('loyalty_cards', lazy=True, cascade='all, delete-orphan'))
    user = db.relationship('User', foreign_keys=[user_id])

    def __init__(self, business_id, user_id, customer_code=None):
        self.business_id = business_id
        self.user_id = user_id
        self.customer_code = customer_code or self.generate_code()

    @staticmethod
    def generate_code():
        return secrets.token_hex(4).upper()

    def __repr__(self):
        return f'LoyaltyCard({self.id}) business={self.business_id} user={self.user_id} stamps={self.stamps}'
