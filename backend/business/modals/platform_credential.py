from config import db
from datetime import datetime


class PlatformCredential(db.Model):
    """Platform-wide (not per-business) OAuth app credentials for the Social
    Desk -- one row per platform (facebook/instagram share the same Meta
    app, so they're stored under 'facebook'). Lets an admin configure these
    from the UI instead of needing shell/hosting access to set environment
    variables, which is what social/publishers.py fell back to before this
    existed. The client secret is encrypted at rest the same way a business's
    own OAuth tokens are (see social/crypto.py)."""
    __tablename__ = 'platform_credential'

    platform = db.Column(db.String(20), primary_key=True)
    client_id = db.Column(db.Text, nullable=False)
    client_secret_enc = db.Column(db.Text, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    updated_by = db.Column(db.String(50), db.ForeignKey('user.public_id'), nullable=True)

    def __init__(self, platform, client_id, client_secret_enc, updated_by=None):
        self.platform = platform
        self.client_id = client_id
        self.client_secret_enc = client_secret_enc
        self.updated_by = updated_by

    def __repr__(self):
        return f'PlatformCredential({self.platform})'
