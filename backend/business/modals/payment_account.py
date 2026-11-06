from config import db
from datetime import datetime

# Enforced at the Python level, not a DB enum -- same convention as
# Business.BUSINESS_CATEGORIES. 'stripe' is the only one actually
# implemented (see backend/business/payments/providers/); the other three
# are valid values today so a future rollout of any of them needs no
# migration, just a real provider module to replace its current stub.
PAYMENT_PROVIDERS = ('stripe', 'nedarim_plus', 'payme', 'paypal')

PAYMENT_ACCOUNT_STATUSES = ('pending', 'active', 'restricted', 'disabled')


class PaymentAccount(db.Model):
    """One payment processor connection per business -- what a storefront
    checkout or booking payment (Phase 4/5) charges against. Deliberately
    stores only the connected account's id, not an OAuth access/refresh
    token: Stripe Connect direct charges (see providers/stripe.py) only
    need stripe_account=<id> alongside this platform's own secret key, so
    there's no token to encrypt/leak/rotate for this provider at all --
    unlike social_account.py's tokens, which really do need to be stored
    (posting on the business's behalf requires acting as their login)."""
    __tablename__ = 'payment_account'

    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(db.Integer, db.ForeignKey('business.id'), nullable=False, unique=True, index=True)

    provider = db.Column(db.String(32), nullable=False, default='stripe', server_default='stripe', index=True)
    external_account_id = db.Column(db.String(255), nullable=True)
    status = db.Column(db.String(20), nullable=False, default='pending', server_default='pending', index=True)

    # Provider-specific, non-secret metadata for display (e.g. Stripe's
    # charges_enabled/payouts_enabled/business name) -- never a credential.
    details = db.Column(db.JSON, nullable=True)

    connected_by = db.Column(db.String(50), db.ForeignKey('user.public_id'), nullable=True)
    connected_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    business = db.relationship('Business', backref=db.backref('payment_account', uselist=False, cascade='all, delete-orphan'))
    connector = db.relationship('User', foreign_keys=[connected_by])

    def __init__(self, business_id, provider='stripe'):
        self.business_id = business_id
        self.provider = provider

    def __repr__(self):
        return f'PaymentAccount({self.id}) business={self.business_id} [{self.provider}:{self.status}]'
