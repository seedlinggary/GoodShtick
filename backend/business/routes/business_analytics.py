"""Click analytics for a business owner's own listing: profile views,
WhatsApp taps, directions taps, deal views/redemptions, shares -- reuses the
site-wide VisitorEvent table (see analytics/modals/visitor.py) rather than a
parallel tracking system, now that it carries a business_id column."""
import secrets
from datetime import datetime, timedelta

from flask import Blueprint, jsonify, request
from sqlalchemy import func

from config import cache, db
from security import token_optional, token_required, super_admin_required
from backend.analytics.routes.visitor import _looks_like_localhost, _staff_public_ids, build_dashboard_payload
from backend.analytics.modals.visitor import VisitorEvent, VisitorSession
from backend.business.modals.business import Business, BusinessLocation
from backend.user.modals.user import User
from upload import get_public_url

business_analytics_api = Blueprint('business_analytics_api', __name__, url_prefix='/business')

TRACKED_EVENTS = (
    'business_view', 'business_whatsapp_click', 'business_directions_click',
    'business_deal_view', 'business_deal_redeem', 'business_share',
)


def _can_manage(business, user):
    if not user:
        return False
    if user.is_boss:
        return True
    if business.owner_user_id:
        return business.owner_user_id == user.public_id
    return business.created_by == user.public_id


@business_analytics_api.route('/businesses/<int:business_id>/track', methods=['POST'])
@token_optional
def track_event(_current_user, business_id):
    """Fire-and-forget beacon, same shape/spirit as /analytics/beacon --
    never blocks or errors the UI action it's attached to."""
    body = request.get_json(silent=True) or {}
    event_type = body.get('event_type')
    if event_type not in TRACKED_EVENTS:
        return jsonify({'message': 'Unknown event_type'}), 400
    if _looks_like_localhost():
        return jsonify({'message': 'ok'})

    anon_id = (body.get('anon_id') or '').strip()[:64] or secrets.token_urlsafe(32)
    try:
        db.session.add(VisitorEvent(anonymous_id=anon_id, event_type=event_type,
                                     business_id=business_id, path=f'/business/{business_id}',
                                     site='business'))
        db.session.commit()
    except Exception:
        db.session.rollback()
    return jsonify({'message': 'ok'})


@business_analytics_api.route('/businesses/<int:business_id>/analytics', methods=['GET'])
@token_required
def business_analytics(current_user, business_id):
    business = db.session.get(Business, business_id)
    if not business or not _can_manage(business, current_user):
        return jsonify({'message': 'Not authorized'}), 403

    def counts_for(days):
        cutoff = datetime.utcnow() - timedelta(days=days)
        rows = (db.session.query(VisitorEvent.event_type, func.count(VisitorEvent.id))
                .filter(VisitorEvent.business_id == business_id, VisitorEvent.created_at >= cutoff)
                .group_by(VisitorEvent.event_type).all())
        by_type = {t: 0 for t in TRACKED_EVENTS}
        by_type.update({t: n for t, n in rows})
        return by_type

    daily_cutoff = datetime.utcnow() - timedelta(days=30)
    day_col = func.date(VisitorEvent.created_at)
    daily_rows = (db.session.query(day_col.label('day'), func.count(VisitorEvent.id))
                  .filter(VisitorEvent.business_id == business_id, VisitorEvent.created_at >= daily_cutoff,
                          VisitorEvent.event_type == 'business_view')
                  .group_by('day').order_by('day').all())

    return jsonify({
        '7d': counts_for(7),
        '30d': counts_for(30),
        '90d': counts_for(90),
        'daily_views': [{'date': str(d), 'count': n} for d, n in daily_rows],
    })


def _staff_anonymous_ids(staff_ids):
    """anonymous_ids belonging to a staff-linked session -- a super admin
    clicking around the directory (including while testing this very
    dashboard) shouldn't inflate "top viewed businesses"/"top locations"."""
    if not staff_ids:
        return set()
    rows = (VisitorSession.query.filter(VisitorSession.user_id.in_(staff_ids))
            .with_entities(VisitorSession.anonymous_id).all())
    return {r[0] for r in rows}


