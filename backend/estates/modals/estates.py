import re
import unicodedata
from datetime import datetime, timedelta

from config import db

# Enforced at the Python/route level (not a DB enum) -- same convention as
# BUSINESS_CATEGORIES in backend/business/modals/business.py.
LISTING_TYPES = ('sale', 'long_term_lease', 'short_term_lease')

# Only sale/long-term listings auto-expire after a month -- a short-term
# (vacation) rental is ongoing availability, not a one-time transaction that
# goes stale the same way, so it's exempt (see EstatesListing.__init__).
EXPIRING_LISTING_TYPES = {'sale', 'long_term_lease'}
LISTING_LIFETIME_DAYS = 30

CURRENCIES = ('USD', 'ILS')
MAX_PHOTOS = 5

# Stage 5's poster dashboard -- a manual status independent of expires_at;
# a 'rented'/'sold' listing disappears from results the same way an
# expired one does (see routes/estates.py's list_listings), it just also
# tells the poster (and this model) WHY it's gone, same reasoning as
# TachlisPost.status/POST_STATUSES.
LISTING_STATUSES = ('active', 'rented', 'sold')


def slugify(name):
    normalized = unicodedata.normalize('NFKD', name).encode('ascii', 'ignore').decode('ascii')
    slug = re.sub(r'[^a-z0-9]+', '-', normalized.lower()).strip('-')
    return slug or 'listing'


class EstatesListing(db.Model):
    """A single property listing -- for sale, long-term lease, or short-term
    lease. Sale/long-term listings default to a one-month lifetime (see
    EXPIRING_LISTING_TYPES) so the public-facing list never shows stale
    listings, but rows are never deleted on expiry -- `is_expired` just
    filters them out of the public query (see routes/estates.py) while
    still showing up on the owner's own "My Listings" page, preserving them
    for historical data same as the user asked."""
    __tablename__ = 'estates_listing'

    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(170), unique=True, nullable=False, index=True)

    listing_type = db.Column(db.String(20), nullable=False, index=True)
    title = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text, nullable=True)

    price = db.Column(db.Float, nullable=True)
    currency = db.Column(db.String(3), nullable=False, default='USD', server_default='USD')
    # Only meaningful for leases (e.g. 'month', 'night', 'week'); null for sale.
    price_period = db.Column(db.String(20), nullable=True)

    address = db.Column(db.String(300), nullable=True)
    # A neighborhood/sub-area within `city` -- common for Israeli listings in
    # particular (e.g. "Givat Hamivtar" within "Yerushalayim", "Neve Shamir"
    # within "Beit Shemesh"), where the neighborhood often matters more to a
    # buyer than the city alone. Free text, not a controlled list -- there's
    # no clean enumerable source of every neighborhood in every city/country
    # this site could ever list.
    neighborhood = db.Column(db.String(120), nullable=True, index=True)
    city = db.Column(db.String(120), nullable=True, index=True)
    state = db.Column(db.String(80), nullable=True)
    zip_code = db.Column(db.String(20), nullable=True)
    country = db.Column(db.String(80), nullable=True, index=True)
    lat = db.Column(db.Float, nullable=True, index=True)
    lng = db.Column(db.Float, nullable=True, index=True)

    bedrooms = db.Column(db.Float, nullable=True)
    bathrooms = db.Column(db.Float, nullable=True)
    size_value = db.Column(db.Float, nullable=True)
    size_unit = db.Column(db.String(10), nullable=True, default='sqft', server_default='sqft')

    # Clearly-labeled distinction the user specifically called out -- a
    # buyer/renter treats an agent-posted listing differently than a private
    # owner's (commission, negotiation norms, etc). Nullable because it's not
    # always known at creation time (e.g. bulk-imported listings) -- None
    # means "not specified" and is treated as neither agent nor owner for
    # the agent_only/owner_only search filters.
    is_agent = db.Column(db.Boolean, nullable=True, index=True)

    contact_name = db.Column(db.String(150), nullable=True)
    contact_email = db.Column(db.String(150), nullable=True)
    contact_phone = db.Column(db.String(40), nullable=True)
    contact_whatsapp = db.Column(db.String(40), nullable=True)

    # Free-form extensibility (parking, furnished, pets_ok, year_built, ...)
    # without needing a migration for every niche field -- same pattern as
    # Business.attributes.
    attributes = db.Column(db.JSON, nullable=True)

    created_by = db.Column(db.String(50), db.ForeignKey('user.public_id'), nullable=True, index=True)

    pub_date = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    # When this listing was actually posted in its source WhatsApp group --
    # distinct from pub_date (when it was added to this DB), which for a
    # bulk-imported listing can lag the real post by hours. NULL for
    # listings posted directly on-site (there's no separate "source" for
    # those) or any older imported listing from before this field existed;
    # "newest" sorting falls back to pub_date in that case (see
    # routes/estates.py's list_listings), so this is purely additive.
    source_posted_at = db.Column(db.DateTime, nullable=True, index=True)
    expires_at = db.Column(db.DateTime, nullable=True, index=True)
    renewed_count = db.Column(db.Integer, nullable=False, default=0, server_default='0')
    views_count = db.Column(db.Integer, nullable=False, default=0, server_default='0')
    # Stage 5's poster dashboard -- "WhatsApp taps" (contact_whatsapp or
    # contact_phone's wa.me link clicked), tracked client-side via POST
    # /estates/listings/<id>/contact-tap, fired once per click, not tied to
    # which contact method was actually used.
    contact_taps = db.Column(db.Integer, nullable=False, default=0, server_default='0')
    status = db.Column(db.String(20), nullable=False, default='active', server_default='active')

    # Stage 5's "Still available?" check -- set when the poster confirms;
    # cleared back to NULL on renew() so a renewed listing is asked again
    # at its own next 14-day mark rather than being "confirmed forever"
    # from one reply months ago.
    still_available_confirmed_at = db.Column(db.DateTime, nullable=True)
    still_available_reminder_sent_at = db.Column(db.DateTime, nullable=True)
    still_available_token = db.Column(db.String(64), nullable=True, unique=True)

    photos = db.relationship('EstatesListingPhoto', backref='listing', lazy=True,
                              cascade='all, delete-orphan', order_by='EstatesListingPhoto.position')
    likes = db.relationship('EstatesListingLike', backref='listing', lazy=True, cascade='all, delete-orphan')
    creator = db.relationship('User', foreign_keys=[created_by],
                               backref=db.backref('estates_listings', lazy=True))

    def __init__(self, slug, listing_type, title, created_by=None, expires_at=None, **kwargs):
        self.slug = slug
        self.listing_type = listing_type
        self.title = title
        self.created_by = created_by
        for key, value in kwargs.items():
            setattr(self, key, value)
        if expires_at is not None:
            self.expires_at = expires_at
        elif listing_type in EXPIRING_LISTING_TYPES:
            self.expires_at = datetime.utcnow() + timedelta(days=LISTING_LIFETIME_DAYS)

    @property
    def is_expired(self):
        return self.expires_at is not None and self.expires_at < datetime.utcnow()

    def renew(self):
        """Bumps expires_at another LISTING_LIFETIME_DAYS out from now --
        the owner-side lever for keeping a still-available listing visible
        past its first month without it ever having silently come back on
        its own (see POST /estates/listings/<id>/renew)."""
        self.expires_at = datetime.utcnow() + timedelta(days=LISTING_LIFETIME_DAYS)
        self.renewed_count = (self.renewed_count or 0) + 1
        self.status = 'active'
        self.still_available_confirmed_at = None
        self.still_available_reminder_sent_at = None

    def __repr__(self):
        return f'EstatesListing({self.id}) {self.title}'


