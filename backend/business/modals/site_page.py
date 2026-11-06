from config import db
from datetime import datetime

PAGE_STATUSES = ('draft', 'published')


class SitePage(db.Model):
    """One page on a business's own site (home/about/contact/custom). The
    actual content lives in SitePageVersion below -- this row is just the
    page's identity (slug/title/SEO), which stays stable across edits."""
    __tablename__ = 'site_page'

    id = db.Column(db.Integer, primary_key=True)
    business_site_id = db.Column(db.Integer, db.ForeignKey('business_site.id'), nullable=False, index=True)

    slug = db.Column(db.String(160), nullable=False)
    title = db.Column(db.String(150), nullable=False)
    is_home = db.Column(db.Boolean, nullable=False, default=False, server_default='false')
    status = db.Column(db.String(20), nullable=False, default='draft', server_default='draft', index=True)

    seo_title = db.Column(db.String(70), nullable=True)
    seo_description = db.Column(db.String(200), nullable=True)
    seo_og_image = db.Column(db.String(300), nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('business_site_id', 'slug', name='uq_site_page_site_slug'),
    )

    site = db.relationship('BusinessSite', backref=db.backref('pages', lazy=True, cascade='all, delete-orphan'))
    versions = db.relationship(
        'SitePageVersion', backref='page', lazy=True, cascade='all, delete-orphan',
        order_by='desc(SitePageVersion.created_at)',
    )

    def __init__(self, business_site_id, slug, title, is_home=False):
        self.business_site_id = business_site_id
        self.slug = slug
        self.title = title
        self.is_home = is_home

    def __repr__(self):
        return f'SitePage({self.id}) site={self.business_site_id} slug={self.slug!r}'


class SitePageVersion(db.Model):
    """Append-only: every "Save draft" inserts a new row rather than
    overwriting one, so a page can be rolled back and a draft edit never
    touches what the public sees until Publish explicitly flips
    is_published on a specific version (and off on every other version of
    the same page -- enforced by the route, not a DB constraint, same
    division of responsibility as Business.rating_avg being a route-
    maintained denormalization rather than a trigger)."""
    __tablename__ = 'site_page_version'

    id = db.Column(db.Integer, primary_key=True)
    page_id = db.Column(db.Integer, db.ForeignKey('site_page.id'), nullable=False, index=True)

    # List of sections, each with a list of blocks -- see BLOCK_TYPES in
    # backend/business/modals/business_site.py for the schema every block
    # here is validated against on save.
    sections = db.Column(db.JSON, nullable=False, default=list)
    is_published = db.Column(db.Boolean, nullable=False, default=False, server_default='false', index=True)

    created_by = db.Column(db.String(50), db.ForeignKey('user.public_id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    creator = db.relationship('User', foreign_keys=[created_by])

    def __init__(self, page_id, sections, created_by=None):
        self.page_id = page_id
        self.sections = sections
        self.created_by = created_by

    def __repr__(self):
        return f'SitePageVersion({self.id}) page={self.page_id} published={self.is_published}'
