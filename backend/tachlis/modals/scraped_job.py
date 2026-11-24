from config import db
from datetime import datetime


class ScrapedJob(db.Model):
    """Dedup record for one job pulled from an external source (API or
    scrape). Checked before creating a new TachlisPost so re-running a
    scraper (daily, via cron) never reposts the same job twice. Exact same
    shape as backend/content_pipeline/modals/scraped_article.py's
    ScrapedArticle, swapping shtick_id for tachlis_post_id."""
    __tablename__ = 'scraped_job'

    id = db.Column(db.Integer, primary_key=True)
    source = db.Column(db.String(50), nullable=False)  # e.g. 'arbeitnow' | 'remoteok' | 'jobicy' | 'alljobs'
    url = db.Column(db.String(500), nullable=False)
    title = db.Column(db.String(300))
    tachlis_post_id = db.Column(db.Integer, db.ForeignKey('tachlis_post.id'), nullable=True)
    scraped_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (db.UniqueConstraint('source', 'url', name='uq_scraped_job_source_url'),)

    def __init__(self, source, url, title=None, tachlis_post_id=None):
        self.source = source
        self.url = url
        self.title = title
        self.tachlis_post_id = tachlis_post_id
