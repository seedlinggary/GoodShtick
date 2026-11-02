import re
import unicodedata

from config import db
from datetime import datetime


def slugify_community(name):
    normalized = unicodedata.normalize('NFKD', name).encode('ascii', 'ignore').decode('ascii')
    slug = re.sub(r'[^a-z0-9]+', '-', normalized.lower()).strip('-')
    return slug or 'community'


class Community(db.Model):
    """A named Jewish community for the 'Find a Community' feature -- usually
    one city (Beit Shemesh, Teaneck, ...) but can be a finer neighborhood
    (Ramat Beit Shemesh Aleph) when that's how the community actually
    organizes itself. Deliberately has no direct FK list of "its" shuls/
    groceries/etc. -- those are found by a radius query against lat/lng (the
    same bbox approach the Directory's "Near me" already uses) against the
    existing Business/BusinessLocation data, filtered by category. That
    reuses every business already imported instead of requiring each one to
    be manually re-linked to a community, and naturally covers "or nearby"
    for anything just outside the community's own borders."""
    __tablename__ = 'community'

    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(160), unique=True, nullable=False, index=True)
    name = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text, nullable=True)

    city = db.Column(db.String(120), nullable=False, index=True)
    state = db.Column(db.String(80), nullable=True)
    country = db.Column(db.String(80), nullable=True)
    lat = db.Column(db.Float, nullable=True, index=True)
    lng = db.Column(db.Float, nullable=True, index=True)

    logo = db.Column(db.String(300), nullable=True)

    # Free text rather than a boolean -- real answers are things like "Active,
    # connected to the Peterson Park eruv" or "None currently", not a plain
    # yes/no. eruv_url points at the community's own eruv-status page/hotline
    # (the one place that's actually kept current); the disclaimer about
    # checking it before relying on it is standing copy at the route/UI
    # level, not stored per-row, since it applies the same way every time.
    eruv_status = db.Column(db.String(300), nullable=True)
    eruv_url = db.Column(db.String(500), nullable=True)
    # A real eruv map image (uploaded via the shared /business/upload
    # pipeline, same Supabase-storage-filename convention as Business.logo)
    # -- shown directly on the community page since "is there an eruv I can
    # see" is a more useful answer than a link out to someone else's site,
    # when we actually have the map.
    eruv_map_image = db.Column(db.String(300), nullable=True)

    # Curated neighborhoods within this community (e.g. Beit Shemesh's
    # Mishkafayim/Ramat Shilo/Neve Shamir/Ramat Gimmel) -- a list of
    # {"name": str, "match": [str, ...]} dicts. Deliberately curated by
    # whoever manages this community rather than auto-derived from
    # EstatesListing.neighborhood's free text: real neighborhood data is
    # messy (parentheticals, abbreviations, spelling variants -- confirmed
    # live), so `match` lets one sub-area absorb known variants (e.g. both
    # "RBS Gimmel 2" and "Ramat Gimmel 2") without a schema change. See
    # routes/community.py's get_community()'s ?area= handling.
    sub_areas = db.Column(db.JSON, nullable=True)

    source_url = db.Column(db.String(500), nullable=True)
    source_name = db.Column(db.String(150), nullable=True)
    # Same derivation convention as Business.imported: true when it came
    # with a source citation (bulk-generated from existing city data or
    # scraped), false when a person described their own community by hand.
    imported = db.Column(db.Boolean, default=False, server_default='false', nullable=False, index=True)

    created_by = db.Column(db.String(50), db.ForeignKey('user.public_id'), nullable=True)
    pub_date = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    # Guest posting: filled only when this community was submitted without
    # an account (see routes/community.py's guest block). guest_manage_token
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

    creator = db.relationship('User', foreign_keys=[created_by])

    def __init__(self, slug, name, city, description=None, state=None, country=None,
                 lat=None, lng=None, logo=None, created_by=None, source_url=None,
                 source_name=None, imported=False, eruv_status=None, eruv_url=None,
                 eruv_map_image=None, approved_to_publish=True, guest_email=None,
                 guest_phone=None, guest_manage_token=None):
        self.slug = slug
        self.name = name
        self.city = city
        self.description = description
        self.state = state
        self.country = country
        self.lat = lat
        self.lng = lng
        self.logo = logo
        self.created_by = created_by
        self.source_url = source_url
        self.source_name = source_name
        self.imported = imported
        self.eruv_status = eruv_status
        self.eruv_url = eruv_url
        self.eruv_map_image = eruv_map_image
        self.approved_to_publish = approved_to_publish
        self.guest_email = guest_email
        self.guest_phone = guest_phone
        self.guest_manage_token = guest_manage_token

    def __repr__(self):
        return f'Community({self.id}) {self.name}'


class CommunityDataCache(db.Model):
    """Generic cache for this domain's own slow/cacheable external calls --
    today that's GPT cost-of-living estimates (see
    routes/community.py's get_cost_of_living), keyed by a string like
    'col:<slug>'. Same shape/reasoning as
    backend/finance/modals/finance.py's FinanceDataCache: an LLM call is slow
    and costs money per request, so a fresh-enough answer is served straight
    back from here instead of asking the model again on every page load."""
    __tablename__ = 'community_data_cache'

    id = db.Column(db.Integer, primary_key=True)
    cache_key = db.Column(db.String(120), unique=True, nullable=False, index=True)
    payload = db.Column(db.JSON, nullable=False)
    fetched_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def __init__(self, cache_key, payload):
        self.cache_key = cache_key
        self.payload = payload


class CommunitySave(db.Model):
    """A member's own 'save this community' bookmark -- lets someone keep a
    shortlist of communities they're considering (e.g. while comparing a few
    before a move), same save/favorite idea as EstatesListingLike."""
    __tablename__ = 'community_save'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(50), db.ForeignKey('user.public_id'), nullable=False, index=True)
    community_id = db.Column(db.Integer, db.ForeignKey('community.id'), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('user_id', 'community_id', name='uq_community_save_user_community'),
    )

    user = db.relationship('User', foreign_keys=[user_id])
    community = db.relationship('Community', foreign_keys=[community_id])

    def __init__(self, user_id, community_id):
        self.user_id = user_id
        self.community_id = community_id
