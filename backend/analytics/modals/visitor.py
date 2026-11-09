from config import db
from datetime import date, datetime


class VisitorIpThrottle(db.Model):
    """Per-IP, per-day counter of brand-new VisitorSession rows created via
    the public /analytics/beacon endpoint -- same (identity, date) bare-
    counter shape as GuestSubmissionThrottle (backend/guest/modals/
    guest_throttle.py), used the same way for the same reason (this app
    runs serverless with pool_size=1, so an in-memory limiter would
    silently do nothing).

    Deliberately scoped to NEW sessions only, not every beacon call -- a
    real visitor loading many pages keeps reusing their own anonymous_id,
    which should never be capped. The actual bot signature this defends
    against is a scraper that doesn't persist the client-side anonymous_id
    between requests (or deliberately randomizes it), which looks exactly
    like a flood of brand-new "unique visitors" from one IP -- that's what
    this throttle catches."""
    __tablename__ = 'visitor_ip_throttle'

    id = db.Column(db.Integer, primary_key=True)
    identity = db.Column(db.String(64), nullable=False, index=True)  # 'ip:<remote_addr>'
    usage_date = db.Column(db.Date, nullable=False, default=date.today, index=True)
    count = db.Column(db.Integer, nullable=False, default=0, server_default='0')

    __table_args__ = (
        db.UniqueConstraint('identity', 'usage_date', name='uq_visitor_ip_throttle_identity_date'),
    )

    def __repr__(self):
        return f'VisitorIpThrottle({self.identity} {self.usage_date} x{self.count})'


class VisitorSession(db.Model):
    """One row per anonymous visitor (identified by a cookie token), regardless
    of how many page views they rack up — page_view_count/last_seen just get
    bumped in place. If the visitor logs in, user_id gets backfilled so
    anonymous-then-authenticated activity can be linked without needing to
    merge/duplicate the row."""
    __tablename__ = 'visitor_session'

    id = db.Column(db.Integer, primary_key=True)
    anonymous_id = db.Column(db.String(64), nullable=False, index=True)
    user_id = db.Column(db.String(50), db.ForeignKey('user.public_id'), nullable=True)
    country = db.Column(db.String(100), nullable=True)
    first_seen = db.Column(db.DateTime, default=datetime.utcnow)
    last_seen = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    page_view_count = db.Column(db.Integer, default=0)
    is_localhost = db.Column(db.Boolean, default=False)
    # Which sub-site this session belongs to (site registry's `id`, e.g.
    # 'business'; null/'main' for the consumer site) -- self-reported by the
    # frontend (siteMode.js's getCurrentSite()) rather than sniffed from the
    # request Host header, since every sub-site is the same deployment behind
    # whatever hostname the request happens to arrive on, and the frontend
    # already resolves that reliably (prod hostname match, or the `?site=`
    # dev toggle) while the backend has no equivalent hostname->site mapping
    # of its own. A visitor's anonymous_id is already implicitly one-per-site
    # (localStorage is same-origin only), so this column doesn't change what
    # gets tracked -- it just makes "traffic to just the Business site"
    # directly filterable instead of inferred from path collisions (both
    # sites' home routes are literally '/').
    site = db.Column(db.String(20), nullable=True, index=True)

    # Which business-owner storefront this session is on, when site is
    # 'business-site' -- every storefront subdomain self-reports that same
    # generic site id (see siteMode.js's businessSiteDescriptor), so without
    # this column there'd be no way to tell one owner's traffic apart from
    # another's. Resolved server-side in beacon() from the subdomain the
    # frontend sends (BusinessSite.subdomain -> business_id), not trusted
    # from the client directly. Loose reference (no FK) to Business.id,
    # same reasoning as VisitorEvent.business_id below. Null for every
    # non-storefront session.
    business_id = db.Column(db.Integer, nullable=True, index=True)

    def __repr__(self):
        return f'<VisitorSession {self.anonymous_id[:8]}... user={self.user_id}>'


class VisitorEvent(db.Model):
    """One row per tracked action. anonymous_id is a loose reference (no FK) to
    VisitorSession.anonymous_id -- sessions and events are written independently
    so a beacon that races ahead of/behind its session upsert never fails.
    event_type is free text (not a DB enum) on purpose: 'page_view' today,
    'like'/'comment'/'game_play'/'ad_click' etc. later, with no migration
    needed to add a new value."""
    __tablename__ = 'visitor_event'

    id = db.Column(db.Integer, primary_key=True)
    anonymous_id = db.Column(db.String(64), nullable=False, index=True)
    event_type = db.Column(db.String(30), nullable=False)
    path = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    # Loose reference (no FK) to Business.id, same "no FK" reasoning as
    # anonymous_id -- a beacon should never fail because of a stale/deleted
    # business row. Populated for the business-directory click-analytics
    # events ('business_view', 'business_whatsapp_click',
    # 'business_directions_click', 'business_deal_view',
    # 'business_deal_redeem', 'business_share'); null for every other
    # (main-site) event type.
    business_id = db.Column(db.Integer, nullable=True, index=True)

    # Same self-reported sub-site id as VisitorSession.site (see there for
    # why) -- kept on both tables since events are queried independently of
    # sessions for a lot of these aggregates.
    site = db.Column(db.String(20), nullable=True, index=True)

    def __repr__(self):
        return f'<VisitorEvent {self.event_type} {self.anonymous_id[:8]}...>'
