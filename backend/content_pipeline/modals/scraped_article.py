from config import db
from datetime import datetime


class ScrapedArticle(db.Model):
    """Dedup record for one article pulled from an external news source.
    Checked before creating a new pending Shtick so re-running a scraper
    never reposts the same article twice."""
    __tablename__ = 'scraped_article'

    id = db.Column(db.Integer, primary_key=True)
    source = db.Column(db.String(50), nullable=False)  # e.g. 'israelnationalnews' | 'yeshivaworld' | 'dansdeals'
    url = db.Column(db.String(500), nullable=False)
    title = db.Column(db.String(300))
    shtick_id = db.Column(db.Integer, db.ForeignKey('shtick.id'), nullable=True)
    scraped_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (db.UniqueConstraint('source', 'url', name='uq_scraped_article_source_url'),)

    def __init__(self, source, url, title=None, shtick_id=None):
        self.source = source
        self.url = url
        self.title = title
        self.shtick_id = shtick_id
