"""Cross-site "Discover" feed for the main Gut Shtick homepage -- merges the
most recent activity from four OTHER sites (Gut Money's job board, Gut
Estates' listings, Gut Community's new businesses and deals, Gut Torah's
posts) into one uniformly-shaped list, filterable by source and searchable
across all of them. This doesn't belong to any one site's own blueprint,
which is why it's its own top-level package rather than living under
backend/tachlis/, backend/estates/, etc.

Each source's rows are queried directly via its own ORM model (not an
internal HTTP call to that site's own blueprint) since this is all one Flask
app against one database -- the existing per-site list routes stay exactly
as they are, this just reads the same tables a second way for a different
shape. Merging/sorting/paginating happens in Python rather than a SQL UNION:
the five source tables share no common schema (different columns, id
spaces, and expiry/approval conventions), so a UNION would need five
per-branch CAST/NULL-AS projections just to align column lists, and
Postgres still couldn't push one ORDER BY/LIMIT through a UNION ALL of five
differently-filtered subqueries without materializing all of them anyway --
no performance win being given up by doing it in Python instead."""
from datetime import datetime, timedelta

from flask import Blueprint, jsonify, request
from sqlalchemy.orm import selectinload

from config import db
from security import token_optional
from upload import get_public_url
from backend.tachlis.modals.tachlis_post import TachlisPost
from backend.estates.modals.estates import EstatesListing
from backend.business.modals.business import Business
from backend.business.modals.business_post import BusinessPost
from backend.torah.modals.torah import TorahPost

feed_api = Blueprint('feed_api', __name__, url_prefix='/feed')

PAGE_SIZE = 20
SOURCE_CANDIDATE_CAP = 300
ALL_SOURCES = ('tachlis', 'estates_listing', 'business_new', 'business_deal', 'torah_post')

TACHLIS_TYPE_LABEL = {'job': 'Job', 'resume': 'Resume', 'service': 'Service'}
LISTING_TYPE_LABEL = {'sale': 'For Sale', 'long_term_lease': 'For Rent', 'short_term_lease': 'Short-Term Rental'}


def _fetch_tachlis(q, cap):
    now = datetime.utcnow()
    query = (TachlisPost.query
             .filter(TachlisPost.approved_to_publish.is_(True))
             .filter(db.or_(TachlisPost.expires_at.is_(None), TachlisPost.expires_at > now)))
    if q:
        like = f'%{q}%'
        query = query.filter(db.or_(
            TachlisPost.title.ilike(like), TachlisPost.body.ilike(like),
            TachlisPost.location.ilike(like), TachlisPost.compensation.ilike(like)))
    rows = query.order_by(TachlisPost.pub_date.desc()).limit(cap).all()

    items = []
    for p in rows:
        label = TACHLIS_TYPE_LABEL.get(p.post_type, 'Listing')
        bits = [label] + [b for b in (p.location, p.compensation) if b]
        items.append({
            'key': f'tachlis:{p.id}', 'source': 'tachlis', 'site_id': 'money',
            'url_path': f'/tachlis/post/{p.id}', 'title': p.title,
            'subtitle': ' · '.join(bits), 'image': None,
            'pub_date': p.pub_date.isoformat() if p.pub_date else None,
        })
    return items


def _fetch_estates_listings(q, cap):
    now = datetime.utcnow()
    query = (EstatesListing.query.options(selectinload(EstatesListing.photos))
             .filter(db.or_(EstatesListing.expires_at.is_(None), EstatesListing.expires_at > now)))
    if q:
        like = f'%{q}%'
        query = query.filter(db.or_(
            EstatesListing.title.ilike(like), EstatesListing.description.ilike(like),
            EstatesListing.city.ilike(like), EstatesListing.neighborhood.ilike(like),
            EstatesListing.address.ilike(like)))
    rows = query.order_by(EstatesListing.pub_date.desc()).limit(cap).all()

    items = []
    for l in rows:
        label = LISTING_TYPE_LABEL.get(l.listing_type, 'Listing')
        place = l.neighborhood or l.city
        bits = [label] + ([place] if place else [])
        image = get_public_url(l.photos[0].filename) if l.photos else None
        items.append({
            'key': f'estates_listing:{l.id}', 'source': 'estates_listing', 'site_id': 'estates',
            'url_path': f'/listings/{l.slug}', 'title': l.title,
            'subtitle': ' · '.join(bits), 'image': image,
            'pub_date': l.pub_date.isoformat() if l.pub_date else None,
        })
    return items