@business_analytics_api.route('/admin/analytics', methods=['GET'])
@super_admin_required
@cache.cached(timeout=60)
def admin_business_analytics(_current_user):
    """Site-wide Business analytics for the Super Admin dashboard: the same
    visitor/geography/new-vs-returning shape as GET /analytics/dashboard but
    scoped to just the Business sub-site's own traffic, plus a leaderboard of
    the most-viewed listings and the locations (business cities) drawing the
    most of that attention.

    Cached for the same reason /analytics/dashboard is: this is ~15 sequential
    aggregate queries (3 windows x {top businesses, its redemptions, top
    locations} plus the shared payload's own visitor/country/trend queries) --
    all 3 windows come back in one response so the frontend's window picker
    is a free client-side re-read, but a super admin re-opening this tab or
    hitting Refresh would otherwise re-run the whole thing every time for
    numbers that don't need to be second-fresh."""
    payload = build_dashboard_payload(site='business')

    staff_ids = _staff_public_ids()
    staff_anon_ids = _staff_anonymous_ids(staff_ids)

    def _exclude_staff_events(query):
        if not staff_anon_ids:
            return query
        return query.filter(VisitorEvent.anonymous_id.notin_(staff_anon_ids))

    def top_businesses_for(days):
        cutoff = datetime.utcnow() - timedelta(days=days)
        query = _exclude_staff_events(db.session.query(
            VisitorEvent.business_id, func.count(VisitorEvent.id).label('views'))
            .filter(VisitorEvent.event_type == 'business_view',
                    VisitorEvent.created_at >= cutoff,
                    VisitorEvent.business_id.isnot(None)))
        rows = query.group_by(VisitorEvent.business_id).order_by(func.count(VisitorEvent.id).desc()).limit(15).all()
        ids = [business_id for business_id, _ in rows]
        if not ids:
            return []
        businesses_by_id = {b.id: b for b in Business.query.filter(Business.id.in_(ids)).all()}
        redeem_rows = _exclude_staff_events(db.session.query(
            VisitorEvent.business_id, func.count(VisitorEvent.id))
            .filter(VisitorEvent.event_type == 'business_deal_redeem',
                    VisitorEvent.created_at >= cutoff,
                    VisitorEvent.business_id.in_(ids))
            .group_by(VisitorEvent.business_id)).all()
        redemptions_by_id = dict(redeem_rows)

        out = []
        for business_id, views in rows:
            b = businesses_by_id.get(business_id)
            if not b:
                continue  # deleted since the event was logged
            out.append({
                'id': b.id, 'name': b.name, 'slug': b.slug, 'category': b.category,
                'logo_url': get_public_url(b.logo) if b.logo else None,
                'views': views, 'redemptions': redemptions_by_id.get(business_id, 0),
            })
        return out

    def top_locations_for(days):
        cutoff = datetime.utcnow() - timedelta(days=days)
        query = _exclude_staff_events(db.session.query(
            func.coalesce(BusinessLocation.city, 'Unknown').label('city'),
            BusinessLocation.state,
            func.count(VisitorEvent.id).label('views'))
            .select_from(VisitorEvent)
            .join(Business, Business.id == VisitorEvent.business_id)
            .join(BusinessLocation, db.and_(
                BusinessLocation.business_id == Business.id,
                BusinessLocation.is_primary.is_(True)))
            .filter(VisitorEvent.event_type == 'business_view', VisitorEvent.created_at >= cutoff))
        rows = (query.group_by('city', BusinessLocation.state)
                .order_by(func.count(VisitorEvent.id).desc()).limit(15).all())
        return [{'city': c, 'state': s, 'views': n} for c, s, n in rows]

    payload['top_businesses'] = {
        '7d': top_businesses_for(7),
        '30d': top_businesses_for(30),
        '90d': top_businesses_for(90),
    }
    payload['top_locations'] = {
        '7d': top_locations_for(7),
        '30d': top_locations_for(30),
        '90d': top_locations_for(90),
    }
    return jsonify(payload)


