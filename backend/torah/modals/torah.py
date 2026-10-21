import re
import unicodedata
from datetime import datetime

from config import db

POST_TYPES = ('text', 'video', 'image')
CATEGORIES = ('parsha', 'halacha', 'mussar', 'stories', 'holidays', 'other')
MAX_PHOTOS = 5

YOUTUBE_URL_RE = re.compile(
    r'(?:youtube\.com/(?:watch\?v=|embed/|shorts/)|youtu\.be/)([A-Za-z0-9_-]{11})'
)


def extract_youtube_id(url_or_id):
    """Accepts a full YouTube URL (watch/embed/shorts/youtu.be) or an already-
    bare 11-character video id, and returns just the id -- or None if nothing
    recognizable was found. No prior art for this existed elsewhere in the
    codebase (channel resolution in content_pipeline/routes/youtube.py is a
    different problem -- a channel, not a single video), so this is new."""
    if not url_or_id:
        return None
    url_or_id = url_or_id.strip()
    match = YOUTUBE_URL_RE.search(url_or_id)
    if match:
        return match.group(1)
    if re.fullmatch(r'[A-Za-z0-9_-]{11}', url_or_id):
        return url_or_id
    return None


def slugify(name):
    normalized = unicodedata.normalize('NFKD', name).encode('ascii', 'ignore').decode('ascii')
    slug = re.sub(r'[^a-z0-9]+', '-', normalized.lower()).strip('-')
    return slug or 'post'


class TorahPost(db.Model):
    """A user-submitted post -- text, a YouTube video, or up to MAX_PHOTOS
    photos (a post can combine a body_text with either a video or photos,
    e.g. a dvar torah with an illustrating picture; the `post_type` just
    drives which input the form foregrounds, not an exclusivity rule)."""
    __tablename__ = 'torah_post'

    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(170), unique=True, nullable=False, index=True)

    post_type = db.Column(db.String(10), nullable=False)  # POST_TYPES
    title = db.Column(db.String(150), nullable=False)
    body_text = db.Column(db.Text, nullable=True)
    youtube_video_id = db.Column(db.String(20), nullable=True)
    category = db.Column(db.String(20), nullable=False, default='other', server_default='other', index=True)

    created_by = db.Column(db.String(50), db.ForeignKey('user.public_id'), nullable=True, index=True)
    pub_date = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    views_count = db.Column(db.Integer, nullable=False, default=0, server_default='0')

    photos = db.relationship('TorahPostPhoto', backref='post', lazy=True,
                              cascade='all, delete-orphan', order_by='TorahPostPhoto.position')
    likes = db.relationship('TorahPostLike', backref='post', lazy=True, cascade='all, delete-orphan')
    creator = db.relationship('User', foreign_keys=[created_by], backref=db.backref('torah_posts', lazy=True))

    def __init__(self, slug, post_type, title, created_by=None, **kwargs):
        self.slug = slug
        self.post_type = post_type
        self.title = title
        self.created_by = created_by
        for key, value in kwargs.items():
            setattr(self, key, value)

    def __repr__(self):
        return f'TorahPost({self.id}) {self.title}'


class TorahPostPhoto(db.Model):
    __tablename__ = 'torah_post_photo'
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey('torah_post.id'), nullable=False, index=True)
    filename = db.Column(db.String(300), nullable=False)
    position = db.Column(db.Integer, nullable=False, default=0, server_default='0')

    def __init__(self, post_id, filename, position=0):
        self.post_id = post_id
        self.filename = filename
        self.position = position


class TorahPostLike(db.Model):
    __tablename__ = 'torah_post_like'
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey('torah_post.id'), nullable=False, index=True)
    user_id = db.Column(db.String(50), db.ForeignKey('user.public_id'), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('post_id', 'user_id', name='uq_torah_post_like_post_user'),
    )

    user = db.relationship('User', backref=db.backref('liked_torah_posts', lazy=True))

    def __init__(self, post_id, user_id):
        self.post_id = post_id
        self.user_id = user_id


class SefariaCache(db.Model):
    """Generic cache for Sefaria API responses (index/book-schema/text),
    keyed by a string like 'index' or 'text:Genesis.1.1'. Sefaria's own API
    is free with no stated hard rate limit, unlike Alpha Vantage, but the
    index/book-schema responses in particular are large and essentially
    static, so caching them is still the right call for latency -- not a
    quota-survival necessity the way finance_data_cache is."""
    __tablename__ = 'sefaria_cache'

    id = db.Column(db.Integer, primary_key=True)
    cache_key = db.Column(db.String(300), unique=True, nullable=False, index=True)
    payload = db.Column(db.JSON, nullable=False)
    fetched_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def __init__(self, cache_key, payload):
        self.cache_key = cache_key
        self.payload = payload
