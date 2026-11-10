from config import db
from datetime import datetime


class GreenInvoiceAccount(db.Model):
    """One Green Invoice (greeninvoice.co.il / 'morning') API key pair per
    business. Unlike Stripe/Google, Green Invoice auth is a plain API key +
    secret the owner generates inside their own Green Invoice account --
    no OAuth app, no admin-side credential row. The secret is encrypted at
    rest the same way a business's own OAuth tokens are (see
    social/crypto.py's encrypt_token/decrypt_token -- generic, not tied to
    social at all). `enabled` is the open/closed-style toggle: a row can
    exist with real, valid credentials and still be off, so an owner can
    pause real document creation without losing their saved keys."""
    __tablename__ = 'green_invoice_account'

    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(db.Integer, db.ForeignKey('business.id'), nullable=False, unique=True, index=True)

    api_key_id = db.Column(db.String(255), nullable=False)
    api_secret_enc = db.Column(db.Text, nullable=False)
    enabled = db.Column(db.Boolean, nullable=False, default=False, server_default='false')

    last_error = db.Column(db.Text, nullable=True)

    connected_by = db.Column(db.String(50), db.ForeignKey('user.public_id'), nullable=True)
    connected_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    business = db.relationship('Business', backref=db.backref('green_invoice_account', uselist=False, cascade='all, delete-orphan'))
    connector = db.relationship('User', foreign_keys=[connected_by])

    def __init__(self, business_id, api_key_id, api_secret_enc, enabled=False):
        self.business_id = business_id
        self.api_key_id = api_key_id
        self.api_secret_enc = api_secret_enc
        self.enabled = enabled

    def __repr__(self):
        return f'GreenInvoiceAccount({self.id}) business={self.business_id} [enabled={self.enabled}]'