def _fetch_business_new(q, cap):
    query = Business.query
    if q:
        like = f'%{q}%'
        query = query.filter(db.or_(Business.name.ilike(like), Business.about.ilike(like)))
    rows = query.order_by(Business.pub_date.desc()).limit(cap).all()

    items = []
    for b in rows:
        items.append({
            'key': f'business_new:{b.id}', 'source': 'business_new', 'site_id': 'business',
            'url_path': f'/business/{b.slug}', 'title': b.name,
            'subtitle': (b.category or '').replace('_', ' ').title(),
            'image': get_public_url(b.logo) if b.logo else None,
            'pub_date': b.pub_date.isoformat() if b.pub_date else None,
        })
    return items


def _fetch_business_deals(q, cap):
    now = datetime.utcnow()
    query = (BusinessPost.query.options(selectinload(BusinessPost.business))
             .filter(BusinessPost.approved_to_publish.is_(True))
             .filter(db.or_(BusinessPost.expires_at.is_(None), BusinessPost.expires_at > now)))
    if q:
        like = f'%{q}%'
        query = query.join(BusinessPost.business).filter(db.or_(
            BusinessPost.title.ilike(like), BusinessPost.body.ilike(like), Business.name.ilike(like)))
    rows = query.order_by(BusinessPost.pub_date.desc()).limit(cap).all()

    items = []
    for p in rows:
        biz_name = p.business.name if p.business else None
        label = (p.post_type or '').replace('_', ' ').title()
        bits = [b for b in (biz_name, label) if b]
        items.append({
            'key': f'business_deal:{p.id}', 'source': 'business_deal', 'site_id': 'business',
            'url_path': f'/business/{p.business.slug}' if p.business else '/deals',
            'title': p.title, 'subtitle': ' · '.join(bits),
            'image': get_public_url(p.image) if p.image else None,
            'pub_date': p.pub_date.isoformat() if p.pub_date else None,
        })
    return items


def _fetch_torah_posts(q, cap):
    query = TorahPost.query.options(selectinload(TorahPost.photos))
    if q:
        like = f'%{q}%'
        query = query.filter(db.or_(TorahPost.title.ilike(like), TorahPost.category.ilike(like)))
    rows = query.order_by(TorahPost.pub_date.desc()).limit(cap).all()

    items = []
    for p in rows:
        image = get_public_url(p.photos[0].filename) if p.photos else None
        items.append({
            'key': f'torah_post:{p.id}', 'source': 'torah_post', 'site_id': 'torah',
            'url_path': f'/posts/{p.slug}', 'title': p.title,
            'subtitle': (p.category or '').title(), 'image': image,
            'pub_date': p.pub_date.isoformat() if p.pub_date else None,
        })
    return items


SOURCE_FETCHERS = {
    'tachlis': _fetch_tachlis,
    'estates_listing': _fetch_estates_listings,
    'business_new': _fetch_business_new,
    'business_deal': _fetch_business_deals,
    'torah_post': _fetch_torah_posts,
}


def _round_robin_merge(per_source_items):
    """Interleaves each source's items evenly (newest-first *within* each
    source, same as before) instead of one global recency sort across all
    of them. A straight recency sort lets whichever source happens to have
    the most recently-dated rows crowd out everything else -- e.g.
    Community's businesses are bulk-imported with old pub_dates, so despite
    having 30,000+ rows they'd lose every slot to a source with only a
    handful of recently-touched rows. Round-robin guarantees every source
    with any inventory left gets a turn, in proportion to how many sources
    are still contributing, rather than in proportion to recency alone."""
    merged = []
    max_len = max((len(items) for items in per_source_items), default=0)
    for i in range(max_len):
        for items in per_source_items:
            if i < len(items):
                merged.append(items[i])
    return merged


