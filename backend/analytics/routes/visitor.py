import random
import secrets
from collections import Counter, defaultdict
from datetime import datetime, timedelta

from flask import Blueprint, jsonify, request
from sqlalchemy import func

from config import cache, db
from security import super_admin_required, token_optional, real_client_ip
from backend.analytics.modals.visitor import VisitorEvent, VisitorIpThrottle, VisitorSession
from backend.business.modals.business import Business
from backend.business.modals.business_site import BusinessSite
from backend.user.modals.user import User

analytics_api = Blueprint('analytics_api', __name__, url_prefix='/analytics')

RETENTION_DAYS = 90

# Caps how many BRAND-NEW VisitorSession rows (not total beacon calls) one
# IP can create per day -- see VisitorIpThrottle's own comment for why this
# is scoped to new sessions specifically. Generous on purpose: a busy
# shared IP (office, school, shul WiFi) can easily be dozens of distinct
# real people in a day; this is here to stop a four-digit flood from one
# IP, not to police ordinary shared-NAT traffic.
NEW_SESSION_DAILY_CAP = 60

# Substrings checked against a lowercased User-Agent header to recognize
# the vast majority of unsophisticated scrapers/bots, which hit a bare
# JSON beacon endpoint using their library's default UA string rather than
# bothering to spoof a real browser. Not a security boundary (any bot that
# sets a normal-looking UA sails right through) -- just enough to stop the
# analytics dashboard from being polluted by the common case. Matched
# bots are silently no-op'd (never written to the DB at all), same
# "ok" response either way so a blocked bot gets no signal to adapt to.
BOT_UA_SUBSTRINGS = (
    'bot', 'crawl', 'spider', 'slurp', 'headless', 'phantom', 'puppeteer',
    'playwright', 'selenium', 'scrapy', 'curl', 'wget', 'python-requests',
    'python-urllib', 'go-http-client', 'java/', 'libwww-perl', 'axios/',
    'facebookexternalhit', 'preview', 'monitor', 'uptime', 'pingdom',
)


def _looks_like_bot_ua():
    ua = (request.headers.get('User-Agent') or '').lower()
    if not ua:
        return True  # a real browser always sends one
    return any(s in ua for s in BOT_UA_SUBSTRINGS)


def _check_and_record_new_session():
    """Mirrors check_and_record_guest_submission's shape exactly (see
    backend/guest/modals/guest_throttle.py) -- True if this IP is still
    under NEW_SESSION_DAILY_CAP new sessions today (and records one),
    False if it's already maxed out. real_client_ip(), not
    request.remote_addr -- see that function's own comment; this was the
    bug that made every NEW visitor site-wide share one daily bucket."""
    identity = f'ip:{real_client_ip() or "unknown"}'
    today = datetime.utcnow().date()
    row = VisitorIpThrottle.query.filter_by(identity=identity, usage_date=today).first()
    if row is None:
        row = VisitorIpThrottle(identity=identity, usage_date=today, count=0)
        db.session.add(row)
    if row.count >= NEW_SESSION_DAILY_CAP:
        return False
    row.count += 1
    return True


# Lazy-cleanup approach (chosen over a vercel.json cron entry): this repo has
# no cron wiring yet and getting Vercel's cron schema exactly right without
# being able to verify it against a real deploy is a good way to ship a cron
# job that silently never fires. A small random chance of a cleanup sweep on
# every tracked write is simpler, needs no deploy-time config, and — at any
# real traffic volume — converges on the same steady-state table size a cron
# job would give you, just with slightly fuzzier timing.
CLEANUP_CHANCE = 0.02

_LOCALHOST_HOSTS = {'localhost', '127.0.0.1', '0.0.0.0'}


def _looks_like_localhost():
    """Belt-and-braces second check behind the frontend's own localhost gate
    (VisitorTracker.js) -- looks at the Host header, falling back to
    Origin/Referer (useful when the frontend dev server and API run on
    different localhost ports)."""
    host = (request.host or '').split(':')[0].lower()
    if host in _LOCALHOST_HOSTS:
        return True
    origin = (request.headers.get('Origin') or request.headers.get('Referer') or '').lower()
    return any(h in origin for h in _LOCALHOST_HOSTS)


