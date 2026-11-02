import re
import unicodedata
from datetime import datetime, timedelta

from config import db

# Two-level taxonomy, enforced at the Python level (not a DB enum) -- same
# convention as BUSINESS_CATEGORIES/LISTING_TYPES elsewhere in this
# codebase. GET /marketplace/categories hands this exact dict to the
# frontend so its cascading category->subcategory selects can never drift
# from what the backend actually accepts.
MARKETPLACE_CATEGORIES = {
    'baby_kids': {
        'label': 'Baby & Kids',
        'subcategories': ['Strollers & Car Seats', 'Cribs & Nursery', 'Kids Clothing', 'Toys & Games', 'Baby Gear'],
    },
    'furniture_home': {
        'label': 'Furniture & Home',
        'subcategories': ['Living Room', 'Bedroom', 'Kitchen & Dining', 'Appliances', 'Home Decor', 'Rugs & Curtains'],
    },
    'judaica_seforim': {
        'label': 'Judaica & Seforim',
        'subcategories': ['Seforim', 'Judaica & Ritual Items', 'Tefillin & Mezuzahs', 'Jewelry'],
    },
    'clothing_shoes': {
        'label': 'Clothing & Shoes',
        'subcategories': ["Men's", "Women's", "Kids'", 'Shoes & Accessories'],
    },
    'electronics': {
        'label': 'Electronics',
        'subcategories': ['Computers & Tablets', 'Phones', 'TVs & Audio', 'Cameras'],
    },
    'vehicles': {
        'label': 'Vehicles',
        'subcategories': ['Cars', 'Bikes & Scooters', 'Car Seats & Accessories'],
    },
    'sports_outdoors': {
        'label': 'Sports & Outdoors',
        'subcategories': ['Exercise Equipment', 'Outdoor Gear', 'Sporting Goods'],
    },
    'simcha_events': {
        'label': 'Simcha & Events',
        'subcategories': ['Gowns & Formal Wear', 'Event Decor', 'Gift Items'],
    },
    'books_media': {
        'label': 'Books & Media',
        'subcategories': ['Books', 'Music', 'Games'],
    },
    'tickets_experiences': {
        'label': 'Tickets & Experiences',
        'subcategories': ['Event Tickets', 'Travel'],
    },
    'free': {
        'label': 'Free / Giveaway',
        'subcategories': [],
    },
    'other': {
        'label': 'Other',
        'subcategories': [],
    },
}

CONDITIONS = ('new', 'like_new', 'good', 'fair', 'for_parts')
CONDITION_LABELS = {
    'new': 'New', 'like_new': 'Like New', 'good': 'Good', 'fair': 'Fair', 'for_parts': 'For Parts',
}
CURRENCIES = ('USD', 'ILS')
MAX_PHOTOS = 6
LISTING_LIFETIME_DAYS = 45
SAVED_STATUSES = ('saved', 'contacted', 'picked_up')
NOTE_MAX = 500
MARKETPLACE_STATUSES = ('active', 'sold', 'traded', 'expired')


def slugify(name):
    normalized = unicodedata.normalize('NFKD', name).encode('ascii', 'ignore').decode('ascii')
    slug = re.sub(r'[^a-z0-9]+', '-', normalized.lower()).strip('-')
    return slug or 'item'


