from config import db
from datetime import datetime

SOCIAL_PLATFORMS = ('facebook', 'instagram', 'google', 'x', 'linkedin', 'tiktok', 'whatsapp')

# Platforms with a real "post on behalf of the business" API this app calls
# directly (see business/social/publishers.py).
API_PLATFORMS = ('facebook', 'instagram', 'google', 'x', 'linkedin')
# No public posting API exists for these -- handled via a share-sheet handoff
# instead (compose once, hand the caption+image to the phone's native share
# sheet so the owner posts it themselves with one more tap).
SHARE_SHEET_PLATFORMS = ('tiktok', 'whatsapp')


class SocialAccount(db.Model):
    """One connected login per (business, platform). Tokens are stored
    encrypted at rest (see business/social/crypto.py) -- this table is the
    one place third-party credentials live in this codebase."""
    __tablename__ = 'social_account'

    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(db.Integer, db.ForeignKey('business.id'), nullable=False, index=True)
    platform = db.Column(db.String(20), nullable=False, index=True)

    external_account_id = db.Column(db.String(150), nullable=False)
    external_account_name = db.Column(db.String(150), nullable=True)

    access_token_enc = db.Column(db.Text, nullable=True)
    refresh_token_enc = db.Column(db.Text, nullable=True)
    expires_at = db.Column(db.DateTime, nullable=True)

    status = db.Column(db.String(20), nullable=False, default='active', server_default='active')
    last_error = db.Column(db.Text, nullable=True)

    connected_by = db.Column(db.String(50), db.ForeignKey('user.public_id'), nullable=True)
    connected_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('business_id', 'platform', name='uq_social_account_business_platform'),
    )

    business = db.relationship('Business', backref=db.backref('social_accounts', lazy=True, cascade='all, delete-orphan'))
    connector = db.relationship('User', foreign_keys=[connected_by])

    def __init__(self, business_id, platform, external_account_id, external_account_name=None,
                 access_token_enc=None, refresh_token_enc=None, expires_at=None, connected_by=None,
                 status='active'):
        self.business_id = business_id
        self.platform = platform
        self.external_account_id = external_account_id
        self.external_account_name = external_account_name
        self.access_token_enc = access_token_enc
        self.refresh_token_enc = refresh_token_enc
        self.expires_at = expires_at
        self.connected_by = connected_by
        self.status = status

    def __repr__(self):
        return f'SocialAccount({self.id}) business={self.business_id} [{self.platform}]'