def _staff_public_ids():
    """public_ids of admin/super_admin accounts -- excluded from every visitor
    metric below. Their own testing/moderation activity isn't real visitor
    behavior and skewed multiple stats in practice (an 8+ hour work session
    once dragged the average "session length" up by orders of magnitude)."""
    return {u.public_id for u in User.query.filter(User.role.in_(('admin', 'super_admin'))).all()}


def _exclude_staff(query, staff_ids):
    if not staff_ids:
        return query
    return query.filter(db.or_(VisitorSession.user_id.is_(None), ~VisitorSession.user_id.in_(staff_ids)))


def _maybe_cleanup():
    """Opportunistically purge rows past the 90-day retention window. Never
    allowed to break the beacon request that triggered it."""
    if random.random() >= CLEANUP_CHANCE:
        return
    try:
        cutoff = datetime.utcnow() - timedelta(days=RETENTION_DAYS)
        VisitorSession.query.filter(VisitorSession.last_seen < cutoff).delete(synchronize_session=False)
        VisitorEvent.query.filter(VisitorEvent.created_at < cutoff).delete(synchronize_session=False)
        db.session.commit()
    except Exception:
        db.session.rollback()


@analytics_api.route('/beacon', methods=['POST'])
@token_optional
def beacon(current_user):
    """Public page-view beacon, called once per page load / route change by
    VisitorTracker.js. Never requires auth, but backfills VisitorSession.user_id
    when a valid x-access-token happens to be present, so an anonymous visitor
    who later logs in gets linked to their earlier anonymous activity.

    The anonymous id is generated and persisted client-side (localStorage),
    not via a cookie -- frontend and backend are separate Vercel deployments
    (different origins), so a cookie set here would be a cross-site/third-party
    cookie from the page's point of view, and browsers increasingly restrict
    or outright drop those (Safari ITP, Firefox ETP, and similar are now the
    default posture for a large share of real traffic, not an edge case).
    That silently made nearly every page view look like a brand-new anonymous
    visitor. localStorage is same-origin only, so it isn't subject to any of
    that -- this matches how the JWT auth token is already handled elsewhere
    in this app (also localStorage, not a cookie), for the same reason.

    No analytics are ever written when the request originates from localhost
    -- unconditionally, no override. (An earlier version had a `force: true`
    escape hatch for exercising the write path from a dev machine; removed
    because any write from localhost, even one flagged and later filtered out
    of the dashboard, was still real dev/test traffic sitting in the
    production table.)

    Two bot defenses, both silent no-ops (never an error response, since a
    blocked bot should get no signal to adapt to -- it just doesn't land in
    the DB): an obvious-bot User-Agent (_looks_like_bot_ua) skips writing
    anything at all, and a brand-new session (this anon_id has never been
    seen before) is additionally gated by a per-IP daily cap
    (_check_and_record_new_session) -- see NEW_SESSION_DAILY_CAP's own
    comment for why only NEW sessions are capped, not every beacon call.
    """
    body = request.get_json(silent=True) or {}
    anon_id = (body.get('anon_id') or '').strip()[:64] or secrets.token_urlsafe(32)
    site = (body.get('site') or '').strip()[:20] or None

    is_localhost = _looks_like_localhost()
    is_bot = _looks_like_bot_ua()

    if not is_localhost and not is_bot:
        now = datetime.utcnow()
        country = request.headers.get('x-vercel-ip-country') or None

        # Every storefront subdomain self-reports the same generic
        # site='business-site' id (see siteMode.js's businessSiteDescriptor)
        # -- resolved here, server-side, from the subdomain the frontend
        # sends, rather than trusting a client-supplied business_id
        # directly. One extra indexed lookup, only on this path.
        business_id = None
        if site == 'business-site':
            subdomain = (body.get('subdomain') or '').strip()[:160] or None
            if subdomain:
                site_row = BusinessSite.query.filter_by(subdomain=subdomain).first()
                business_id = site_row.business_id if site_row else None

        session_row = VisitorSession.query.filter_by(anonymous_id=anon_id).first()
        if session_row:
            session_row.last_seen = now
            session_row.page_view_count = (session_row.page_view_count or 0) + 1
            if current_user and not session_row.user_id:
                session_row.user_id = current_user.public_id
            if site and not session_row.site:
                session_row.site = site
            if business_id and not session_row.business_id:
                session_row.business_id = business_id
        else:
            if not _check_and_record_new_session():
                db.session.commit()  # persist the throttle row's own increment/insert
                return jsonify({'message': 'ok', 'anon_id': anon_id})
            session_row = VisitorSession(
                anonymous_id=anon_id,
                user_id=current_user.public_id if current_user else None,
                country=country,
                first_seen=now,
                last_seen=now,
                page_view_count=1,
                is_localhost=False,
                site=site,
                business_id=business_id,
            )
            db.session.add(session_row)

        db.session.add(VisitorEvent(
            anonymous_id=anon_id,
            event_type='page_view',
            path=body.get('path'),
            created_at=now,
            site=site,
            business_id=business_id,
        ))
        db.session.commit()
        _maybe_cleanup()

    return jsonify({'message': 'ok', 'anon_id': anon_id})


