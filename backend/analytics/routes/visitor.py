import random
import secrets
from collections import defaultdict
from datetime import datetime, timedelta

from flask import Blueprint, jsonify, request
from sqlalchemy import func

from config import cache, db
from security import super_admin_required, token_optional
from backend.analytics.modals.visitor import VisitorEvent, VisitorSession
from backend.user.modals.user import User

analytics_api = Blueprint('analytics_api', __name__, url_prefix='/analytics')

RETENTION_DAYS = 90
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
    """
    body = request.get_json(silent=True) or {}
    anon_id = (body.get('anon_id') or '').strip()[:64] or secrets.token_urlsafe(32)

    is_localhost = _looks_like_localhost()

    if not is_localhost:
        now = datetime.utcnow()
        country = request.headers.get('x-vercel-ip-country') or None

        session_row = VisitorSession.query.filter_by(anonymous_id=anon_id).first()
        if session_row:
            session_row.last_seen = now
            session_row.page_view_count = (session_row.page_view_count or 0) + 1
            if current_user and not session_row.user_id:
                session_row.user_id = current_user.public_id
        else:
            session_row = VisitorSession(
                anonymous_id=anon_id,
                user_id=current_user.public_id if current_user else None,
                country=country,
                first_seen=now,
                last_seen=now,
                page_view_count=1,
                is_localhost=False,
            )
            db.session.add(session_row)

        db.session.add(VisitorEvent(
            anonymous_id=anon_id,
            event_type='page_view',
            path=body.get('path'),
            created_at=now,
        ))
        db.session.commit()
        _maybe_cleanup()

    return jsonify({'message': 'ok', 'anon_id': anon_id})


def _visitor_counts(days, staff_ids):
    cutoff = datetime.utcnow() - timedelta(days=days)
    base = _exclude_staff(VisitorSession.query.filter(
        VisitorSession.last_seen >= cutoff,
        VisitorSession.is_localhost.is_(False),
    ), staff_ids)
    total = base.with_entities(func.count(func.distinct(VisitorSession.anonymous_id))).scalar() or 0
    logged_in = (base.filter(VisitorSession.user_id.isnot(None))
                 .with_entities(func.count(func.distinct(VisitorSession.anonymous_id))).scalar() or 0)
    return {'total': total, 'logged_in': logged_in, 'anonymous': total - logged_in}


def _visitor_day_stats():
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
    one definition both use now.)"""
    rows = (db.session.query(
        VisitorEvent.anonymous_id,
        func.min(func.date(VisitorEvent.created_at)),
        func.count(func.distinct(func.date(VisitorEvent.created_at))))
        .group_by(VisitorEvent.anonymous_id).all())
    return {anon_id: (first_day, day_count) for anon_id, first_day, day_count in rows}


def _new_vs_returning_counts(days, staff_ids, day_stats_by_id):
    cutoff = datetime.utcnow() - timedelta(days=days)
    active_ids = (_exclude_staff(VisitorSession.query.filter(
        VisitorSession.last_seen >= cutoff, VisitorSession.is_localhost.is_(False),
    ), staff_ids)
        .with_entities(VisitorSession.anonymous_id).distinct().all())
    new_count = 0
    returning_count = 0
    for (anon_id,) in active_ids:
        _, day_count = day_stats_by_id.get(anon_id, (None, 1))
        if day_count >= 2:
            returning_count += 1
        else:
            new_count += 1
    return {'new': new_count, 'returning': returning_count}


def _daily_new_vs_returning(days, staff_ids, day_stats_by_id):
    """Per-day new/returning split for the trend chart -- for each calendar
    day, how many distinct visitors were active, split by whether that day
    was their first-ever active day or a later, repeat day."""
    cutoff = datetime.utcnow() - timedelta(days=days)
    day_col = func.date(VisitorEvent.created_at)
    pairs = (db.session.query(VisitorEvent.anonymous_id, day_col.label('day'))
             .join(VisitorSession, VisitorSession.anonymous_id == VisitorEvent.anonymous_id)
             .filter(VisitorEvent.created_at >= cutoff, VisitorSession.is_localhost.is_(False)))
    if staff_ids:
        pairs = pairs.filter(db.or_(VisitorSession.user_id.is_(None),
                                     ~VisitorSession.user_id.in_(staff_ids)))
    pairs = pairs.distinct().all()

    daily = defaultdict(lambda: {'new': 0, 'returning': 0})
    for anon_id, day in pairs:
        first_day, _ = day_stats_by_id.get(anon_id, (day, 1))
        bucket = 'new' if first_day == day else 'returning'
        daily[str(day)][bucket] += 1
    return [{'date': d, **counts} for d, counts in sorted(daily.items())]


@analytics_api.route('/dashboard', methods=['GET'])
@super_admin_required
@cache.cached(timeout=60)
def dashboard(_current_user):
    staff_ids = _staff_public_ids()

    visitors = {
        '7d': _visitor_counts(7, staff_ids),
        '30d': _visitor_counts(30, staff_ids),
        '90d': _visitor_counts(90, staff_ids),
    }

    avg_views = (_exclude_staff(VisitorSession.query.filter(VisitorSession.is_localhost.is_(False)), staff_ids)
                 .with_entities(func.avg(VisitorSession.page_view_count)).scalar())
    avg_page_views = round(float(avg_views or 0), 1)

    country_rows = (_exclude_staff(db.session.query(
        func.coalesce(VisitorSession.country, 'Unknown').label('country'),
        func.count(func.distinct(VisitorSession.anonymous_id)).label('visitor_count'))
        .filter(VisitorSession.is_localhost.is_(False)), staff_ids)
        .group_by('country')
        .order_by(func.count(func.distinct(VisitorSession.anonymous_id)).desc())
        .limit(10).all())
    top_countries = [{'country': c, 'count': n} for c, n in country_rows]

    day_stats_by_id = _visitor_day_stats()
    new_vs_returning = {
        '7d': _new_vs_returning_counts(7, staff_ids, day_stats_by_id),
        '30d': _new_vs_returning_counts(30, staff_ids, day_stats_by_id),
        '90d': _new_vs_returning_counts(90, staff_ids, day_stats_by_id),
    }
    daily_new_vs_returning = _daily_new_vs_returning(30, staff_ids, day_stats_by_id)

    trend_cutoff = datetime.utcnow() - timedelta(days=30)
    day_col = func.date(VisitorSession.first_seen)
    trend_rows = (_exclude_staff(db.session.query(
        day_col.label('day'),
        func.count(func.distinct(VisitorSession.anonymous_id)).label('new_visitors'))
        .filter(VisitorSession.first_seen >= trend_cutoff, VisitorSession.is_localhost.is_(False)), staff_ids)
        .group_by('day')
        .order_by('day')
        .all())
    daily_trend = [{'date': str(d), 'count': n} for d, n in trend_rows]

    return jsonify({
        'visitors': visitors,
        'avg_page_views': avg_page_views,
        'top_countries': top_countries,
        'daily_trend': daily_trend,
        'new_vs_returning': new_vs_returning,
        'daily_new_vs_returning': daily_new_vs_returning,
    })
