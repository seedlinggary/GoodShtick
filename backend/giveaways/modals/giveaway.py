import secrets
from datetime import date, datetime

from config import db

# Draft campaigns exist before anything is public; scheduled/active/paused
# happen while entries are open; closed freezes entries (see
# GiveawayDrawSnapshot); winner_selected/completed happen after a draw.
# Enforced at the route level (CAMPAIGN_STATUSES below), not a DB enum, same
# convention as backend/campaigns/modals/campaign.py's CAMPAIGN_STATUSES.
GIVEAWAY_STATUSES = ('draft', 'scheduled', 'active', 'paused', 'closed', 'winner_selected', 'completed')
VERIFICATION_METHODS = ('auto', 'manual', 'self_certify')
PARTICIPATION_STATUSES = ('pending_verification', 'active', 'disqualified', 'winner', 'backup_winner')


class GiveawayCampaign(db.Model):
    """The rich, configurable "campaign" entity -- a giveaway, referral
    program, or lead-gen push. Deliberately its OWN entity, not an extension
    of backend/campaigns/modals/campaign.py's MarketingCampaign: that model
    stays exactly what it already is (a named group of outbound tracked
    links), and this one HAS one of those (marketing_campaign_id) for its
    channel links rather than becoming one -- a giveaway has participants,
    an entry ledger, referral rewards and a winner draw, none of which a
    bare link-tracking campaign needs."""
    __tablename__ = 'giveaway_campaign'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False)
    slug = db.Column(db.String(80), nullable=False, unique=True, index=True)
    description = db.Column(db.Text, nullable=True)
    # Free text, not a DB enum -- 'giveaway' today, 'referral_program'/
    # 'lead_gen'/'coupon' etc. later with no migration needed.
    campaign_type = db.Column(db.String(30), nullable=False, default='giveaway', server_default='giveaway')
    status = db.Column(db.String(20), nullable=False, default='draft', server_default='draft')

    # Informational only (which sub-sites this is being promoted on) --
    # the landing page itself is reachable from every hostname regardless,
    # same as /contribute.
    sites = db.Column(db.JSON, nullable=True)

    starts_at = db.Column(db.DateTime, nullable=True)
    ends_at = db.Column(db.DateTime, nullable=True)

    prize_details = db.Column(db.Text, nullable=True)
    terms_text = db.Column(db.Text, nullable=True)
    privacy_note = db.Column(db.Text, nullable=True)
    image_url = db.Column(db.String(500), nullable=True)

    # e.g. {"max_entries_per_participant": 50} -- entry "weight" per action
    # lives on GiveawayEntryAction.entry_quantity instead; this is just
    # campaign-wide caps/toggles, kept flexible as JSON (same established
    # pattern as Business.attributes) so new rules don't need a migration.
    entry_rules = db.Column(db.JSON, nullable=True)

    # Auto-created alongside this row (see create_campaign route) so this
    # campaign's outbound channel links (WhatsApp, Instagram, email blast)
    # are just ordinary CampaignLink rows under the existing /campaigns
    # system -- no second link/click model.
    marketing_campaign_id = db.Column(db.Integer, db.ForeignKey('marketing_campaign.id'), nullable=True)

    created_by = db.Column(db.String(50), db.ForeignKey('user.public_id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    entry_actions = db.relationship('GiveawayEntryAction', backref='campaign', lazy=True,
                                     cascade='all, delete-orphan', order_by='GiveawayEntryAction.sort_order')
    participations = db.relationship('GiveawayParticipation', backref='campaign', lazy=True,
                                      cascade='all, delete-orphan')

    def __repr__(self):
        return f'GiveawayCampaign({self.id}) {self.name} [{self.status}]'


class GiveawayEntryAction(db.Model):
    """One configurable way to earn entries on a campaign -- email signup,
    email verification, WhatsApp join, Instagram follow, a successful
    referral, etc. Config only; actual completions are GiveawayEntry ledger
    rows, never totals kept here."""
    __tablename__ = 'giveaway_entry_action'

    id = db.Column(db.Integer, primary_key=True)
    campaign_id = db.Column(db.Integer, db.ForeignKey('giveaway_campaign.id'), nullable=False, index=True)

    # e.g. 'email_signup', 'email_verify', 'whatsapp_join', 'instagram_follow',
    # 'facebook_follow', 'referral_qualified', or any admin-defined custom key.
    action_key = db.Column(db.String(60), nullable=False)
    label = db.Column(db.String(160), nullable=False)
    description = db.Column(db.Text, nullable=True)
    action_url = db.Column(db.String(500), nullable=True)

    # This IS the entry "weight" the spec asks for -- a referral action set
    # to 5 is worth 5x an email-verify action set to 1. No separate weight
    # column.
    entry_quantity = db.Column(db.Integer, nullable=False, default=1, server_default='1')

    is_required = db.Column(db.Boolean, nullable=False, default=False, server_default='false')
    verification_method = db.Column(db.String(20), nullable=False, default='self_certify', server_default='self_certify')

    # Null = unlimited; defaults to 1 so a brand-new action can't be farmed
    # for unlimited entries unless an admin explicitly raises this.
    max_completions = db.Column(db.Integer, nullable=True, default=1, server_default='1')

    is_enabled = db.Column(db.Boolean, nullable=False, default=True, server_default='true')
    sort_order = db.Column(db.Integer, nullable=False, default=0, server_default='0')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('campaign_id', 'action_key', name='uq_giveaway_entry_action_campaign_key'),
    )

    def __repr__(self):
        return f'GiveawayEntryAction({self.id}) {self.action_key} +{self.entry_quantity}'