def _filter_site(query, model, site):
    """Applies a `site` scope to a query, when one is given. `site=None` means
    "every sub-site" (the existing whole-platform dashboard's behavior,
    unchanged) -- it does NOT mean "rows with a null site," since plenty of
    pre-this-column history and any future untracked sub-site would have
    site=None on the row itself. Passing an explicit site string is the only
    way to narrow to one sub-site."""
    if site is None:
        return query
    return query.filter(model.site == site)


def _filter_business(query, model, business_ids):
    """Same shape as _filter_site, for the new business-site breakdown --
    `business_ids=None`/empty means "every business" (or every non-storefront
    row, when combined with a site filter that isn't 'business-site'), an
    explicit list narrows to just those owners' storefront traffic."""
    if not business_ids:
        return query
    return query.filter(model.business_id.in_(business_ids))


def _parse_business_ids(raw):
    if not raw:
        return None
    ids = []
    for part in raw.split(','):
        part = part.strip()
        if part.isdigit():
            ids.append(int(part))
    return ids or None


def _visitor_counts(days, staff_ids, site=None, business_ids=None):
    """Logged-in visitors are deduped by user_id (stable across every
    anonymous_id they might show up under -- different device, cleared
    localStorage, or any of the 6 sub-site origins, since VisitorSession.
    user_id is the same value everywhere per the SSO flow); anonymous
    visitors, who have no user_id, are still deduped by anonymous_id. Deduping
    everyone by anonymous_id (the old behavior) double/triple-counted any
    logged-in visitor who showed up under more than one anonymous_id."""
    cutoff = datetime.utcnow() - timedelta(days=days)
    base = _exclude_staff(VisitorSession.query.filter(
        VisitorSession.last_seen >= cutoff,
        VisitorSession.is_localhost.is_(False),
    ), staff_ids)
    base = _filter_site(base, VisitorSession, site)
    base = _filter_business(base, VisitorSession, business_ids)
    logged_in = (base.filter(VisitorSession.user_id.isnot(None))
                 .with_entities(func.count(func.distinct(VisitorSession.user_id))).scalar() or 0)
    anonymous = (base.filter(VisitorSession.user_id.is_(None))
                 .with_entities(func.count(func.distinct(VisitorSession.anonymous_id))).scalar() or 0)
    return {'total': logged_in + anonymous, 'logged_in': logged_in, 'anonymous': anonymous}


def _visitor_day_stats(site=None, business_ids=None):
    """anonymous_id -> (first-ever active date, count of distinct calendar
    days they've been active on), across all history -- not just the current
    window. One unified definition of "returning" is used everywhere below:
    a visitor becomes returning the moment they show up on a 2nd distinct
    calendar day, independent of any period boundary. (An earlier version
    defined "returning" for the period stat tiles as "first seen before this
    window started," which disagreed with the daily chart's "came back on a
    later day" definition for anyone whose first-ever visit fell inside the
    window -- same underlying data, two different day-vs-period-relative
    definitions producing different-looking numbers side by side. This is the
    one definition both use now.)

    When scoped to a `site`, "first-ever active day"/"distinct days" are
    both computed only from that site's own events -- otherwise someone who
    has browsed the main site for months but is brand new to the Business
    directory today would count as a "returning" business visitor, which
    isn't a useful answer to "is Business's own audience growing."""
    rows = db.session.query(
        VisitorEvent.anonymous_id,
        func.min(func.date(VisitorEvent.created_at)),
        func.count(func.distinct(func.date(VisitorEvent.created_at))))
    rows = _filter_site(rows, VisitorEvent, site)
    rows = _filter_business(rows, VisitorEvent, business_ids)
    rows = rows.group_by(VisitorEvent.anonymous_id).all()
    return {anon_id: (first_day, day_count) for anon_id, first_day, day_count in rows}


