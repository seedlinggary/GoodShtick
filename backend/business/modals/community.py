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

    source_url = db.Column(db.String(500), nullable=True)
    source_name = db.Column(db.String(150), nullable=True)
    # Same derivation convention as Business.imported: true when it came
    # with a source citation (bulk-generated from existing city data or
    # scraped), false when a person described their own community by hand.
    imported = db.Column(db.Boolean, default=False, server_default='false', nullable=False, index=True)

    created_by = db.Column(db.String(50), db.ForeignKey('user.public_id'), nullable=True)
    pub_date = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    creator = db.relationship('User', foreign_keys=[created_by])

    def __init__(self, slug, name, city, description=None, state=None, country=None,
                 lat=None, lng=None, logo=None, created_by=None, source_url=None,
                 source_name=None, imported=False, eruv_status=None, eruv_url=None,
                 eruv_map_image=None):
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

    def __repr__(self):
        return f'Community({self.id}) {self.name}'