class MarketplaceListing(db.Model):
    """A single buy/sell/trade/giveaway item. Goes live immediately on
    creation, same open philosophy as EstatesListing/Business/Community --
    an unclaimed directory-style post, nothing to impersonate yet. Default
    45-day lifetime (see EXPIRES_AT below / renew()), same role as
    EstatesListing's own expiry -- keeps stale "still have this?" posts
    from cluttering search without ever deleting the row."""
    __tablename__ = 'marketplace_listing'

    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(170), unique=True, nullable=False, index=True)

    title = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text, nullable=True)
    category = db.Column(db.String(30), nullable=False, index=True)  # MARKETPLACE_CATEGORIES key
    subcategory = db.Column(db.String(60), nullable=True, index=True)
    condition = db.Column(db.String(20), nullable=True)  # CONDITIONS

    price = db.Column(db.Float, nullable=True)
    currency = db.Column(db.String(3), nullable=False, default='USD', server_default='USD')
    is_free = db.Column(db.Boolean, nullable=False, default=False, server_default='false', index=True)

    # A shippable item (seforim, Judaica, jewelry) stays findable by
    # category/keyword search for a buyer anywhere in the world; a
    # pickup-only item (furniture, a couch) is properly distance-filtered
    # instead -- see routes/marketplace.py's list_listings for how this
    # interacts with the "near me" radius search.
    ships = db.Column(db.Boolean, nullable=False, default=False, server_default='false', index=True)

    address = db.Column(db.String(300), nullable=True)
    city = db.Column(db.String(120), nullable=True, index=True)
    state = db.Column(db.String(80), nullable=True)
    country = db.Column(db.String(80), nullable=True, index=True)
    lat = db.Column(db.Float, nullable=True, index=True)
    lng = db.Column(db.Float, nullable=True, index=True)

    contact_name = db.Column(db.String(150), nullable=True)
    contact_email = db.Column(db.String(150), nullable=True)
    contact_phone = db.Column(db.String(40), nullable=True)
    contact_whatsapp = db.Column(db.String(40), nullable=True)
    contact_link = db.Column(db.String(500), nullable=True)

    status = db.Column(db.String(20), nullable=False, default='active', server_default='active')
    expires_at = db.Column(db.DateTime, nullable=True, index=True)
    renewed_count = db.Column(db.Integer, nullable=False, default=0, server_default='0')
    views_count = db.Column(db.Integer, nullable=False, default=0, server_default='0')
    contact_taps = db.Column(db.Integer, nullable=False, default=0, server_default='0')

    created_by = db.Column(db.String(50), db.ForeignKey('user.public_id'), nullable=True, index=True)
    pub_date = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    # Guest posting: filled only when this listing was submitted without an
    # account (see routes/marketplace.py's guest block). guest_manage_token
    # is the no-login credential: a private link emailed to the submitter,
    # validated purely by this unique token.
    guest_email = db.Column(db.String(150), nullable=True)
    guest_phone = db.Column(db.String(40), nullable=True)
    guest_manage_token = db.Column(db.String(64), nullable=True, unique=True, index=True)

    # Three-state moderation gate: None = pending guest submission awaiting
    # admin review, True = live, False = rejected. Every existing row was
    # backfilled to True by the migration that added this column, and every
    # logged-in create path sets it True immediately -- only a brand new
    # guest submission is ever inserted with this left None.
    approved_to_publish = db.Column(db.Boolean, nullable=True, index=True)

    photos = db.relationship('MarketplaceListingPhoto', backref='listing', lazy=True,
                              cascade='all, delete-orphan', order_by='MarketplaceListingPhoto.position')
    likes = db.relationship('MarketplaceListingLike', backref='listing', lazy=True, cascade='all, delete-orphan')
    creator = db.relationship('User', foreign_keys=[created_by],
                               backref=db.backref('marketplace_listings', lazy=True))

    def __init__(self, slug, title, category, created_by=None, **kwargs):
        self.slug = slug
        self.title = title
        self.category = category
        self.created_by = created_by
        for key, value in kwargs.items():
            setattr(self, key, value)
        if self.expires_at is None:
            self.expires_at = datetime.utcnow() + timedelta(days=LISTING_LIFETIME_DAYS)

    @property
    def is_expired(self):
        return self.expires_at is not None and self.expires_at < datetime.utcnow()

    def renew(self):
        self.expires_at = datetime.utcnow() + timedelta(days=LISTING_LIFETIME_DAYS)
        self.renewed_count = (self.renewed_count or 0) + 1
        self.status = 'active'

    def __repr__(self):
        return f'MarketplaceListing({self.id}) {self.title}'


class MarketplaceListingPhoto(db.Model):
    __tablename__ = 'marketplace_listing_photo'

    id = db.Column(db.Integer, primary_key=True)
    listing_id = db.Column(db.Integer, db.ForeignKey('marketplace_listing.id'), nullable=False, index=True)
    filename = db.Column(db.String(300), nullable=False)
    position = db.Column(db.Integer, nullable=False, default=0, server_default='0')

    def __init__(self, listing_id, filename, position=0):
        self.listing_id = listing_id
        self.filename = filename
        self.position = position


class MarketplaceListingLike(db.Model):
    """Save/favorite -- same shape as EstatesListingLike minus its
    price-drop-notification snapshot fields (no price-tracking sweep for
    this feature in v1)."""
    __tablename__ = 'marketplace_listing_like'

    id = db.Column(db.Integer, primary_key=True)
    listing_id = db.Column(db.Integer, db.ForeignKey('marketplace_listing.id'), nullable=False, index=True)
    user_id = db.Column(db.String(50), db.ForeignKey('user.public_id'), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    status = db.Column(db.String(20), nullable=False, default='saved', server_default='saved')
    note = db.Column(db.String(NOTE_MAX), nullable=True)

    __table_args__ = (
        db.UniqueConstraint('listing_id', 'user_id', name='uq_marketplace_like_listing_user'),
    )

    user = db.relationship('User', backref=db.backref('liked_marketplace_listings', lazy=True))

    def __init__(self, listing_id, user_id):
        self.listing_id = listing_id
        self.user_id = user_id