def _window_event_counts(days, staff_ids, site=None, business_ids=None):
    """anonymous_id -> how many of its own VisitorEvent rows fall in the last
    `days` days -- used to tell a true bounce (never came back at all, not
    even later in the window) apart from a visitor who's simply newly-seen
    this period but genuinely browsed."""
    cutoff = datetime.utcnow() - timedelta(days=days)
    query = (db.session.query(VisitorEvent.anonymous_id, func.count(VisitorEvent.id))
             .join(VisitorSession, VisitorSession.anonymous_id == VisitorEvent.anonymous_id)
             .filter(VisitorEvent.created_at >= cutoff, VisitorSession.is_localhost.is_(False)))
    query = _filter_site(query, VisitorEvent, site)
    query = _filter_business(query, VisitorEvent, business_ids)
    if staff_ids:
        query = query.filter(db.or_(VisitorSession.user_id.is_(None),
                                     ~VisitorSession.user_id.in_(staff_ids)))
    return dict(query.group_by(VisitorEvent.anonymous_id).all())


def _new_returning_bounced_counts(days, staff_ids, day_stats_by_id, site=None, business_ids=None):
    """Splits every visitor active in the window into exactly one of three
    buckets: bounced (never had more than a single page view across the
    WHOLE window -- the "didn't really visit" case), returning (2+ distinct
    calendar days active, ever), or new (neither). Mutually exclusive and
    exhaustive over the same active-visitor set _visitor_counts() totals, so
    the three numbers always sum to that total."""
    cutoff = datetime.utcnow() - timedelta(days=days)
    active = _exclude_staff(VisitorSession.query.filter(
        VisitorSession.last_seen >= cutoff, VisitorSession.is_localhost.is_(False),
    ), staff_ids)
    active = _filter_site(active, VisitorSession, site)
    active_ids = _filter_business(active, VisitorSession, business_ids).with_entities(VisitorSession.anonymous_id).distinct().all()
    window_counts = _window_event_counts(days, staff_ids, site, business_ids)
    new_count = 0
    returning_count = 0
    bounced_count = 0
    for (anon_id,) in active_ids:
        if window_counts.get(anon_id, 0) <= 1:
            bounced_count += 1
            continue
        _, day_count = day_stats_by_id.get(anon_id, (None, 1))
        if day_count >= 2:
            returning_count += 1
        else:
            new_count += 1
    return {'new': new_count, 'returning': returning_count, 'bounced': bounced_count}


def _daily_new_vs_returning(days, staff_ids, day_stats_by_id, site=None, business_ids=None):
    """Per-day new/returning/bounced split for the trend chart -- for each
    calendar day, how many distinct visitors were active, split three ways:
    bounced (only a single page view that specific day), or -- for everyone
    who looked at more than one page that day -- new (that day was their
    first-ever active day) vs. returning (a later, repeat day). Not
    `.distinct()`'d like the old version: telling a bounce apart from a real
    visit needs the actual per-(visitor, day) page-view COUNT, not just
    whether the pair occurred at all."""
    cutoff = datetime.utcnow() - timedelta(days=days)
    day_col = func.date(VisitorEvent.created_at)
    pairs = (db.session.query(VisitorEvent.anonymous_id, day_col.label('day'))
             .join(VisitorSession, VisitorSession.anonymous_id == VisitorEvent.anonymous_id)
             .filter(VisitorEvent.created_at >= cutoff, VisitorSession.is_localhost.is_(False)))
    pairs = _filter_site(pairs, VisitorEvent, site)
    pairs = _filter_business(pairs, VisitorEvent, business_ids)
    if staff_ids:
        pairs = pairs.filter(db.or_(VisitorSession.user_id.is_(None),
                                     ~VisitorSession.user_id.in_(staff_ids)))
    day_event_counts = Counter(pairs.all())  # (anon_id, day) -> page views that day

    daily = defaultdict(lambda: {'new': 0, 'returning': 0, 'bounced': 0})
    for (anon_id, day), count in day_event_counts.items():
        if count <= 1:
            daily[str(day)]['bounced'] += 1
            continue
        first_day, _ = day_stats_by_id.get(anon_id, (day, 1))
        bucket = 'new' if first_day == day else 'returning'
        daily[str(day)][bucket] += 1
    return [{'date': d, **counts} for d, counts in sorted(daily.items())]


