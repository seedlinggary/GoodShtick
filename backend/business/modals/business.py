import re
import unicodedata

from config import db
from datetime import datetime

# Enforced at the Python/route level (not a Postgres enum) to match this
# project's convention of avoiding DB-level enums elsewhere (see tachlis).
BUSINESS_CATEGORIES = (
    'restaurant', 'grocery', 'retail', 'professional_services',
    'health_beauty', 'home_services', 'education', 'entertainment',
    'automotive', 'nonprofit', 'gemach', 'shul', 'kollel', 'other',
)

# Categories where a "kosher/kashrut" filter is relevant on the frontend.
# Kashrut itself is still stored per-location (a chain can vary by branch),
# this just tells the client when to show that field/filter at all.
FOOD_CATEGORIES = {'restaurant', 'grocery'}

# 'physical' = a real address (geocoded via the address autocomplete, has
# lat/lng); 'delivery' = no storefront, just a city/country it serves;
# 'online' = no location at all -- a home business or web-only shop that
# could be anywhere. Enforced at the Python/route level, not a DB enum.
LOCATION_TYPES = ('physical', 'delivery', 'online')


def slugify(name):
    normalized = unicodedata.normalize('NFKD', name).encode('ascii', 'ignore').decode('ascii')
    slug = re.sub(r'[^a-z0-9]+', '-', normalized.lower()).strip('-')
    return slug or 'business'


class Business(db.Model):
    __tablename__ = 'business'

    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(160), unique=True, nullable=False, index=True)
    name = db.Column(db.String(150), nullable=False)
    about = db.Column(db.Text, nullable=True)
    # Raw Supabase Storage filename -- resolved to a public URL at
    # serialization time via upload.get_public_url(), same pattern as
    # HockPost.image (see backend/hock/schemas/hock.py).
    logo = db.Column(db.String(300), nullable=True)
    category = db.Column(db.String(40), nullable=False, index=True)
    website = db.Column(db.String(300), nullable=True)

    # Provenance for listings that weren't submitted by their own owner (bulk
    # directory imports) -- where the info came from, so a claimant or admin
    # can verify/correct it. `imported` distinguishes these from organic
    # self-submissions for admin filtering/auditing at scale.
    source_url = db.Column(db.String(500), nullable=True)
    source_name = db.Column(db.String(150), nullable=True)
    imported = db.Column(db.Boolean, default=False, server_default='false', nullable=False, index=True)

    # Set only once a claim is approved -- see BusinessClaim.
    owner_user_id = db.Column(db.String(50), db.ForeignKey('user.public_id'), nullable=True, index=True)
    created_by = db.Column(db.String(50), db.ForeignKey('user.public_id'), nullable=True)

    # Denormalized -- recomputed on every BusinessRating write so the
    # directory/list/sort queries never need a live aggregate join.
    rating_avg = db.Column(db.Float, nullable=False, default=0.0, server_default='0')
    rating_count = db.Column(db.Integer, nullable=False, default=0, server_default='0')

    # Free-form extensibility for whatever a given business type needs that
    # doesn't warrant its own column yet (e.g. delivery, wifi, parking).
    attributes = db.Column(db.JSON, nullable=True)

    # Set when an owner activates "boosted placement" (earned by completing
    # their profile, see routes/business_owner_tools.py) -- while in the
    # future this points, list_businesses sorts the business to the top of
    # its category/search regardless of the requested sort.
    boost_until = db.Column(db.DateTime, nullable=True, index=True)

    pub_date = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    owner = db.relationship('User', foreign_keys=[owner_user_id],
                             backref=db.backref('owned_businesses', lazy=True))
    creator = db.relationship('User', foreign_keys=[created_by],
                               backref=db.backref('created_businesses', lazy=True))
    locations = db.relationship('BusinessLocation', backref='business', lazy=True,
                                 cascade='all, delete-orphan')

    def __init__(self, slug, name, category, about=None, logo=None,
                 created_by=None, attributes=None, website=None,
                 source_url=None, source_name=None, imported=False):
        self.slug = slug
        self.name = name
        self.category = category
        self.about = about
        self.logo = logo
        self.created_by = created_by
        self.attributes = attributes
        self.website = website
        self.source_url = source_url
        self.source_name = source_name
        self.imported = imported

    @property
    def is_claimed(self):
        return self.owner_user_id is not None

    def __repr__(self):
        return f'Business({self.id}) {self.name}'


class BusinessLocation(db.Model):
    __tablename__ = 'business_location'

    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(db.Integer, db.ForeignKey('business.id'), nullable=False, index=True)

    # See LOCATION_TYPES. Existing rows default to 'physical' (that was the
    # only kind that existed before this column was added).
    location_type = db.Column(db.String(20), nullable=False, default='physical', server_default='physical', index=True)

    address = db.Column(db.String(300), nullable=True)
    city = db.Column(db.String(120), nullable=True, index=True)
    state = db.Column(db.String(80), nullable=True)
    zip_code = db.Column(db.String(20), nullable=True)
    country = db.Column(db.String(80), nullable=True)

    lat = db.Column(db.Float, nullable=True, index=True)
    lng = db.Column(db.Float, nullable=True, index=True)

    phone = db.Column(db.String(40), nullable=True)
    email = db.Column(db.String(120), nullable=True)

    # {"mon": {"open": "09:00", "close": "17:00", "closed": false}, ...}
    hours = db.Column(db.JSON, nullable=True)

    # Only meaningful for FOOD_CATEGORIES businesses, but kept generic --
    # nothing stops a caterer or grocery aisle from wanting this either.
    kashrut = db.Column(db.String(200), nullable=True)
    attributes = db.Column(db.JSON, nullable=True)

    is_primary = db.Column(db.Boolean, default=False, server_default='false', nullable=False)

    def __init__(self, business_id, location_type='physical', address=None, city=None, state=None, zip_code=None,
                 country=None, lat=None, lng=None, phone=None, email=None, hours=None,
                 kashrut=None, attributes=None, is_primary=False):
        self.business_id = business_id
        self.location_type = location_type
        self.address = address
        self.city = city
        self.state = state
        self.zip_code = zip_code
        self.country = country
        self.lat = lat
        self.lng = lng
        self.phone = phone
        self.email = email
        self.hours = hours
        self.kashrut = kashrut
        self.attributes = attributes
        self.is_primary = is_primary

    def __repr__(self):
        return f'BusinessLocation({self.id}) business={self.business_id} {self.city or ""}'