@feed_api.route('/aggregate', methods=['GET'])
@token_optional
def aggregate(_current_user):
    requested = (request.args.get('sources') or '').strip()
    sources = [s for s in requested.split(',') if s] if requested else list(ALL_SOURCES)
    unknown = [s for s in sources if s not in SOURCE_FETCHERS]
    if unknown:
        return jsonify({'message': f'Unknown source(s): {", ".join(unknown)}. Valid: {", ".join(ALL_SOURCES)}'}), 400

    q = (request.args.get('q') or '').strip()
    try:
        page = max(1, int(request.args.get('page', 1)))
    except (TypeError, ValueError):
        page = 1

    # Each active source is asked for enough rows to cover every page up to
    # the one requested (already sorted + filtered in SQL), capped so a
    # very deep page number can't force an unbounded per-source query.
    cap = min(page * PAGE_SIZE, SOURCE_CANDIDATE_CAP)
    per_source_items = [SOURCE_FETCHERS[source](q, cap) for source in sources]
    merged = _round_robin_merge(per_source_items)

    start = (page - 1) * PAGE_SIZE
    page_slice = merged[start:start + PAGE_SIZE + 1]
    has_more = len(page_slice) > PAGE_SIZE
    items = page_slice[:PAGE_SIZE]

    return jsonify({'items': items, 'page': page, 'has_more': has_more})


TODAY_WINDOW_HOURS = 24
TODAY_CAP = 200


def _is_today(model):
    """The time a row actually went up in its source WhatsApp group when
    known, falling back to when it was added here -- same coalesce as each
    model's own "newest" sort (see estates.py/tachlis_post.py)."""
    cutoff = datetime.utcnow() - timedelta(hours=TODAY_WINDOW_HOURS)
    return db.func.coalesce(model.source_posted_at, model.pub_date) > cutoff


@feed_api.route('/today', methods=['GET'])
def today():
    """Powers "Today on GUT" -- every Estates listing and Tachlis job/resume
    posted in the last 24 hours, grouped by area (Estates) and category
    (Tachlis) client-side from this flat list. No auth, no pagination: this
    is meant to be one glance-able, shareable page, not a deep feed."""
    now = datetime.utcnow()

    estates_rows = (EstatesListing.query
                     .options(selectinload(EstatesListing.photos))
                     .filter(db.or_(EstatesListing.expires_at.is_(None), EstatesListing.expires_at > now))
                     .filter(_is_today(EstatesListing))
                     .order_by(db.func.coalesce(EstatesListing.source_posted_at, EstatesListing.pub_date).desc())
                     .limit(TODAY_CAP)
                     .all())
    estates_items = [{
        'id': l.id, 'slug': l.slug, 'title': l.title,
        'listing_type': l.listing_type,
        'area': l.neighborhood or l.city or l.country,
        'price': l.price, 'currency': l.currency, 'price_period': l.price_period,
        'cover_photo_url': get_public_url(l.photos[0].filename) if l.photos else None,
        'pub_date': (l.source_posted_at or l.pub_date).isoformat() if (l.source_posted_at or l.pub_date) else None,
    } for l in estates_rows]

    jobs_rows = (TachlisPost.query
                 .filter(TachlisPost.approved_to_publish.is_(True))
                 .filter(db.or_(TachlisPost.expires_at.is_(None), TachlisPost.expires_at > now))
                 .filter(_is_today(TachlisPost))
                 .order_by(db.func.coalesce(TachlisPost.source_posted_at, TachlisPost.pub_date).desc())
                 .limit(TODAY_CAP)
                 .all())
    jobs_items = [{
        'id': p.id, 'title': p.title, 'post_type': p.post_type,
        'category': p.category, 'location': p.location, 'compensation': p.compensation,
        'remote': p.remote,
        'pub_date': (p.source_posted_at or p.pub_date).isoformat() if (p.source_posted_at or p.pub_date) else None,
    } for p in jobs_rows]

    return jsonify({
        'generated_at': now.isoformat(),
        'window_hours': TODAY_WINDOW_HOURS,
        'estates': estates_items,
        'jobs': jobs_items,
    })