SESSION_GAP_MINUTES = 30
# A single segment can still span many gaps each under SESSION_GAP_MINUTES
# (e.g. a tab left open, glanced at every ~29 minutes) -- capped here so one
# such outlier can't dominate the average at this site's traffic volume.
MAX_SESSION_MINUTES = 60


def _session_duration_stats(days, staff_ids, site=None, business_ids=None):
    """Splits each anonymous_id's events into visit segments -- consecutive
    events with no gap over SESSION_GAP_MINUTES count as the same visit, a
    bigger gap starts a new one -- and summarizes how long visits last.
    Deliberately a plain Python loop over an already-fetched, ordered query
    result rather than a SQL window function: this codebase has no window-
    function precedent elsewhere, and the dataset is small at this site's
    (solo-scale) traffic volume."""
    cutoff = datetime.utcnow() - timedelta(days=days)
    query = (db.session.query(VisitorEvent.anonymous_id, VisitorEvent.created_at)
             .join(VisitorSession, VisitorSession.anonymous_id == VisitorEvent.anonymous_id)
             .filter(VisitorEvent.created_at >= cutoff, VisitorSession.is_localhost.is_(False)))
    query = _filter_site(query, VisitorEvent, site)
    query = _filter_business(query, VisitorEvent, business_ids)
    if staff_ids:
        query = query.filter(db.or_(VisitorSession.user_id.is_(None),
                                     ~VisitorSession.user_id.in_(staff_ids)))
    rows = query.distinct().order_by(VisitorEvent.anonymous_id, VisitorEvent.created_at).all()

    durations = []
    current_id = None
    seg_first = seg_last = None
    for anon_id, created_at in rows:
        if anon_id != current_id:
            if seg_first is not None:
                durations.append((seg_last - seg_first).total_seconds() / 60)
            current_id = anon_id
            seg_first = seg_last = created_at
        else:
            if (created_at - seg_last).total_seconds() > SESSION_GAP_MINUTES * 60:
                durations.append((seg_last - seg_first).total_seconds() / 60)
                seg_first = created_at
            seg_last = created_at
    if seg_first is not None:
        durations.append((seg_last - seg_first).total_seconds() / 60)

    if not durations:
        return {'avg_minutes': 0, 'avg_minutes_engaged': 0, 'bounce_rate': 0}
    # Two fixes to a figure that was previously inflated:
    # 1. A bounce (single-page-view visit) segments to a duration of exactly
    #    0 above -- these used to be dropped from the average entirely
    #    (averaging only non-zero durations), which skews the result upward
    #    by excluding precisely the visits that would pull it down the most.
    #    They're now counted as 0, same as any other real visit length, in
    #    `avg_minutes` -- the honest "across every visit" figure.
    # 2. A session with no further activity for up to SESSION_GAP_MINUTES
    #    between events is still one segment, so someone glancing back at an
    #    idle tab every ~29 minutes for hours could register as one
    #    multi-hour "session" with nothing capping it -- at this site's
    #    solo-scale traffic volume, one such outlier could swing the whole
    #    average. Capped at MAX_SESSION_MINUTES, same reasoning as the gap
    #    cutoff itself: past a certain point this proxy stops being a
    #    trustworthy measurement anyway.
    capped = [min(d, MAX_SESSION_MINUTES) for d in durations]
    avg_minutes = round(sum(capped) / len(capped), 1)
    # `avg_minutes_engaged`: the OTHER honest question -- among visits that
    # went past a single page, how long do they tend to last? Answers "when
    # someone does stick around, how long for", which `avg_minutes` alone
    # can't -- a near-zero overall average (dominated by a high bounce rate)
    # would otherwise hide a perfectly healthy engaged-visit length.
    engaged = [d for d in capped if d > 0]
    avg_minutes_engaged = round(sum(engaged) / len(engaged), 1) if engaged else 0
    bounce_rate = round(100 * sum(1 for d in durations if d == 0) / len(durations), 1)
    return {'avg_minutes': avg_minutes, 'avg_minutes_engaged': avg_minutes_engaged, 'bounce_rate': bounce_rate}