@business_analytics_api.route('/admin/recent-additions', methods=['GET'])
@super_admin_required
def admin_recent_additions(_current_user):
    """Super Admin's "who's adding businesses, and from where" view --
    distinguishes a real owner self-listing their own business (imported is
    False, created_by is that owner) from a bulk import (imported is True,
    source_name says which site it came from, created_by is whichever
    account ran the import script). Filterable by who added it and by date
    range, so an admin can tell their own additions apart from a teammate's
    or from an unattended/random source.

    `added_by` is one of: omitted/'all', a user's public_id (their own
    self-submitted businesses only), 'imported:<source_name>' (that import
    source's businesses, source_name exactly as stored), 'imported' (any
    import, any source), or 'imported:__other__' (every import source NOT
    big enough to get its own dropdown entry -- see MIN_SOURCE_COUNT below)."""
    added_by = (request.args.get('added_by') or '').strip()
    since = (request.args.get('since') or '').strip()
    until = (request.args.get('until') or '').strip()
    try:
        page = max(1, int(request.args.get('page', 1)))
    except (TypeError, ValueError):
        page = 1
    per_page = 50

    # One real business import (the original kashrus-list bulk import) wrote
    # a distinct source_name per establishment-citation page rather than per
    # batch, so the raw list of distinct source_names runs into the hundreds
    # -- useless as a dropdown. Only sources this large get their own filter
    # entry; everything smaller is reachable via the single '__other__' bucket.
    MIN_SOURCE_COUNT = 30
    big_sources = [s for (s,) in db.session.query(Business.source_name)
                   .filter(Business.imported.is_(True), Business.source_name.isnot(None))
                   .group_by(Business.source_name)
                   .having(func.count(Business.id) >= MIN_SOURCE_COUNT).all()]

    query = Business.query

    if added_by == 'imported:__other__':
        query = query.filter(Business.imported.is_(True), Business.source_name.notin_(big_sources))
    elif added_by.startswith('imported:'):
        source = added_by[len('imported:'):]
        query = query.filter(Business.imported.is_(True), Business.source_name == source)
    elif added_by == 'imported':
        query = query.filter(Business.imported.is_(True))
    elif added_by:
        query = query.filter(Business.imported.is_(False), Business.created_by == added_by)

    if since:
        try:
            query = query.filter(Business.pub_date >= datetime.fromisoformat(since))
        except ValueError:
            return jsonify({'message': 'since must be an ISO date'}), 400
    if until:
        try:
            query = query.filter(Business.pub_date <= datetime.fromisoformat(until) + timedelta(days=1))
        except ValueError:
            return jsonify({'message': 'until must be an ISO date'}), 400

    total = query.count()
    rows = (query.options(db.selectinload(Business.locations))
            .order_by(Business.pub_date.desc())
            .offset((page - 1) * per_page).limit(per_page).all())

    creator_ids = {b.created_by for b in rows if b.created_by}
    creators_by_id = {}
    if creator_ids:
        for u in User.query.filter(User.public_id.in_(creator_ids)).all():
            creators_by_id[u.public_id] = u

    def added_by_label(b):
        if b.imported:
            return {'kind': 'imported', 'label': b.source_name or 'Imported', 'detail': b.source_url}
        creator = creators_by_id.get(b.created_by)
        if creator:
            return {'kind': 'user', 'label': creator.profile_name, 'detail': creator.email, 'public_id': creator.public_id}
        return {'kind': 'unknown', 'label': 'Unknown', 'detail': None}

    results = []
    for b in rows:
        loc = next((l for l in b.locations if l.is_primary), (b.locations[0] if b.locations else None))
        results.append({
            'id': b.id, 'name': b.name, 'slug': b.slug, 'category': b.category,
            'city': loc.city if loc else None, 'state': loc.state if loc else None,
            'is_claimed': b.is_claimed,
            'pub_date': b.pub_date.isoformat() if b.pub_date else None,
            'added_by': added_by_label(b),
        })

    # Filter-dropdown options: every distinct real self-submitter, and every
    # import source big enough to be worth its own entry (see big_sources
    # above) -- built unfiltered so the dropdown doesn't shrink to just
    # whatever the current filter already narrowed down to.
    has_other_sources = bool(
        db.session.query(Business.id)
        .filter(Business.imported.is_(True), Business.source_name.isnot(None), Business.source_name.notin_(big_sources))
        .first()
    )
    self_submitter_ids = [c for (c,) in db.session.query(Business.created_by)
                           .filter(Business.imported.is_(False), Business.created_by.isnot(None))
                           .distinct().all()]
    self_submitters = []
    if self_submitter_ids:
        for u in User.query.filter(User.public_id.in_(self_submitter_ids)).all():
            self_submitters.append({'public_id': u.public_id, 'name': u.profile_name, 'email': u.email})
    self_submitters.sort(key=lambda u: (u['name'] or '').lower())

    return jsonify({
        'results': results,
        'total': total,
        'page': page,
        'per_page': per_page,
        'has_more': page * per_page < total,
        'filters': {
            'import_sources': sorted(big_sources),
            'has_other_sources': has_other_sources,
            'self_submitters': self_submitters,
        },
    })


