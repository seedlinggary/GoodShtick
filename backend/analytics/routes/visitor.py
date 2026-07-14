import random
import secrets
from datetime import datetime, timedelta

from flask import Blueprint, jsonify, make_response, request
from sqlalchemy import func

from config import cache, db
from security import super_admin_required, token_optional
from backend.analytics.modals.visitor import VisitorEvent, VisitorSession

analytics_api = Blueprint('analytics_api', __name__, url_prefix='/analytics')

ANON_COOKIE_NAME = 'anon_id'
ANON_COOKIE_MAX_AGE = 60 * 60 * 24 * 365  # ~1 year

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

    `force: true` in the JSON body is a TEST-ONLY escape hatch (see the class
    docstring on VisitorSession / task notes) that bypasses the "don't write
    localhost traffic" skip so the write path can be exercised from a dev
    machine -- rows written this way are still stamped is_localhost=True, so
    they're excluded from the real /analytics/dashboard aggregates either way.
    """
    body = request.get_json(silent=True) or {}
    force = bool(body.get('force'))

    anon_id = request.cookies.get(ANON_COOKIE_NAME)
    is_new_cookie = not anon_id
    if not anon_id:
        anon_id = secrets.token_urlsafe(32)

    is_localhost = _looks_like_localhost()
    skip_write = is_localhost and not force

    if not skip_write:
        now = datetime.utcnow()
        country = request.headers.get('x-vercel-ip-country') or None

        session_row = VisitorSession.query.filter_by(anonymous_id=anon_id).first()
        if session_row:
            session_row.last_seen = now
            session_row.page_view_count = (session_row.page_view_count or 0) + 1
            session_row.is_localhost = is_localhost
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
                is_localhost=is_localhost,
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

    resp = make_response(jsonify({'message': 'ok'}))
    if is_new_cookie:
        # Frontend and backend are separate Vercel deployments (different
        # origins), so this is a cross-site fetch() in production -- SameSite=Lax
        # cookies are NOT sent on cross-site XHR/fetch (only top-level nav), which
        # would silently make every page view look like a brand-new anonymous
        # visitor. SameSite=None (+ the Secure it requires) fixes that; local HTTP
        # dev can't set Secure cookies at all, so it falls back to Lax there,
        # where same-origin/localhost fetches work fine either way.
        if is_localhost:
            resp.set_cookie(
                ANON_COOKIE_NAME, anon_id,
                max_age=ANON_COOKIE_MAX_AGE, httponly=True, samesite='Lax',
            )
        else:
            resp.set_cookie(
                ANON_COOKIE_NAME, anon_id,
                max_age=ANON_COOKIE_MAX_AGE, httponly=True, samesite='None', secure=True,
            )
    return resp


@analytics_api.route('/logout', methods=['POST'])
def logout_reset():
    """Clears the anon_id cookie on sign-out.

    Without this, a browser that ever logged in keeps the SAME anon_id
    forever (see beacon()'s backfill), so VisitorSession.user_id -- set once,
    never cleared -- permanently misclassifies that browser as "logged in"
    even after signing out and browsing anonymously. Dropping the cookie here
    makes the next beacon() call mint a fresh anon_id, so genuinely anonymous
    post-logout activity lands in a new, correctly-anonymous session row. The
    old session row is untouched and still accurately reflects the time the
    visitor spent logged in.
    """
    resp = make_response(jsonify({'message': 'ok'}))
    if _looks_like_localhost():
        resp.set_cookie(ANON_COOKIE_NAME, '', max_age=0, httponly=True, samesite='Lax')
    else:
        resp.set_cookie(ANON_COOKIE_NAME, '', max_age=0, httponly=True, samesite='None', secure=True)
    return resp


def _visitor_counts(days):
    cutoff = datetime.utcnow() - timedelta(days=days)
    base = VisitorSession.query.filter(
        VisitorSession.last_seen >= cutoff,
        VisitorSession.is_localhost.is_(False),
    )
    total = base.with_entities(func.count(func.distinct(VisitorSession.anonymous_id))).scalar() or 0
    logged_in = (base.filter(VisitorSession.user_id.isnot(None))
                 .with_entities(func.count(func.distinct(VisitorSession.anonymous_id))).scalar() or 0)
    return {'total': total, 'logged_in': logged_in, 'anonymous': total - logged_in}


@analytics_api.route('/dashboard', methods=['GET'])
@super_admin_required
@cache.cached(timeout=60)
def dashboard(_current_user):
    visitors = {
        '7d': _visitor_counts(7),
        '30d': _visitor_counts(30),
        '90d': _visitor_counts(90),
    }

    avg_seconds = (db.session.query(
        func.avg(func.extract('epoch', VisitorSession.last_seen - VisitorSession.first_seen)))
        .filter(VisitorSession.is_localhost.is_(False))
        .scalar())
    # Postgres AVG(extract(epoch, ...)) comes back as a Decimal; Flask's JSON
    # provider silently serializes Decimal as a *string*, which would make
    # this field inconsistent with every other numeric field in the payload.
    # Cast to float first so it round-trips as a real JSON number.
    avg_session_minutes = round(float(avg_seconds or 0) / 60, 1)

    country_rows = (db.session.query(
        func.coalesce(VisitorSession.country, 'Unknown').label('country'),
        func.count(func.distinct(VisitorSession.anonymous_id)).label('visitor_count'))
        .filter(VisitorSession.is_localhost.is_(False))
        .group_by('country')
        .order_by(func.count(func.distinct(VisitorSession.anonymous_id)).desc())
        .limit(10).all())
    top_countries = [{'country': c, 'count': n} for c, n in country_rows]

    trend_cutoff = datetime.utcnow() - timedelta(days=30)
    day_col = func.date(VisitorSession.first_seen)
    trend_rows = (db.session.query(
        day_col.label('day'),
        func.count(func.distinct(VisitorSession.anonymous_id)).label('new_visitors'))
        .filter(VisitorSession.first_seen >= trend_cutoff, VisitorSession.is_localhost.is_(False))
        .group_by('day')
        .order_by('day')
        .all())
    daily_trend = [{'date': str(d), 'count': n} for d, n in trend_rows]

    return jsonify({
        'visitors': visitors,
        'avg_session_minutes': avg_session_minutes,
        'top_countries': top_countries,
        'daily_trend': daily_trend,
    })