def _top_paths(days, staff_ids, site=None, business_ids=None, limit=10):
    cutoff = datetime.utcnow() - timedelta(days=days)
    query = (db.session.query(VisitorEvent.path, func.count().label('count'))
             .join(VisitorSession, VisitorSession.anonymous_id == VisitorEvent.anonymous_id)
             .filter(VisitorEvent.created_at >= cutoff, VisitorSession.is_localhost.is_(False),
                     VisitorEvent.path.isnot(None), VisitorEvent.path != ''))
    query = _filter_site(query, VisitorEvent, site)
    query = _filter_business(query, VisitorEvent, business_ids)
    if staff_ids:
        query = query.filter(db.or_(VisitorSession.user_id.is_(None),
                                     ~VisitorSession.user_id.in_(staff_ids)))
    rows = (query.group_by(VisitorEvent.path)
            .order_by(func.count().desc())
            .limit(limit).all())
    return [{'path': p, 'count': n} for p, n in rows]


def build_dashboard_payload(site=None, business_ids=None):
    """Shared by the whole-platform dashboard (site=None), the Business-only
    one (site='business', see business_analytics.py), and the per-storefront
    one (site='business-site', optionally narrowed further to business_ids
    -- see business_site_dashboard() below) -- same metrics, just scoped to
    one sub-site's (and optionally one or more businesses') own
    sessions/events when given."""
    staff_ids = _staff_public_ids()

    visitors = {
        '7d': _visitor_counts(7, staff_ids, site, business_ids),
        '30d': _visitor_counts(30, staff_ids, site, business_ids),
        '90d': _visitor_counts(90, staff_ids, site, business_ids),
    }

    avg_base = _exclude_staff(VisitorSession.query.filter(VisitorSession.is_localhost.is_(False)), staff_ids)
    avg_base = _filter_site(avg_base, VisitorSession, site)
    avg_views = _filter_business(avg_base, VisitorSession, business_ids).with_entities(func.avg(VisitorSession.page_view_count)).scalar()
    avg_page_views = round(float(avg_views or 0), 1)

    country_base = _exclude_staff(db.session.query(
        func.coalesce(VisitorSession.country, 'Unknown').label('country'),
        func.count(func.distinct(VisitorSession.anonymous_id)).label('visitor_count'))
        .filter(VisitorSession.is_localhost.is_(False)), staff_ids)
    country_base = _filter_site(country_base, VisitorSession, site)
    country_rows = (_filter_business(country_base, VisitorSession, business_ids)
        .group_by('country')
        .order_by(func.count(func.distinct(VisitorSession.anonymous_id)).desc())
        .limit(10).all())
    top_countries = [{'country': c, 'count': n} for c, n in country_rows]

    day_stats_by_id = _visitor_day_stats(site, business_ids)
    new_vs_returning = {
        '7d': _new_returning_bounced_counts(7, staff_ids, day_stats_by_id, site, business_ids),
        '30d': _new_returning_bounced_counts(30, staff_ids, day_stats_by_id, site, business_ids),
        '90d': _new_returning_bounced_counts(90, staff_ids, day_stats_by_id, site, business_ids),
    }
    daily_new_vs_returning = _daily_new_vs_returning(30, staff_ids, day_stats_by_id, site, business_ids)

    trend_cutoff = datetime.utcnow() - timedelta(days=30)
    day_col = func.date(VisitorSession.first_seen)
    trend_base = _exclude_staff(db.session.query(
        day_col.label('day'),
        func.count(func.distinct(VisitorSession.anonymous_id)).label('new_visitors'))
        .filter(VisitorSession.first_seen >= trend_cutoff, VisitorSession.is_localhost.is_(False)), staff_ids)
    trend_base = _filter_site(trend_base, VisitorSession, site)
    trend_rows = (_filter_business(trend_base, VisitorSession, business_ids)
        .group_by('day')
        .order_by('day')
        .all())
    daily_trend = [{'date': str(d), 'count': n} for d, n in trend_rows]

    payload = {
        'visitors': visitors,
        'avg_page_views': avg_page_views,
        'top_countries': top_countries,
        'daily_trend': daily_trend,
        'new_vs_returning': new_vs_returning,
        'daily_new_vs_returning': daily_new_vs_returning,
        'session_duration': _session_duration_stats(7, staff_ids, site, business_ids),
        'top_paths': _top_paths(7, staff_ids, site, business_ids),
    }

    # Per-sub-site breakdown -- only meaningful on the whole-platform view;
    # a scoped dashboard (site='business', or any business_ids filter) is
    # already narrowed to one thing, so a by_site breakdown of it would just
    # repeat the same number.
    if site is None and not business_ids:
        payload['by_site'] = [
            {'site': key, 'label': label, **_visitor_counts(7, staff_ids, site=key)}
            for key, label in SITE_LABELS.items()
        ]

    return payload