class EstatesListingPhoto(db.Model):
    __tablename__ = 'estates_listing_photo'

    id = db.Column(db.Integer, primary_key=True)
    listing_id = db.Column(db.Integer, db.ForeignKey('estates_listing.id'), nullable=False, index=True)
    # Raw Supabase Storage filename -- resolved via upload.get_public_url()
    # at serialization time, same pattern as Business.logo.
    filename = db.Column(db.String(300), nullable=False)
    position = db.Column(db.Integer, nullable=False, default=0, server_default='0')

    def __init__(self, listing_id, filename, position=0):
        self.listing_id = listing_id
        self.filename = filename
        self.position = position


# Stage 4's "saved items with status" -- enforced at the Python/route level,
# not a DB enum, same convention as SEARCH_TYPES/POST_TYPES elsewhere.
# 'saved' is the initial state the moment something's liked/hearted; the
# other three are the member's own tracking of where they are with it.
SAVED_STATUSES = ('saved', 'contacted', 'viewed', 'applied')
NOTE_MAX = 500


class EstatesListingLike(db.Model):
    """A saved/favorited listing -- the 'come back to this later' feature.
    Also Stage 4's shortlist: status + note let a member track where they
    are with it, and notified_price/was_active are snapshots this same row
    compares against on each price-drop/back-on-market sweep (see
    backend/estates/routes/estates.py's check_saved_listings_for_changes())
    so a listing only triggers one notification per actual change, not one
    per sweep."""
    __tablename__ = 'estates_listing_like'

    id = db.Column(db.Integer, primary_key=True)
    listing_id = db.Column(db.Integer, db.ForeignKey('estates_listing.id'), nullable=False, index=True)
    user_id = db.Column(db.String(50), db.ForeignKey('user.public_id'), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    status = db.Column(db.String(20), nullable=False, default='saved', server_default='saved')
    note = db.Column(db.String(NOTE_MAX), nullable=True)

    notified_price = db.Column(db.Float, nullable=True)
    was_active = db.Column(db.Boolean, nullable=False, default=True, server_default='true')

    __table_args__ = (
        db.UniqueConstraint('listing_id', 'user_id', name='uq_estates_like_listing_user'),
    )

    user = db.relationship('User', backref=db.backref('liked_estates_listings', lazy=True))

    def __init__(self, listing_id, user_id):
        self.listing_id = listing_id
        self.user_id = user_id


# ── Group buy ("buy before it's built") ─────────────────────────────────
# Common in Israel ("al haneyar" / pre-construction buying) -- a developer
# project where a large enough group of buyers banding together can get a
# bulk-purchase discount. This is a separate listing type entirely (a whole
# project with many prospective buyers, not one seller/one buyer), hence its
# own model rather than forcing it into EstatesListing.

GROUP_BUY_STAGES = ('pre_construction', 'under_construction', 'nearing_completion')


class EstatesGroupBuy(db.Model):
    __tablename__ = 'estates_group_buy'

    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(170), unique=True, nullable=False, index=True)

    title = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text, nullable=True)
    developer_name = db.Column(db.String(150), nullable=True)
    stage = db.Column(db.String(30), nullable=True)

    address = db.Column(db.String(300), nullable=True)
    neighborhood = db.Column(db.String(120), nullable=True, index=True)
    city = db.Column(db.String(120), nullable=True, index=True)
    state = db.Column(db.String(80), nullable=True)
    country = db.Column(db.String(80), nullable=True, index=True)
    lat = db.Column(db.Float, nullable=True)
    lng = db.Column(db.Float, nullable=True)

    price_per_unit_estimate = db.Column(db.Float, nullable=True)
    currency = db.Column(db.String(3), nullable=False, default='USD', server_default='USD')
    total_units = db.Column(db.Integer, nullable=True)
    min_group_size = db.Column(db.Integer, nullable=True)
    # Free-form ("Q4 2027") rather than a strict date -- pre-construction
    # timelines are estimates that get restated in whatever precision the
    # developer actually gave, not a hard committed date.
    expected_completion = db.Column(db.String(40), nullable=True)

    contact_name = db.Column(db.String(150), nullable=True)
    contact_email = db.Column(db.String(150), nullable=True)
    contact_phone = db.Column(db.String(40), nullable=True)
    contact_whatsapp = db.Column(db.String(40), nullable=True)

    created_by = db.Column(db.String(50), db.ForeignKey('user.public_id'), nullable=True, index=True)
    pub_date = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    is_closed = db.Column(db.Boolean, nullable=False, default=False, server_default='false')

    photos = db.relationship('EstatesGroupBuyPhoto', backref='group_buy', lazy=True,
                              cascade='all, delete-orphan', order_by='EstatesGroupBuyPhoto.position')
    members = db.relationship('EstatesGroupBuyMember', backref='group_buy', lazy=True,
                               cascade='all, delete-orphan')
    creator = db.relationship('User', foreign_keys=[created_by],
                               backref=db.backref('estates_group_buys', lazy=True))

    def __init__(self, slug, title, created_by=None, **kwargs):
        self.slug = slug
        self.title = title
        self.created_by = created_by
        for key, value in kwargs.items():
            setattr(self, key, value)

    def __repr__(self):
        return f'EstatesGroupBuy({self.id}) {self.title}'


