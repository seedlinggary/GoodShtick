from config import db
from datetime import datetime

SOCIAL_POST_STATUSES = ('draft', 'scheduled', 'posted', 'failed', 'partial')
TARGET_STATUSES = ('pending', 'posted', 'failed', 'share_pending')


class SocialPost(db.Model):
    """One composed post, platform-agnostic -- what actually reaches each
    platform is tracked per-target in SocialPostTarget below."""
    __tablename__ = 'social_post'

    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(db.Integer, db.ForeignKey('business.id'), nullable=False, index=True)
    created_by = db.Column(db.String(50), db.ForeignKey('user.public_id'), nullable=False)

    caption = db.Column(db.Text, nullable=False)
    # Raw Supabase Storage filename -- resolved via get_public_url(), same
    # pattern as Business.logo.
    media = db.Column(db.String(300), nullable=True)
    link_url = db.Column(db.String(500), nullable=True)

    scheduled_at = db.Column(db.DateTime, nullable=True, index=True)
    status = db.Column(db.String(20), nullable=False, default='draft', server_default='draft', index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    business = db.relationship('Business', backref=db.backref('social_posts', lazy=True, cascade='all, delete-orphan'))
    author = db.relationship('User', foreign_keys=[created_by])
    targets = db.relationship('SocialPostTarget', backref='post', lazy=True, cascade='all, delete-orphan')

    def __init__(self, business_id, created_by, caption, media=None, link_url=None,
                 scheduled_at=None, status='draft'):
        self.business_id = business_id
        self.created_by = created_by
        self.caption = caption
        self.media = media
        self.link_url = link_url
        self.scheduled_at = scheduled_at
        self.status = status

    def __repr__(self):
        return f'SocialPost({self.id}) business={self.business_id} [{self.status}]'


class SocialPostTarget(db.Model):
    """One row per platform a SocialPost was sent to. `social_account_id` is
    null for share-sheet-only platforms (tiktok/whatsapp), which never go
    through a stored connected account."""
    __tablename__ = 'social_post_target'

    id = db.Column(db.Integer, primary_key=True)
    social_post_id = db.Column(db.Integer, db.ForeignKey('social_post.id'), nullable=False, index=True)
    social_account_id = db.Column(db.Integer, db.ForeignKey('social_account.id'), nullable=True, index=True)
    platform = db.Column(db.String(20), nullable=False)

    status = db.Column(db.String(20), nullable=False, default='pending', server_default='pending', index=True)
    remote_post_id = db.Column(db.String(150), nullable=True)
    error = db.Column(db.Text, nullable=True)
    posted_at = db.Column(db.DateTime, nullable=True)

    account = db.relationship('SocialAccount')

    def __init__(self, social_post_id, platform, social_account_id=None, status='pending'):
        self.social_post_id = social_post_id
        self.platform = platform
        self.social_account_id = social_account_id
        self.status = status

    def __repr__(self):
        return f'SocialPostTarget({self.id}) post={self.social_post_id} [{self.platform}:{self.status}]'