@business_analytics_api.route('/admin/businesses/search', methods=['GET'])
@super_admin_required
def admin_business_search(_current_user):
    """Super Admin's "find a business" lookup -- by its own name/slug/city,
    or by its owner's email/profile name, so support can jump straight to a
    business's account from a ticket that only gives them the owner's email.
    Returns everything needed to act on the result without a second click:
    a link into the public profile, a link into Owner Tools (now open to any
    super admin regardless of ownership -- see BusinessOwnerTools.js), and a
    quick view count so "see views and info about it" doesn't need the full
    Business Site Analytics tab open too."""
    q = (request.args.get('q') or '').strip()
    if not q:
        return jsonify({'results': []})
    like = f'%{q}%'

    matches = (Business.query
        .outerjoin(BusinessLocation, db.and_(
            BusinessLocation.business_id == Business.id,
            BusinessLocation.is_primary.is_(True)))
        .outerjoin(User, User.public_id == Business.owner_user_id)
        .filter(db.or_(
            Business.name.ilike(like),
            Business.slug.ilike(like),
            BusinessLocation.city.ilike(like),
            User.email.ilike(like),
            User.profile_name.ilike(like),
        ))
        .order_by(Business.name)
        .limit(25)
        .all())

    ids = [b.id for b in matches]
    views_by_id = {}
    if ids:
        cutoff_30d = datetime.utcnow() - timedelta(days=30)
        rows = (db.session.query(VisitorEvent.business_id, func.count(VisitorEvent.id))
                .filter(VisitorEvent.event_type == 'business_view',
                        VisitorEvent.business_id.in_(ids),
                        VisitorEvent.created_at >= cutoff_30d)
                .group_by(VisitorEvent.business_id).all())
        views_by_id = dict(rows)

    results = []
    for b in matches:
        loc = next((l for l in b.locations if l.is_primary), None)
        owner = b.owner  # None unless a claim has been approved (owner_user_id set)
        results.append({
            'id': b.id, 'name': b.name, 'slug': b.slug, 'category': b.category,
            'logo_url': get_public_url(b.logo) if b.logo else None,
            'is_claimed': b.is_claimed,
            'city': loc.city if loc else None, 'state': loc.state if loc else None,
            'owner_email': owner.email if owner else None,
            'owner_name': owner.profile_name if owner else None,
            'views_30d': views_by_id.get(b.id, 0),
            'pub_date': b.pub_date.isoformat() if b.pub_date else None,
        })
    return jsonify({'results': results})
