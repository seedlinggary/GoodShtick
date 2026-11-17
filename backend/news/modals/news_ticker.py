from datetime import datetime

from config import db

# A ticker item is a one-line blurb, not a full post -- kept short so the
# scrolling strip (see src/news/NewsTicker.js) stays skimmable instead of
# turning into a second feed. Word count (not just a char cap) is what
# actually keeps it short: a handful of long words can still blow past a
# reasonable reading length even under a generous character limit.
TICKER_TEXT_MAX_WORDS = 15
TICKER_TEXT_MAX_LEN = 240


class NewsTickerItem(db.Model):
    """A short scrolling headline for GutKol's ticker bar -- deliberately
    NOT a NewsArticle: no slug, body, likes, or moderation queue of its
    own, just a line of text an admin/bot wrote directly (see
    routes/news_ticker.py's normalize/validate helpers for the word-count
    cap) and an optional link (to one of GutKol's own articles, or
    anywhere else). `is_active` lets an admin retire an item without
    losing it -- same soft-hide pattern as NewsArticle.approved_to_publish,
    just a plain bool here since there's no moderation queue to distinguish
    "pending" from "off"."""
    __tablename__ = 'news_ticker_item'

    id = db.Column(db.Integer, primary_key=True)
    text = db.Column(db.String(TICKER_TEXT_MAX_LEN), nullable=False)
    link_url = db.Column(db.String(500), nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True, server_default='true', index=True)

    created_by = db.Column(db.String(50), db.ForeignKey('user.public_id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    creator = db.relationship('User', foreign_keys=[created_by])

    def __init__(self, text, created_by=None, **kwargs):
        self.text = text
        self.created_by = created_by
        for key, value in kwargs.items():
            setattr(self, key, value)

    def __repr__(self):
        return f'NewsTickerItem({self.id}) {self.text[:30]!r}'
