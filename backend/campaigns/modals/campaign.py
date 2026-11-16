import secrets

from config import db
from datetime import datetime

CAMPAIGN_STATUSES = ('active', 'paused', 'ended')


class MarketingCampaign(db.Model):
    """One outbound campaign (e.g. 'Fall 2026 Facebook push') -- a container
    for CampaignLinks below. Not the same thing as backend/ads/modals/ad.py's
    Ad model, which is an in-site ad SHOWN to visitors on our own pages; this
    is the other direction -- links we hand out on other sites/channels that
    point back at us."""
    __tablename__ = 'marketing_campaign'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(10), nullable=False, default='active', server_default='active')
    created_by = db.Column(db.String(50), db.ForeignKey('user.public_id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    links = db.relationship('CampaignLink', backref='campaign', lazy=True, cascade='all, delete-orphan',
                             order_by='CampaignLink.created_at.desc()')

    def __repr__(self):
        return f'MarketingCampaign({self.id}) {self.name}'


class CampaignLink(db.Model):
    """One trackable link within a campaign. `code` is what appears in the
    actual shared URL (<API_BASE>/campaigns/r/<code>); `destination_url` is
    where it ultimately sends the visitor -- a full absolute URL (any of our
    6 hostnames, or elsewhere), chosen by whoever creates the link rather
    than resolved from a backend hostname registry, since only the frontend
    (src/siteMode.js) actually knows those at build time."""
    __tablename__ = 'campaign_link'

    id = db.Column(db.Integer, primary_key=True)
    campaign_id = db.Column(db.Integer, db.ForeignKey('marketing_campaign.id'), nullable=False, index=True)
    code = db.Column(db.String(16), nullable=False, unique=True, index=True)
    label = db.Column(db.String(160), nullable=False)
    destination_url = db.Column(db.String(500), nullable=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True, server_default='1')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    clicks = db.relationship('CampaignLinkClick', backref='link', lazy=True, cascade='all, delete-orphan')

    def __init__(self, campaign_id, label, destination_url, code=None):
        self.campaign_id = campaign_id
        self.label = label
        self.destination_url = destination_url
        self.code = code or self.generate_code()

    @staticmethod
    def generate_code():
        return secrets.token_hex(4)

    def __repr__(self):
        return f'CampaignLink({self.id}) {self.code} -> {self.destination_url}'


class CampaignLinkClick(db.Model):
    """Raw click log -- one row per hit on /campaigns/r/<code>, written
    before any frontend JS has had a chance to run. Deliberately separate
    from VisitorSession/VisitorEvent (backend/analytics/modals/visitor.py):
    those only exist once the frontend's beacon fires, so a visitor who
    clicks and bounces before the page finishes loading (or blocks the
    beacon) would otherwise vanish from the top of the funnel entirely."""
    __tablename__ = 'campaign_link_click'

    id = db.Column(db.Integer, primary_key=True)
    link_id = db.Column(db.Integer, db.ForeignKey('campaign_link.id'), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    referrer = db.Column(db.String(500), nullable=True)
    user_agent = db.Column(db.String(300), nullable=True)
    country = db.Column(db.String(100), nullable=True)

    def __repr__(self):
        return f'CampaignLinkClick({self.id}) link={self.link_id}'