@analytics_api.route('/dashboard', methods=['GET'])
@super_admin_required
@cache.cached(timeout=60, query_string=True)
def dashboard(_current_user):
    site = (request.args.get('site') or '').strip() or None
    business_ids = _parse_business_ids(request.args.get('business_id'))
    return jsonify(build_dashboard_payload(site=site, business_ids=business_ids))


@analytics_api.route('/business-site-businesses', methods=['GET'])
@super_admin_required
@cache.cached(timeout=60)
def business_site_businesses(_current_user):
    """Every business with at least one tracked storefront visitor session,
    for the business-site analytics section's "all businesses / just these"
    picker -- deliberately not just every claimed business, since most of
    those have no storefront traffic (or no storefront at all) to filter
    down to."""
    rows = (db.session.query(Business.id, Business.name, Business.slug)
            .join(VisitorSession, VisitorSession.business_id == Business.id)
            .filter(VisitorSession.is_localhost.is_(False))
            .distinct()
            .order_by(Business.name)
            .all())
    return jsonify({'businesses': [{'id': i, 'name': n, 'slug': s} for i, n, s in rows]})


SITE_LABELS = {
    'main': 'Gut Shtick', 'business': 'Gut Community', 'estates': 'Gut Estates',
    'money': 'Gut Money', 'torah': 'Gut Torah', 'news': 'Gut News',
}
PAGE_SIZE = 50

SORTABLE_FIELDS = {
    'user_name', 'site', 'country', 'first_seen', 'last_seen',
    'page_view_count', 'days_active', 'business_name',
}
DEFAULT_SORT = [('last_seen', True)]  # True = descending


def _parse_sort(raw):
    """Parses a comma-separated "field:dir,field2:dir2" priority-sort spec
    into an ordered list of (field, descending) pairs, most important
    first -- e.g. "page_view_count:desc,last_seen:asc" sorts by page views,
    breaking ties by last seen. Unknown fields are silently dropped rather
    than erroring, same "a bad filter just does nothing" posture as the
    rest of this endpoint."""
    if not raw:
        return list(DEFAULT_SORT)
    keys = []
    for part in raw.split(','):
        part = part.strip()
        if not part:
            continue
        field, _, direction = part.partition(':')
        field = field.strip()
        if field not in SORTABLE_FIELDS:
            continue
        keys.append((field, direction.strip().lower() == 'desc'))
    return keys or list(DEFAULT_SORT)


def _sort_value(row, field):
    """row holds raw typed values (datetimes, ints), not yet stringified --
    sorting those directly is what makes chronological/numeric ordering
    correct, rather than comparing ISO strings lexically. Missing values
    sort last regardless of direction, via the most extreme value for
    whatever type the column holds."""
    v = row.get(field)
    if v is None:
        if field in ('page_view_count', 'days_active'):
            return -1
        if field in ('first_seen', 'last_seen'):
            return datetime.min
        return ''
    return v.lower() if isinstance(v, str) else v


