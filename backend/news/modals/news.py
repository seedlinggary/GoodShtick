import re
import unicodedata
from datetime import datetime

from config import db

CATEGORIES = ('world', 'politics', 'business', 'science', 'health', 'sports', 'entertainment', 'other')


def slugify(name):
    normalized = unicodedata.normalize('NFKD', name).encode('ascii', 'ignore').decode('ascii')
    slug = re.sub(r'[^a-z0-9]+', '-', normalized.lower()).strip('-')
    return slug or 'article'


class NewsArticle(db.Model):
    """Either a scraped headline (imported=True, from news_scraper.py --
    mirrors content_pipeline/routes/scraper.py's Shtick pipeline, just
    landing in this site's own model instead) or a user-submitted post
    (imported=False). Scraped articles sit in a pending-approval queue
    (approved_to_publish starts NULL) the same way Shtick's scraper output
    does -- third-party headlines get a human check before going public.
    User posts publish immediately (approved_to_publish=True at creation),
    consistent with every other self-attributed content type in this app
    (Estates listings, Torah posts, ...) -- there's nothing to impersonate
    in your own byline the way there is in someone else's headline."""
    __tablename__ = 'news_article'

    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(170), unique=True, nullable=False, index=True)

    title = db.Column(db.String(200), nullable=False)
    excerpt = db.Column(db.Text, nullable=True)
    body_text = db.Column(db.Text, nullable=True)
    image = db.Column(db.String(300), nullable=True)
    category = db.Column(db.String(20), nullable=False, default='other', server_default='other', index=True)

    imported = db.Column(db.Boolean, default=False, server_default='false', nullable=False, index=True)
    source_url = db.Column(db.String(500), nullable=True)
    source_name = db.Column(db.String(150), nullable=True)
    # NULL = pending review (only meaningful when imported=True); True/False
    # once a super-admin has acted. User posts (imported=False) are created
    # with this already True -- see class docstring.
    approved_to_publish = db.Column(db.Boolean, nullable=True, index=True)

    created_by = db.Column(db.String(50), db.ForeignKey('user.public_id'), nullable=True, index=True)
    pub_date = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    views_count = db.Column(db.Integer, nullable=False, default=0, server_default='0')

    likes = db.relationship('NewsArticleLike', backref='article', lazy=True, cascade='all, delete-orphan')
    creator = db.relationship('User', foreign_keys=[created_by], backref=db.backref('news_articles', lazy=True))

    def __init__(self, slug, title, created_by=None, **kwargs):
        self.slug = slug
        self.title = title
        self.created_by = created_by
        for key, value in kwargs.items():
            setattr(self, key, value)

    def __repr__(self):
        return f'NewsArticle({self.id}) {self.title}'


class NewsArticleLike(db.Model):
    __tablename__ = 'news_article_like'
    id = db.Column(db.Integer, primary_key=True)
    article_id = db.Column(db.Integer, db.ForeignKey('news_article.id'), nullable=False, index=True)
    user_id = db.Column(db.String(50), db.ForeignKey('user.public_id'), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('article_id', 'user_id', name='uq_news_article_like_article_user'),
    )

    user = db.relationship('User', backref=db.backref('liked_news_articles', lazy=True))

    def __init__(self, article_id, user_id):
        self.article_id = article_id
        self.user_id = user_id
