from datetime import datetime

from config import db

# Enforced at the Python/route level, same convention as CADENCES/POST_STATUSES
# elsewhere in this codebase rather than a DB enum.
BANNER_STYLES = ('info', 'success', 'warning', 'urgent')


class SiteBanner(db.Model):
    """Single-row table (id is always 1) holding the super-admin-editable
    site-wide announcement banner shown above the navbar on every one of
    GUT's 5 sites -- same shared React bundle/backend, same single-row
    settings pattern as AlertDigestSchedule (see
    backend/alerts/modals/alert.py).

    A visitor's dismissal is tracked client-side only (localStorage), keyed
    off updated_at -- editing the message while enabled bumps updated_at,
    which brings the banner back even for someone who already dismissed the
    previous version, with no server-side per-visitor state needed."""
    __tablename__ = 'site_banner'

    id = db.Column(db.Integer, primary_key=True)
    enabled = db.Column(db.Boolean, nullable=False, default=False, server_default='false')
    message = db.Column(db.Text, nullable=True)
    link_url = db.Column(db.String(500), nullable=True)
    link_text = db.Column(db.String(60), nullable=True)
    style = db.Column(db.String(20), nullable=False, default='info', server_default='info')
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f'<SiteBanner enabled={self.enabled} style={self.style}>'