@analytics_api.route('/sessions', methods=['GET'])
@super_admin_required
def list_sessions(_current_user):
    """Who's actually showing up -- a filterable, named list behind the
    aggregate counts on /dashboard, since "47 returning visitors" doesn't
    tell you WHO. Each row names the logged-in visitor when there is one
    (profile name), and flags whether they're a repeat visitor using the
    exact same "2+ distinct calendar days active" definition the dashboard
    trend chart uses, so the two views of "returning" never disagree.

    Supports filtering by any column (name/site/country/view-count
    range/business) and a multi-column priority sort (?sort=
    field:dir,field2:dir2, see _parse_sort) -- both applied in Python over
    every matching row before pagination, same approach repeat_only already
    used, since this dataset is small at this site's traffic volume and a
    dozen small per-row lookups (day stats, user names, business names)
    don't translate cleanly into one SQL ORDER BY anyway."""
    site = (request.args.get('site') or '').strip() or None
    business_ids = _parse_business_ids(request.args.get('business_id'))
    try:
        days = max(1, min(365, int(request.args.get('days', 30))))
    except (TypeError, ValueError):
        days = 30
    repeat_only = request.args.get('repeat_only') in ('1', 'true', 'True')
    logged_in_filter = (request.args.get('logged_in') or '').strip().lower()
    country = (request.args.get('country') or '').strip() or None
    name_filter = (request.args.get('name') or '').strip().lower() or None
    site_filter_text = (request.args.get('site_text') or '').strip().lower() or None
    min_views = max_views = None
    try:
        if request.args.get('min_views'):
            min_views = int(request.args.get('min_views'))
    except (TypeError, ValueError):
        pass
    try:
        if request.args.get('max_views'):
            max_views = int(request.args.get('max_views'))
    except (TypeError, ValueError):
        pass
    sort_keys = _parse_sort(request.args.get('sort'))
    try:
        page = max(1, int(request.args.get('page', 1)))
    except (TypeError, ValueError):
        page = 1

    staff_ids = _staff_public_ids()
    cutoff = datetime.utcnow() - timedelta(days=days)
    query = _exclude_staff(VisitorSession.query.filter(
        VisitorSession.last_seen >= cutoff, VisitorSession.is_localhost.is_(False),
    ), staff_ids)
    query = _filter_site(query, VisitorSession, site)
    query = _filter_business(query, VisitorSession, business_ids)
    if logged_in_filter == 'true':
        query = query.filter(VisitorSession.user_id.isnot(None))
    elif logged_in_filter == 'false':
        query = query.filter(VisitorSession.user_id.is_(None))
    if country:
        query = query.filter(func.lower(VisitorSession.country) == country.lower())

    day_stats = _visitor_day_stats(site, business_ids)
    raw_sessions = query.all()

    user_ids = {s.user_id for s in raw_sessions if s.user_id}
    users_by_id = {u.public_id: u for u in User.query.filter(User.public_id.in_(user_ids)).all()} if user_ids else {}
    business_ids_seen = {s.business_id for s in raw_sessions if s.business_id}
    businesses_by_id = ({b.id: b for b in Business.query.filter(Business.id.in_(business_ids_seen)).all()}
                         if business_ids_seen else {})

    rows = []
    for s in raw_sessions:
        day_count = day_stats.get(s.anonymous_id, (None, 1))[1]
        user = users_by_id.get(s.user_id)
        business = businesses_by_id.get(s.business_id)
        rows.append({
            'anonymous_id': s.anonymous_id[:12],
            'user_name': user.profile_name if user else None,
            'site': s.site or 'main',
            'site_label': SITE_LABELS.get(s.site or 'main', s.site or 'main'),
            'business_id': s.business_id,
            'business_name': business.name if business else None,
            'country': s.country or 'Unknown',
            'first_seen': s.first_seen,
            'last_seen': s.last_seen,
            'page_view_count': s.page_view_count or 0,
            'days_active': day_count,
            'is_returning': day_count >= 2,
        })

    if repeat_only:
        rows = [r for r in rows if r['is_returning']]
    if name_filter:
        rows = [r for r in rows if name_filter in (r['user_name'] or 'anonymous').lower()]
    if site_filter_text:
        rows = [r for r in rows if site_filter_text in (r['site_label'] or '').lower()]
    if min_views is not None:
        rows = [r for r in rows if r['page_view_count'] >= min_views]
    if max_views is not None:
        rows = [r for r in rows if r['page_view_count'] <= max_views]

    # Stable sort applied from the LEAST significant key to the MOST
    # significant -- Python's sort is stable, so each pass only breaks ties
    # left by the previous (higher-priority) pass, building up the correct
    # multi-column priority order with mixed asc/desc directions.
    for field, desc in reversed(sort_keys):
        rows.sort(key=lambda r: _sort_value(r, field), reverse=desc)

    total = len(rows)
    page_rows = rows[(page - 1) * PAGE_SIZE: page * PAGE_SIZE]

    def finalize(r):
        return {
            **r,
            'first_seen': r['first_seen'].isoformat() if r['first_seen'] else None,
            'last_seen': r['last_seen'].isoformat() if r['last_seen'] else None,
        }

    return jsonify({
        'sessions': [finalize(r) for r in page_rows],
        'total': total,
        'page': page,
        'has_more': page * PAGE_SIZE < total,
        'sites': SITE_LABELS,
        'sort': [f'{f}:{"desc" if d else "asc"}' for f, d in sort_keys],
    })
