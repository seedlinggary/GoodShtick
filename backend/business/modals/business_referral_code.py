import secrets

from config import db
from datetime import datetime


class BusinessReferral(db.Model):
    """A customer's personal 'refer a friend' code for one business --
    Business.attributes.referral_reward is the owner-written description of
    what both sides get (e.g. '10% off'), granted informally by the owner
    when they see the referral in their dashboard, same trust-based pattern
    as boosted placement -- no discount/payment engine involved."""
    __tablename__ = 'business_referral'

    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(db.Integer, db.ForeignKey('business.id'), nullable=False, index=True)
    referrer_user_id = db.Column(db.String(50), db.ForeignKey('user.public_id'), nullable=False, index=True)
    code = db.Column(db.String(12), nullable=False, unique=True, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('business_id', 'referrer_user_id', name='uq_referral_business_user'),
    )

    business = db.relationship('Business', backref=db.backref('referrals', lazy=True, cascade='all, delete-orphan'))
    referrer = db.relationship('User', foreign_keys=[referrer_user_id])
    uses = db.relationship('BusinessReferralUse', backref='referral', lazy=True, cascade='all, delete-orphan')

    def __init__(self, business_id, referrer_user_id, code=None):
        self.business_id = business_id
        self.referrer_user_id = referrer_user_id
        self.code = code or self.generate_code()

    @staticmethod
    def generate_code():
        return secrets.token_hex(4).upper()

    def __repr__(self):
        return f'BusinessReferral({self.id}) business={self.business_id} referrer={self.referrer_user_id}'


class BusinessReferralUse(db.Model):
    """One row per person who's redeemed a deal via someone else's referral
    code -- the unique constraint is what stops the same person being
    counted twice for the same referral."""
    __tablename__ = 'business_referral_use'

    id = db.Column(db.Integer, primary_key=True)
    referral_id = db.Column(db.Integer, db.ForeignKey('business_referral.id'), nullable=False, index=True)
    referred_user_id = db.Column(db.String(50), db.ForeignKey('user.public_id'), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('referral_id', 'referred_user_id', name='uq_referral_use'),
    )

    referred_user = db.relationship('User', foreign_keys=[referred_user_id])

    def __init__(self, referral_id, referred_user_id):
        self.referral_id = referral_id
        self.referred_user_id = referred_user_id

    def __repr__(self):
        return f'BusinessReferralUse({self.id}) referral={self.referral_id} referred={self.referred_user_id}'