class EstatesGroupBuyPhoto(db.Model):
    __tablename__ = 'estates_group_buy_photo'

    id = db.Column(db.Integer, primary_key=True)
    group_buy_id = db.Column(db.Integer, db.ForeignKey('estates_group_buy.id'), nullable=False, index=True)
    filename = db.Column(db.String(300), nullable=False)
    position = db.Column(db.Integer, nullable=False, default=0, server_default='0')

    def __init__(self, group_buy_id, filename, position=0):
        self.group_buy_id = group_buy_id
        self.filename = filename
        self.position = position


class EstatesGroupBuyMember(db.Model):
    """Someone who's joined a group-buy to express interest -- the organizer
    sees the full list (to coordinate), everyone else just sees a count (not
    other members' identities)."""
    __tablename__ = 'estates_group_buy_member'

    id = db.Column(db.Integer, primary_key=True)
    group_buy_id = db.Column(db.Integer, db.ForeignKey('estates_group_buy.id'), nullable=False, index=True)
    user_id = db.Column(db.String(50), db.ForeignKey('user.public_id'), nullable=False, index=True)
    note = db.Column(db.String(500), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('group_buy_id', 'user_id', name='uq_estates_groupbuy_member'),
    )

    user = db.relationship('User', backref=db.backref('estates_group_buy_memberships', lazy=True))

    def __init__(self, group_buy_id, user_id, note=None):
        self.group_buy_id = group_buy_id
        self.user_id = user_id
        self.note = note
