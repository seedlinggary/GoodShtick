import re
import unicodedata
from datetime import datetime

from sqlalchemy.dialects.postgresql import ARRAY

from config import db

# The owner's own preset split for GutKol's articles (bot-generated content
# included), plus a catch-all 'other' for anything that doesn't cleanly fit
# one of these. NOT an exhaustive enum -- a poster who can't find a fit can
# type their own category instead (see news_article.py's create_article/
# edit_article, which accept any normalized custom string too), so the
# `categories` column is NOT constrained to this tuple at the DB level. This
# list is just what's offered as ready-made choices before "add your own."
CATEGORIES = ('finance', 'political', 'american', 'international', 'technology', 'health', 'other')

CATEGORY_MAX_LEN = 40

# An article can carry more than one topic (e.g. a story that's both
# "finance" and "political"), but not an unbounded tag list -- the owner's
# own cap, enforced centrally in normalize_categories() below so every
# create/edit route gets it for free rather than re-checking it themselves.
MAX_CATEGORIES = 3


def slugify(name):
    normalized = unicodedata.normalize('NFKD', name).encode('ascii', 'ignore').decode('ascii')
    slug = re.sub(r'[^a-z0-9]+', '-', normalized.lower()).strip('-')
    return slug or 'article'


def normalize_category(raw):
    """Lowercases/trims a single category (preset or custom-typed) so the
    same topic always lands as the same string -- matters once a poster can
    type their own instead of picking from CATEGORIES, since "Pop Culture"
    and "pop culture" need to be the same filter, not two. Collapses
    internal whitespace too, and truncates to the column's own max length."""
    cleaned = re.sub(r'\s+', ' ', (raw or '').strip().lower())
    return cleaned[:CATEGORY_MAX_LEN]


def normalize_categories(raw_list):
    """Same normalization as normalize_category(), applied to a whole list
    -- dedupes (preserving the order picked) and caps at MAX_CATEGORIES, so
    a request can't bypass the limit by just sending a longer list. Returns
    [] for anything falsy/not iterable, never raises on a malformed body."""
    cleaned = []
    for raw in (raw_list or []):
        c = normalize_category(raw)
        if c and c not in cleaned:
            cleaned.append(c)
        if len(cleaned) >= MAX_CATEGORIES:
            break
    return cleaned


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
    # A Postgres array, not a join table -- at this app's traffic scale
    # (see _public_filter's own note on the rest of this file) a plain
    # array column with the `@>`-style containment filter list_articles
    # uses is simpler than a many-to-many table for a 1-3 element tag list,
    # and GIN-indexable if it ever needs to be.
    categories = db.Column(ARRAY(db.String(CATEGORY_MAX_LEN)), nullable=False, default=list, server_default='{}')

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

    # Guest ("post without an account") fields -- only set when created_by
    # is None (see routes/news_article.py's create_guest_article).
    # guest_manage_token is the no-login credential: a private link emailed
    # to the poster (see backend/alerts/emails.py's
    # send_guest_submission_email) that lets them view/edit/delete this
    # article purely by presenting the token, same shape as TachlisPost's
    # still_available_token.
    guest_email = db.Column(db.String(150), nullable=True)
    guest_phone = db.Column(db.String(40), nullable=True)
    guest_manage_token = db.Column(db.String(64), nullable=True, unique=True, index=True)

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