class GiveawayParticipant(db.Model):
    """Global participant identity -- one row per email address, ever,
    across every campaign. Per-campaign state lives on GiveawayParticipation
    instead, so the same person entering two different giveaways doesn't
    duplicate their identity."""
    __tablename__ = 'giveaway_participant'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=True)
    email = db.Column(db.String(160), nullable=False, unique=True, index=True)
    phone = db.Column(db.String(30), nullable=True)
    email_verified = db.Column(db.Boolean, nullable=False, default=False, server_default='false')
    user_id = db.Column(db.String(50), db.ForeignKey('user.public_id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    participations = db.relationship('GiveawayParticipation', backref='participant', lazy=True)

    @staticmethod
    def normalize_email(email):
        return (email or '').strip().lower()

    def __repr__(self):
        return f'GiveawayParticipant({self.id}) {self.email}'


class GiveawayParticipation(db.Model):
    """One participant's record within one campaign -- referral code,
    attribution, consent, and fraud/status state all live here rather than
    on the global GiveawayParticipant, since a person's referrer/consent/
    status in one giveaway has nothing to do with another."""
    __tablename__ = 'giveaway_participation'

    id = db.Column(db.Integer, primary_key=True)
    campaign_id = db.Column(db.Integer, db.ForeignKey('giveaway_campaign.id'), nullable=False, index=True)
    participant_id = db.Column(db.Integer, db.ForeignKey('giveaway_participant.id'), nullable=False, index=True)

    referral_code = db.Column(db.String(16), nullable=False, unique=True, index=True)
    referrer_participation_id = db.Column(db.Integer, db.ForeignKey('giveaway_participation.id'), nullable=True)

    # {source, medium, channel, promotion, creative, partner, referral_code,
    # landing_page, campaign_link_id} -- first_touch is set once and never
    # overwritten (sticky); last_touch is replaced on every subsequent visit
    # before this participation existed... in practice both are set together
    # at /enter time from whatever attribution the landing page captured,
    # and last_touch alone gets refreshed on later /action calls.
    first_touch = db.Column(db.JSON, nullable=True)
    last_touch = db.Column(db.JSON, nullable=True)

    consent_marketing = db.Column(db.Boolean, nullable=False, default=False, server_default='false')
    consent_at = db.Column(db.DateTime, nullable=True)
    consent_source = db.Column(db.String(60), nullable=True)

    status = db.Column(db.String(20), nullable=False, default='pending_verification', server_default='pending_verification')
    fraud_flags = db.Column(db.JSON, nullable=True)

    verify_token = db.Column(db.String(64), nullable=True, unique=True, index=True)
    verified_at = db.Column(db.DateTime, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    referrer = db.relationship('GiveawayParticipation', remote_side=[id])
    entries = db.relationship('GiveawayEntry', backref='participation', lazy=True,
                               foreign_keys='GiveawayEntry.participation_id', cascade='all, delete-orphan')
    referral_clicks = db.relationship('GiveawayReferralClick', backref='participation', lazy=True,
                                       cascade='all, delete-orphan')

    __table_args__ = (
        db.UniqueConstraint('campaign_id', 'participant_id', name='uq_giveaway_participation_campaign_participant'),
    )

    @staticmethod
    def generate_referral_code():
        return secrets.token_hex(4).upper()

    def __repr__(self):
        return f'GiveawayParticipation({self.id}) campaign={self.campaign_id} participant={self.participant_id}'


class GiveawayEntry(db.Model):
    """Append-only entry ledger -- entry totals are ALWAYS computed live as
    SUM(entry_quantity) over non-invalidated rows for a participation, never
    stored/cached anywhere, per the spec's own hard requirement.

    related_participation_id disambiguates two different shapes of entry
    under one uniqueness rule: a plain self-action (email verify, Instagram
    follow) sets this to the SAME id as participation_id (a self-reference
    sentinel, not NULL -- SQL unique constraints treat every NULL as
    distinct from every other NULL, so a bare NULL would silently defeat
    idempotency for repeat self-actions); a referral-credit action sets this
    to the REFERRED friend's participation_id, so one referrer can earn many
    referral-credit rows (one per friend) while still never earning two for
    the same friend."""
    __tablename__ = 'giveaway_entry'

    id = db.Column(db.Integer, primary_key=True)
    participation_id = db.Column(db.Integer, db.ForeignKey('giveaway_participation.id'), nullable=False, index=True)
    action_key = db.Column(db.String(60), nullable=False)
    related_participation_id = db.Column(db.Integer, db.ForeignKey('giveaway_participation.id'), nullable=False)

    # Snapshot of GiveawayEntryAction.entry_quantity at write time, so
    # reconfiguring an action's weight later never rewrites past entries.
    entry_quantity = db.Column(db.Integer, nullable=False, default=1, server_default='1')

    verification_status = db.Column(db.String(20), nullable=False, default='verified', server_default='verified')
    verification_method = db.Column(db.String(20), nullable=True)
    evidence = db.Column(db.Text, nullable=True)
    ip_address = db.Column(db.String(64), nullable=True)
    user_agent = db.Column(db.String(300), nullable=True)
    entry_metadata = db.Column(db.JSON, nullable=True)

    invalidated = db.Column(db.Boolean, nullable=False, default=False, server_default='false')
    invalidated_reason = db.Column(db.Text, nullable=True)
    invalidated_by = db.Column(db.String(50), db.ForeignKey('user.public_id'), nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    __table_args__ = (
        db.UniqueConstraint('participation_id', 'action_key', 'related_participation_id',
                             name='uq_giveaway_entry_participation_action_related'),
    )

    def __repr__(self):
        return f'GiveawayEntry({self.id}) participation={self.participation_id} {self.action_key} +{self.entry_quantity}'


class GiveawayReferralClick(db.Model):
    """Raw click log for a participant's own referral link (?ref=<code> on
    the landing page) -- parallel to CampaignLinkClick, but keyed by a
    participation's referral_code rather than a channel CampaignLink, since
    a per-participant row in CampaignLink itself would conflate channel-level
    tracking (a handful of rows) with per-person referral identity
    (potentially thousands)."""
    __tablename__ = 'giveaway_referral_click'

    id = db.Column(db.Integer, primary_key=True)
    participation_id = db.Column(db.Integer, db.ForeignKey('giveaway_participation.id'), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    referrer = db.Column(db.String(500), nullable=True)
    user_agent = db.Column(db.String(300), nullable=True)
    country = db.Column(db.String(100), nullable=True)
    ip_address = db.Column(db.String(64), nullable=True)

    def __repr__(self):
        return f'GiveawayReferralClick({self.id}) participation={self.participation_id}'


class GiveawayDrawSnapshot(db.Model):
    """A frozen eligible pool, taken once when entries close for a draw.
    pool_json is the actual frozen list ([{participation_id, entries}, ...])
    -- later entry/ledger changes (even a legitimate late invalidation) can
    never retroactively alter a draw already run against this snapshot."""
    __tablename__ = 'giveaway_draw_snapshot'

    id = db.Column(db.Integer, primary_key=True)
    campaign_id = db.Column(db.Integer, db.ForeignKey('giveaway_campaign.id'), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    eligible_count = db.Column(db.Integer, nullable=False, default=0)
    pool_json = db.Column(db.JSON, nullable=False)
    rules_applied = db.Column(db.JSON, nullable=True)
    created_by = db.Column(db.String(50), db.ForeignKey('user.public_id'), nullable=True)

    draws = db.relationship('GiveawayDraw', backref='snapshot', lazy=True, cascade='all, delete-orphan')

    def __repr__(self):
        return f'GiveawayDrawSnapshot({self.id}) campaign={self.campaign_id} n={self.eligible_count}'


class GiveawayDraw(db.Model):
    """One drawn result -- the winner is its own row; each backup winner is
    an additional row against the SAME snapshot (is_backup=True,
    backup_rank=1,2,...), so nothing about a past draw is ever overwritten,
    only added to."""
    __tablename__ = 'giveaway_draw'

    id = db.Column(db.Integer, primary_key=True)
    campaign_id = db.Column(db.Integer, db.ForeignKey('giveaway_campaign.id'), nullable=False, index=True)
    snapshot_id = db.Column(db.Integer, db.ForeignKey('giveaway_draw_snapshot.id'), nullable=False, index=True)
    drawn_at = db.Column(db.DateTime, default=datetime.utcnow)
    algorithm = db.Column(db.String(60), nullable=False, default='secrets_weighted_random', server_default='secrets_weighted_random')
    winner_participation_id = db.Column(db.Integer, db.ForeignKey('giveaway_participation.id'), nullable=False)
    is_backup = db.Column(db.Boolean, nullable=False, default=False, server_default='false')
    backup_rank = db.Column(db.Integer, nullable=True)
    drawn_by = db.Column(db.String(50), db.ForeignKey('user.public_id'), nullable=True)

    winner_participation = db.relationship('GiveawayParticipation', foreign_keys=[winner_participation_id])

    def __repr__(self):
        return f'GiveawayDraw({self.id}) campaign={self.campaign_id} winner={self.winner_participation_id} backup={self.is_backup}'


class GiveawayEntryThrottle(db.Model):
    """Per-IP, per-day counter on new giveaway-participant creation --
    identical (identity, usage_date) shape to backend/analytics/modals/
    visitor.py's VisitorIpThrottle and backend/guest/modals/guest_throttle.py's
    GuestSubmissionThrottle (same reasoning: this app runs serverless with
    pool_size=1, so an in-memory limiter would do nothing). Kept as its own
    table rather than reusing either of those, since this caps a distinct
    public write surface (giveaway entries) independently of guest posts or
    analytics sessions."""
    __tablename__ = 'giveaway_entry_throttle'

    id = db.Column(db.Integer, primary_key=True)
    identity = db.Column(db.String(64), nullable=False, index=True)
    usage_date = db.Column(db.Date, nullable=False, default=date.today, index=True)
    count = db.Column(db.Integer, nullable=False, default=0, server_default='0')

    __table_args__ = (
        db.UniqueConstraint('identity', 'usage_date', name='uq_giveaway_entry_throttle_identity_date'),
    )

    def __repr__(self):
        return f'GiveawayEntryThrottle({self.identity} {self.usage_date} x{self.count})'


GIVEAWAY_ENTRY_DAILY_CAP = 20


def check_and_record_giveaway_entry(request):
    """Returns True if allowed (and records it), False if today's cap is
    already hit for this IP. Call once, right before creating a new
    GiveawayParticipant/GiveawayParticipation row -- same "check, then
    commit together" contract as check_and_record_guest_submission."""
    from security import real_client_ip
    identity = f'ip:{real_client_ip() or "unknown"}'
    today = date.today()
    row = GiveawayEntryThrottle.query.filter_by(identity=identity, usage_date=today).first()
    if row is None:
        row = GiveawayEntryThrottle(identity=identity, usage_date=today, count=0)
        db.session.add(row)
    if row.count >= GIVEAWAY_ENTRY_DAILY_CAP:
        return False
    row.count += 1
    return True
