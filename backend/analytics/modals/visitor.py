from config import db
from datetime import datetime


class VisitorSession(db.Model):
    """One row per anonymous visitor (identified by a cookie token), regardless
    of how many page views they rack up — page_view_count/last_seen just get
    bumped in place. If the visitor logs in, user_id gets backfilled so
    anonymous-then-authenticated activity can be linked without needing to
    merge/duplicate the row."""
    __tablename__ = 'visitor_session'

    id = db.Column(db.Integer, primary_key=True)
    anonymous_id = db.Column(db.String(64), nullable=False, index=True)
    user_id = db.Column(db.String(50), db.ForeignKey('user.public_id'), nullable=True)
    country = db.Column(db.String(100), nullable=True)
    first_seen = db.Column(db.DateTime, default=datetime.utcnow)
    last_seen = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    page_view_count = db.Column(db.Integer, default=0)
    is_localhost = db.Column(db.Boolean, default=False)

    def __repr__(self):
        return f'<VisitorSession {self.anonymous_id[:8]}... user={self.user_id}>'


class VisitorEvent(db.Model):
    """One row per tracked action. anonymous_id is a loose reference (no FK) to
    VisitorSession.anonymous_id -- sessions and events are written independently
    so a beacon that races ahead of/behind its session upsert never fails.
    event_type is free text (not a DB enum) on purpose: 'page_view' today,
    'like'/'comment'/'game_play'/'ad_click' etc. later, with no migration
    needed to add a new value."""
    __tablename__ = 'visitor_event'

    id = db.Column(db.Integer, primary_key=True)
    anonymous_id = db.Column(db.String(64), nullable=False, index=True)
    event_type = db.Column(db.String(30), nullable=False)
    path = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    def __repr__(self):
        return f'<VisitorEvent {self.event_type} {self.anonymous_id[:8]}...>'
