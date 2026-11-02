"""'Find a Community' -- each Community is a point (usually a city, sometimes
a finer neighborhood) whose shuls/mikvahs/groceries/restaurants/attractions
are found by a radius query against the existing Business/BusinessLocation
data (same bbox math the Directory's "Near me" already uses), not a manually
maintained link list. That means every business already imported into the
directory is automatically part of whichever community it's near, including
the explicit "or nearby" case for things like restaurants."""
import json
import math
import os
import re
import unicodedata
from datetime import datetime, timedelta

from flask import Blueprint, jsonify, request
from sqlalchemy import func
from sqlalchemy.orm import selectinload

from config import db
from security import token_required, token_optional, admin_required
from backend.business.modals.community import Community, CommunityDataCache, CommunitySave
from backend.business.modals.business import Business, BusinessLocation
from backend.business.schemas.community import CommunitySchema
from backend.business.schemas.business import make_business_schema
from backend.estates.modals.estates import EstatesListing, LISTING_TYPES
from backend.estates.schemas.estates import EstatesListingCardSchema
from backend.tachlis.modals.tachlis_post import TachlisPost
from backend.tachlis.schemas.tachlis import make_tachlis_post_schema

community_api = Blueprint('community_api', __name__, url_prefix='/business')

NAME_MAX, DESC_MAX = 150, 2000
ERUV_STATUS_MAX, ERUV_URL_MAX = 300, 500
GUEST_EMAIL_MAX = 150
GUEST_PHONE_MAX = 40
# Amenities -- tightened to genuinely "nearby" (walking distance), per
# explicit user feedback that the original 15mi radius returned things
# too far away to call local.
DEFAULT_RADIUS_MILES = 0.5
MILES_PER_DEGREE_LAT = 69

# Sub-areas (curated neighborhoods within one Community) -- caps mirror the
# other free-text limits above; kept small since this is a hand-curated
# list, not an open-ended one.
SUB_AREAS_MAX = 40
SUB_AREA_NAME_MAX = 80
SUB_AREA_MATCH_MAX = 20
SUB_AREA_MATCH_STR_MAX = 120

# Housing price-by-size breakdown -- only shown when there's enough of a
# currency's listings to bucket meaningfully (MIN_FOR_BREAKDOWN), and only
# for a bedroom-count bucket with enough listings of its own (MIN_BUCKET)
# to avoid a single oddball listing posing as "the median 5-bedroom price".
MIN_FOR_BREAKDOWN = 10
MIN_BUCKET = 3
MAX_BEDROOM_BUCKET = 5  # collapses 5+ bedrooms into one bucket

# Housing (Estates) comparables -- wider than the 0.5mi amenities radius
# (confirmed live: a Community's own point can sit in a spot with ZERO
# geocoded listings within 0.5mi -- e.g. Beit Shemesh -- while 1.5mi
# reliably returns real nearby listings), but still a genuinely local
# market, not a regional one.
HOUSING_RADIUS_MILES = 1.5

# Jobs (Tachlis) radius -- wider than housing, per explicit user feedback,
# but no longer meant to approximate a long commute. There's no real
# driving-directions API anywhere in this codebase, so this stays a
# straight-line figure, surfaced to the client via radius_miles on the
# response so it's never presented as more precise than it is.
JOB_RADIUS_MILES = 8

# What counts as each required community amenity, for the detail page's
# "does this community have X yet" summary. Schools/organizations reuse
# categories (education/nonprofit) that already had real data from earlier
# imports -- no new sourcing needed to wire these in.
AMENITY_CATEGORIES = {
    'shuls': 'shul',
    'mikvahs': 'mikvah',
    'groceries': 'grocery',
    'restaurants': 'restaurant',
    'attractions': 'attraction',
    'schools': 'education',
    'organizations': 'nonprofit',
}

# Eruv status changes week to week (a downed pole, a construction detour)
# and we have no way to keep a stored status current, so every response
# that includes one carries this same reminder rather than storing it
# per-row.
ERUV_DISCLAIMER = ('Eruv status can change week to week. Always check the community’s own '
                    'eruv map or hotline before relying on it, especially before Shabbos.')


def _slugify(name):
    normalized = unicodedata.normalize('NFKD', name).encode('ascii', 'ignore').decode('ascii')
    slug = re.sub(r'[^a-z0-9]+', '-', normalized.lower()).strip('-')
    return slug or 'community'


def _unique_slug(name):
    base = _slugify(name)
    slug = base
    i = 2
    while db.session.query(Community.id).filter_by(slug=slug).first():
        slug = f'{base}-{i}'
        i += 1
    return slug


def _bbox_from_point(lat, lng, miles):
    lat_delta = miles / MILES_PER_DEGREE_LAT
    lng_delta = miles / (MILES_PER_DEGREE_LAT * math.cos(math.radians(lat))) if lat else miles / MILES_PER_DEGREE_LAT
    return lat - lat_delta, lat + lat_delta, lng - lng_delta, lng + lng_delta


def _can_manage_community(community, user):
    if not user:
        return False
    if user.is_boss:
        return True
    return community.created_by == user.public_id


def _validate_sub_areas(raw):
    """Returns (error_message_or_None, cleaned_list). `raw` must be a list
    of {"name": str, "match": [str, ...]} dicts -- `match` is a list (not a
    single string) so one sub-area can absorb known spelling/format
    variants of its neighborhood name later without a schema change."""
    if not isinstance(raw, list):
        return 'sub_areas must be a list', None
    if len(raw) > SUB_AREAS_MAX:
        return f'sub_areas must be {SUB_AREAS_MAX} or fewer', None

    cleaned = []
    for entry in raw:
        if not isinstance(entry, dict):
            return 'Each sub_area must be an object', None
        name = (entry.get('name') or '').strip()
        if not name:
            return 'Each sub_area needs a name', None
        if len(name) > SUB_AREA_NAME_MAX:
            return f'sub_area name must be {SUB_AREA_NAME_MAX} characters or fewer', None

        match = entry.get('match')
        if not isinstance(match, list) or not match:
            return f'sub_area "{name}" needs at least one match string', None
        if len(match) > SUB_AREA_MATCH_MAX:
            return f'sub_area "{name}" has too many match strings', None
        cleaned_match = []
        for m in match:
            m = (m or '').strip() if isinstance(m, str) else ''
            if not m:
                continue
            if len(m) > SUB_AREA_MATCH_STR_MAX:
                return f'A match string for sub_area "{name}" is too long', None
            cleaned_match.append(m)
        if not cleaned_match:
            return f'sub_area "{name}" needs at least one non-empty match string', None

        cleaned.append({'name': name, 'match': cleaned_match})

    return None, cleaned


@community_api.route('/communities', methods=['GET'])
def list_communities():
    """Public browse/search -- by name, city, or state. No auth needed, same
    as the business directory's own public listing. ?sort=random gives the
    same 'shake the board' as the rest of the site; ?sort=distance (with
    lat/lng) sorts by proximity the same way the Directory's "Near me" does
    -- Community already has lat/lng directly on the row (no nested
    locations to join through), so this just sorts in Python rather than
    needing the Directory's candidate-window dance."""
    q = (request.args.get('q') or '').strip()
    state = (request.args.get('state') or '').strip()
    sort = (request.args.get('sort') or '').strip().lower()
    try:
        page = max(1, int(request.args.get('page', 1)))
    except (TypeError, ValueError):
        page = 1
    per_page = 50

    near_lat = near_lng = None
    if sort == 'distance':
        try:
            near_lat, near_lng = float(request.args.get('lat')), float(request.args.get('lng'))
        except (TypeError, ValueError):
            return jsonify({'message': 'sort=distance requires numeric lat and lng'}), 400

    query = Community.query.filter(Community.approved_to_publish.is_(True))
    if q:
        like = f'%{q}%'
        query = query.filter(db.or_(Community.name.ilike(like), Community.city.ilike(like)))
    if state:
        query = query.filter(Community.state.ilike(state))

    total = query.count()

    if sort == 'distance':
        candidates = [c for c in query.all() if c.lat is not None and c.lng is not None]
        candidates.sort(key=lambda c: (c.lat - near_lat) ** 2 + (c.lng - near_lng) ** 2)
        total = len(candidates)
        rows = candidates[(page - 1) * per_page: page * per_page]
    elif sort == 'random':
        rows = query.order_by(func.random()).offset((page - 1) * per_page).limit(per_page).all()
    else:
        rows = query.order_by(Community.name).offset((page - 1) * per_page).limit(per_page).all()

    return jsonify({
        'results': CommunitySchema(many=True).dump(rows),
        'total': total, 'page': page, 'per_page': per_page,
        'has_more': page * per_page < total,
    })


@community_api.route('/communities/states', methods=['GET'])
def list_community_states():
    """Distinct states with at least one community, for a filter dropdown."""
    rows = (db.session.query(Community.state)
            .filter(Community.state.isnot(None), Community.state != '')
            .distinct().order_by(Community.state).all())
    return jsonify({'states': [s for (s,) in rows]})


@community_api.route('/communities/sitemap-data', methods=['GET'])
def community_sitemap_data():
    """Minimal {slug, updated} rows for every community -- see
    business.py's sitemap_data() for why this stays a lean, joinless query."""
    rows = (db.session.query(Community.slug, Community.pub_date)
            .filter(Community.approved_to_publish.is_(True)).all())
    return jsonify({
        'communities': [
            {'slug': slug, 'updated': pub_date.isoformat() if pub_date else None}
            for slug, pub_date in rows
        ],
    })


@community_api.route('/communities/<slug>', methods=['GET'])
@token_optional
def get_community(current_user, slug):
    community = Community.query.filter_by(slug=slug).first()
    if not community or (community.approved_to_publish is not True and not _can_manage_community(community, current_user)):
        return jsonify({'message': 'Community not found'}), 404

    data = CommunitySchema().dump(community)
    data['can_manage'] = _can_manage_community(community, current_user)
    data['is_saved'] = bool(current_user and CommunitySave.query.filter_by(
        user_id=current_user.public_id, community_id=community.id).first())
    if community.eruv_status or community.eruv_map_image:
        data['eruv_disclaimer'] = ERUV_DISCLAIMER

    # Sub-area narrowing (?area=<name>) -- a curated list the community's
    # own manager defines (see Community.sub_areas), not auto-derived from
    # EstatesListing.neighborhood's messy free text. Only narrows Housing
    # below: BusinessLocation/TachlisPost have no neighborhood field to
    # match against, so Amenities/Jobs always stay community-wide --
    # `selected_area` tells the frontend whether narrowing actually
    # happened, so it can show why those two sections didn't change.
    data['sub_areas'] = community.sub_areas or []
    requested_area = (request.args.get('area') or '').strip()
    selected_sub_area = next(
        (a for a in (community.sub_areas or []) if a['name'] == requested_area), None,
    ) if requested_area else None
    data['selected_area'] = selected_sub_area['name'] if selected_sub_area else None

    if community.lat is None or community.lng is None:
        data['amenities'] = {key: [] for key in AMENITY_CATEGORIES}
        data['amenities_note'] = 'This community has no map location yet, so nearby businesses can’t be found automatically.'
        data['housing'] = {ltype: {'count': 0, 'by_currency': [], 'listings': []} for ltype in LISTING_TYPES}
        data['jobs'] = {'count': 0, 'radius_miles': JOB_RADIUS_MILES, 'posts': []}
        return jsonify(data)

    south, north, west, east = _bbox_from_point(community.lat, community.lng, DEFAULT_RADIUS_MILES)
    schema = make_business_schema(current_user, many=True, card=True)

    amenities = {}
    for key, category in AMENITY_CATEGORIES.items():
        # Subquery of matching business_ids rather than a join+distinct --
        # Business.attributes is a JSON column, and Postgres has no equality
        # operator for json, so DISTINCT on a joined query raises.
        loc_ids = db.session.query(BusinessLocation.business_id).filter(
            BusinessLocation.lat.isnot(None), BusinessLocation.lng.isnot(None),
            BusinessLocation.lat.between(south, north),
            BusinessLocation.lng.between(west, east))
        businesses = (Business.query
            .options(selectinload(Business.locations), selectinload(Business.claims))
            .filter(Business.category == category, Business.id.in_(loc_ids),
                    Business.approved_to_publish.is_(True))
            .order_by(Business.name)
            .limit(30).all())
        amenities[key] = schema.dump(businesses)

    data['amenities'] = amenities
    data['radius_miles'] = DEFAULT_RADIUS_MILES

    # Housing -- real EstatesListing comparables within HOUSING_RADIUS_MILES,
    # same "active" filter and median-price approach area_page() already
    # uses (backend/estates/routes/estates.py), just scoped to this
    # community's own bbox instead of an exact city/neighborhood match.
    #
    # Median is computed PER CURRENCY, not blended across all of them --
    # confirmed live that a single bbox can genuinely mix USD and ILS
    # listings (e.g. short-term rentals near Beit Shemesh: 47 ILS + 10 USD),
    # and averaging raw price numbers across two different currencies with
    # no conversion applied would be a meaningless, actively misleading
    # figure, not just a cosmetic $-vs-₪ label mixup.
    now = datetime.utcnow()
    hsouth, hnorth, hwest, heast = _bbox_from_point(community.lat, community.lng, HOUSING_RADIUS_MILES)
    housing = {}
    for ltype in LISTING_TYPES:
        if selected_sub_area:
            # Deliberately NOT bounded by the community's own (now tight,
            # 1.5mi) bbox -- confirmed live that a real, hand-curated
            # sub-area like Jerusalem's Gilo or Malha sits well outside
            # 1.5mi of whatever single point Jerusalem's own Community row
            # happens to use, and ANDing the tight bbox back in silently
            # zeroed out real matches. A sub-area's `match` list is curated
            # by a trusted community manager (not arbitrary free-text
            # search), so the neighborhood match alone is the right filter.
            bbox_filter = db.and_(
                EstatesListing.listing_type == ltype,
                EstatesListing.approved_to_publish.is_(True),
                db.or_(EstatesListing.expires_at.is_(None), EstatesListing.expires_at > now),
                db.or_(*[EstatesListing.neighborhood.ilike(f'%{m}%') for m in selected_sub_area['match']]),
            )
        else:
            bbox_filter = db.and_(
                EstatesListing.listing_type == ltype,
                EstatesListing.approved_to_publish.is_(True),
                db.or_(EstatesListing.expires_at.is_(None), EstatesListing.expires_at > now),
                EstatesListing.lat.isnot(None), EstatesListing.lng.isnot(None),
                EstatesListing.lat.between(hsouth, hnorth), EstatesListing.lng.between(hwest, heast),
            )
        rows = (EstatesListing.query.filter(bbox_filter)
                .order_by(func.coalesce(EstatesListing.source_posted_at, EstatesListing.pub_date).desc())
                .limit(20).all())
        by_currency_rows = (db.session.query(
            EstatesListing.currency,
            func.count(EstatesListing.id),
            func.percentile_cont(0.5).within_group(EstatesListing.price.asc()))
            .filter(bbox_filter, EstatesListing.price.isnot(None))
            .group_by(EstatesListing.currency)
            .all())
        by_currency = []
        for cur, n, med in by_currency_rows:
            entry = {'currency': cur, 'count': n, 'median_price': round(med, 2) if med is not None else None}
            # Price-by-size: bedroom-count buckets, only once there's enough
            # of this currency to bucket meaningfully (MIN_FOR_BREAKDOWN),
            # and only for a bucket with enough listings of its own
            # (MIN_BUCKET) -- confirmed live that bedroom count has far
            # better real-data coverage (~91%) than size_value (~64%) for
            # sale listings, so bedrooms is the breakdown dimension, not sqft.
            if n >= MIN_FOR_BREAKDOWN:
                bucket_col = func.least(func.floor(EstatesListing.bedrooms), MAX_BEDROOM_BUCKET)
                bucket_rows = (db.session.query(
                    bucket_col.label('bucket'),
                    func.count(EstatesListing.id),
                    func.percentile_cont(0.5).within_group(EstatesListing.price.asc()))
                    .filter(bbox_filter, EstatesListing.currency == cur, EstatesListing.price.isnot(None),
                            EstatesListing.bedrooms.isnot(None))
                    .group_by('bucket')
                    .having(func.count(EstatesListing.id) >= MIN_BUCKET)
                    .order_by('bucket')
                    .all())
                entry['by_bedrooms'] = [
                    {
                        'bedrooms': int(bucket), 'is_max_bucket': bucket >= MAX_BEDROOM_BUCKET,
                        'count': bn, 'median_price': round(bmed, 2) if bmed is not None else None,
                    }
                    for bucket, bn, bmed in bucket_rows
                ]
            else:
                entry['by_bedrooms'] = []
            by_currency.append(entry)
        housing[ltype] = {
            'count': len(rows),
            'by_currency': by_currency,
            'listings': EstatesListingCardSchema(many=True).dump(rows),
        }
    data['housing'] = housing

    # Jobs -- real TachlisPost job openings within JOB_RADIUS_MILES (wider
    # than housing, straight-line only -- see JOB_RADIUS_MILES's own
    # comment). Same public-visibility filter as /tachlis/posts' list_posts:
    # approved_to_publish is True and
    # not expired (a manually 'filled' post is already force-expired by
    # set_post_status, so that one expiry check also excludes it).
    jsouth, jnorth, jwest, jeast = _bbox_from_point(community.lat, community.lng, JOB_RADIUS_MILES)
    job_filter = db.and_(
        TachlisPost.post_type == 'job',
        TachlisPost.approved_to_publish.is_(True),
        db.or_(TachlisPost.expires_at.is_(None), TachlisPost.expires_at > now),
        TachlisPost.lat.isnot(None), TachlisPost.lng.isnot(None),
        TachlisPost.lat.between(jsouth, jnorth), TachlisPost.lng.between(jwest, jeast),
    )
    job_rows = (TachlisPost.query.filter(job_filter)
                .order_by(func.coalesce(TachlisPost.source_posted_at, TachlisPost.pub_date).desc())
                .limit(20).all())
    data['jobs'] = {
        'count': len(job_rows),
        'radius_miles': JOB_RADIUS_MILES,
        'posts': make_tachlis_post_schema(current_user, many=True, card=True).dump(job_rows),
    }

    return jsonify(data)


def _cached(cache_key, ttl, fetch_fn):
    """Returns (payload, from_cache_bool, error_or_None). Identical logic to
    backend/finance/routes/finance_market.py's own _cached(), just backed by
    CommunityDataCache instead of FinanceDataCache -- serves a stale cache
    entry rather than a hard error if fetch_fn itself fails, since a stale
    cost-of-living estimate is still far more useful to show than nothing."""
    row = CommunityDataCache.query.filter_by(cache_key=cache_key).first()
    if row and datetime.utcnow() - row.fetched_at < ttl:
        return row.payload, True, None

    try:
        payload = fetch_fn()
    except Exception as e:
        if row:
            return row.payload, True, None
        return None, False, str(e)

    if row:
        row.payload = payload
        row.fetched_at = datetime.utcnow()
    else:
        row = CommunityDataCache(cache_key=cache_key, payload=payload)
        db.session.add(row)
    db.session.commit()
    return payload, False, None


@community_api.route('/communities/<slug>/cost-of-living', methods=['GET'])
def get_cost_of_living(slug):
    """GPT-estimated, cached cost-of-living context -- never presented as
    precise local data (see the prompt's own confidence_note instruction),
    just a useful general-purpose estimate that's expensive/slow enough to
    ask for that it's cached for 30 days via _cached() above rather than
    asked fresh on every page view."""
    community = Community.query.filter_by(slug=slug).first()
    if not community:
        return jsonify({'message': 'Community not found'}), 404
    if not os.environ.get('OPENAI_API_KEY'):
        return jsonify({'message': 'Cost-of-living estimates are not configured'}), 503

    def fetch():
        from openai import OpenAI
        client = OpenAI()
        location_desc = ', '.join(filter(None, [community.name, community.city, community.state, community.country]))
        response = client.chat.completions.create(
            model='gpt-4o-mini',
            response_format={'type': 'json_object'},
            temperature=0.3,
            messages=[
                {'role': 'system', 'content': (
                    "You estimate general cost-of-living context for Orthodox Jewish families considering a "
                    "community. Respond ONLY with a JSON object with exactly these string keys: "
                    "cost_of_living_index (e.g. 'about 15% above the US national average, driven mainly by housing'), "
                    "groceries, utilities, transportation, day_school_tuition (typical yeshiva/day school tuition "
                    "range for this area if you have a reasonable estimate), kosher_grocery_premium "
                    "(how much more kosher groceries typically cost here vs a non-kosher baseline), and "
                    "confidence_note (be explicit if you are not confident about specifics for this exact area "
                    "and are giving a regional/general estimate instead -- never present a guess as precise local data)."
                )},
                {'role': 'user', 'content': f'Community: {location_desc}'},
            ],
        )
        return json.loads(response.choices[0].message.content)

    payload, cached, error = _cached(f'col:{slug}', timedelta(days=30), fetch)
    if error:
        return jsonify({'message': error}), 502
    return jsonify({'col': payload, 'cached': cached})


@community_api.route('/communities/<slug>/save', methods=['POST'])
@token_required
def save_community(current_user, slug):
    community = Community.query.filter_by(slug=slug).first()
    if not community:
        return jsonify({'message': 'Community not found'}), 404
    existing = CommunitySave.query.filter_by(user_id=current_user.public_id, community_id=community.id).first()
    if not existing:
        db.session.add(CommunitySave(user_id=current_user.public_id, community_id=community.id))
        db.session.commit()
    return jsonify({'saved': True})


@community_api.route('/communities/<slug>/save', methods=['DELETE'])
@token_required
def unsave_community(current_user, slug):
    community = Community.query.filter_by(slug=slug).first()
    if not community:
        return jsonify({'message': 'Community not found'}), 404
    CommunitySave.query.filter_by(user_id=current_user.public_id, community_id=community.id).delete()
    db.session.commit()
    return jsonify({'saved': False})


@community_api.route('/communities/saved', methods=['GET'])
@token_required
def list_saved_communities(current_user):
    rows = (Community.query.join(CommunitySave, CommunitySave.community_id == Community.id)
            .filter(CommunitySave.user_id == current_user.public_id)
            .order_by(CommunitySave.created_at.desc()).all())
    return jsonify({'results': CommunitySchema(many=True).dump(rows)})


@community_api.route('/communities', methods=['POST'])
@token_required
def create_community(current_user):
    """Goes live immediately, same philosophy as a business listing -- any
    logged-in resident can add their own community rather than waiting on
    an admin, since 'able to be added manually' was an explicit requirement."""
    body = request.get_json() or {}
    name = (body.get('name') or '').strip()
    city = (body.get('city') or '').strip()
    if not name:
        return jsonify({'message': 'Name is required'}), 400
    if len(name) > NAME_MAX:
        return jsonify({'message': f'Name must be {NAME_MAX} characters or fewer'}), 400
    if not city:
        return jsonify({'message': 'City is required'}), 400
    description = (body.get('description') or '').strip()
    if len(description) > DESC_MAX:
        return jsonify({'message': f'Description must be {DESC_MAX} characters or fewer'}), 400

    lat, lng = body.get('lat'), body.get('lng')
    try:
        lat = float(lat) if lat not in (None, '') else None
        lng = float(lng) if lng not in (None, '') else None
    except (TypeError, ValueError):
        return jsonify({'message': 'lat/lng must be numbers'}), 400

    eruv_status = (body.get('eruv_status') or '').strip()
    if len(eruv_status) > ERUV_STATUS_MAX:
        return jsonify({'message': f'Eruv status must be {ERUV_STATUS_MAX} characters or fewer'}), 400
    eruv_url = (body.get('eruv_url') or '').strip()
    if len(eruv_url) > ERUV_URL_MAX:
        return jsonify({'message': f'Eruv URL must be {ERUV_URL_MAX} characters or fewer'}), 400

    sub_areas = None
    if 'sub_areas' in body:
        error, sub_areas = _validate_sub_areas(body.get('sub_areas') or [])
        if error:
            return jsonify({'message': error}), 400

    community = Community(
        slug=_unique_slug(name), name=name, city=city,
        description=description or None,
        state=(body.get('state') or '').strip() or None,
        country=(body.get('country') or '').strip() or None,
        lat=lat, lng=lng,
        eruv_status=eruv_status or None, eruv_url=eruv_url or None,
        eruv_map_image=(body.get('eruv_map_image') or '').strip() or None,
        created_by=current_user.public_id,
        imported=False,
        approved_to_publish=True,
    )
    if sub_areas is not None:
        community.sub_areas = sub_areas
    db.session.add(community)
    db.session.commit()
    return jsonify(CommunitySchema().dump(community)), 201


@community_api.route('/communities/guest', methods=['POST'])
def create_guest_community():
    """Same validation as create_community, minus the login requirement --
    goes into the pending queue instead of live immediately (see
    Community.approved_to_publish)."""
    body = request.get_json() or {}
    name = (body.get('name') or '').strip()
    city = (body.get('city') or '').strip()
    if not name:
        return jsonify({'message': 'Name is required'}), 400
    if len(name) > NAME_MAX:
        return jsonify({'message': f'Name must be {NAME_MAX} characters or fewer'}), 400
    if not city:
        return jsonify({'message': 'City is required'}), 400
    description = (body.get('description') or '').strip()
    if len(description) > DESC_MAX:
        return jsonify({'message': f'Description must be {DESC_MAX} characters or fewer'}), 400

    lat, lng = body.get('lat'), body.get('lng')
    try:
        lat = float(lat) if lat not in (None, '') else None
        lng = float(lng) if lng not in (None, '') else None
    except (TypeError, ValueError):
        return jsonify({'message': 'lat/lng must be numbers'}), 400

    guest_email = (body.get('guest_email') or '').strip()[:GUEST_EMAIL_MAX]
    guest_phone = (body.get('guest_phone') or '').strip()[:GUEST_PHONE_MAX]
    if not (guest_email or guest_phone):
        return jsonify({'message': 'At least one of guest_email or guest_phone is required'}), 400

    from backend.guest.modals.guest_throttle import check_and_record_guest_submission
    if not check_and_record_guest_submission(request):
        return jsonify({'message': 'Too many submissions from this network today -- please try again tomorrow.'}), 429

    import secrets
    community = Community(
        slug=_unique_slug(name), name=name, city=city,
        description=description or None,
        state=(body.get('state') or '').strip() or None,
        country=(body.get('country') or '').strip() or None,
        lat=lat, lng=lng,
        created_by=None,
        imported=False,
        approved_to_publish=None,
        guest_email=guest_email or None,
        guest_phone=guest_phone or None,
        guest_manage_token=secrets.token_urlsafe(32),
    )
    db.session.add(community)
    db.session.commit()

    if guest_email:
        try:
            from backend.alerts import emails
            from backend.alerts.routes.alert import MAIN_SITE_URL
            emails.send_guest_submission_email(
                guest_email, 'your community', community.name,
                f'{MAIN_SITE_URL}/guest/community/{community.guest_manage_token}',
            )
        except Exception:
            pass  # an email failure should never break the actual submission

    data = CommunitySchema().dump(community)
    data['guest_manage_token'] = community.guest_manage_token
    return jsonify(data), 201


@community_api.route('/communities/guest/<token>', methods=['GET'])
def get_guest_community(token):
    community = Community.query.filter_by(guest_manage_token=token).first()
    if not community:
        return jsonify({'message': 'Community not found'}), 404
    return jsonify(CommunitySchema().dump(community))


@community_api.route('/communities/guest/<token>', methods=['PATCH'])
def edit_guest_community(token):
    community = Community.query.filter_by(guest_manage_token=token).first()
    if not community:
        return jsonify({'message': 'Community not found'}), 404

    body = request.get_json() or {}
    if 'name' in body:
        name = (body.get('name') or '').strip()
        if not name or len(name) > NAME_MAX:
            return jsonify({'message': f'Name is required, {NAME_MAX} characters or fewer'}), 400
        community.name = name
    if 'description' in body:
        description = (body.get('description') or '').strip()
        if len(description) > DESC_MAX:
            return jsonify({'message': f'Description must be {DESC_MAX} characters or fewer'}), 400
        community.description = description or None
    for field in ('city', 'state', 'country'):
        if field in body:
            setattr(community, field, (body.get(field) or '').strip() or None)
    if 'lat' in body or 'lng' in body:
        try:
            community.lat = float(body['lat']) if body.get('lat') not in (None, '') else None
            community.lng = float(body['lng']) if body.get('lng') not in (None, '') else None
        except (TypeError, ValueError):
            return jsonify({'message': 'lat/lng must be numbers'}), 400

    db.session.commit()
    return jsonify(CommunitySchema().dump(community))


@community_api.route('/communities/guest/<token>', methods=['DELETE'])
def delete_guest_community(token):
    community = Community.query.filter_by(guest_manage_token=token).first()
    if not community:
        return jsonify({'message': 'Community not found'}), 404
    db.session.delete(community)
    db.session.commit()
    return jsonify({'message': 'Community deleted'})


@community_api.route('/admin/communities/pending', methods=['GET'])
@admin_required
def get_pending_communities(_current_user):
    pending = Community.query.filter_by(approved_to_publish=None).order_by(Community.pub_date.asc()).all()
    return jsonify(CommunitySchema(many=True).dump(pending))


@community_api.route('/admin/communities/<int:community_id>/approve', methods=['POST'])
@admin_required
def approve_community(_current_user, community_id):
    community = db.session.get(Community, community_id)
    if not community:
        return jsonify({'message': 'Community not found'}), 404
    body = request.get_json(silent=True) or {}
    approved = not body.get('reject', False)
    community.approved_to_publish = approved
    db.session.commit()
    return jsonify({'message': 'approved' if approved else 'rejected'})


@community_api.route('/communities/<int:community_id>', methods=['PATCH'])
@token_required
def edit_community(current_user, community_id):
    community = db.session.get(Community, community_id)
    if not community:
        return jsonify({'message': 'Community not found'}), 404
    if not _can_manage_community(community, current_user):
        return jsonify({'message': 'Not authorized'}), 403

    body = request.get_json() or {}
    if 'name' in body:
        name = (body.get('name') or '').strip()
        if not name or len(name) > NAME_MAX:
            return jsonify({'message': f'Name is required, {NAME_MAX} characters or fewer'}), 400
        community.name = name
    if 'description' in body:
        description = (body.get('description') or '').strip()
        if len(description) > DESC_MAX:
            return jsonify({'message': f'Description must be {DESC_MAX} characters or fewer'}), 400
        community.description = description or None
    for field in ('city', 'state', 'country'):
        if field in body:
            setattr(community, field, (body.get(field) or '').strip() or None)
    if 'lat' in body or 'lng' in body:
        try:
            community.lat = float(body['lat']) if body.get('lat') not in (None, '') else None
            community.lng = float(body['lng']) if body.get('lng') not in (None, '') else None
        except (TypeError, ValueError):
            return jsonify({'message': 'lat/lng must be numbers'}), 400
    if 'eruv_status' in body:
        eruv_status = (body.get('eruv_status') or '').strip()
        if len(eruv_status) > ERUV_STATUS_MAX:
            return jsonify({'message': f'Eruv status must be {ERUV_STATUS_MAX} characters or fewer'}), 400
        community.eruv_status = eruv_status or None
    if 'eruv_url' in body:
        eruv_url = (body.get('eruv_url') or '').strip()
        if len(eruv_url) > ERUV_URL_MAX:
            return jsonify({'message': f'Eruv URL must be {ERUV_URL_MAX} characters or fewer'}), 400
        community.eruv_url = eruv_url or None
    if 'eruv_map_image' in body:
        community.eruv_map_image = (body.get('eruv_map_image') or '').strip() or None
    if 'sub_areas' in body:
        error, sub_areas = _validate_sub_areas(body.get('sub_areas') or [])
        if error:
            return jsonify({'message': error}), 400
        community.sub_areas = sub_areas or None

    db.session.commit()
    return jsonify(CommunitySchema().dump(community))


@community_api.route('/communities/<int:community_id>', methods=['DELETE'])
@token_required
def delete_community(current_user, community_id):
    community = db.session.get(Community, community_id)
    if not community:
        return jsonify({'message': 'Community not found'}), 404
    if not _can_manage_community(community, current_user):
        return jsonify({'message': 'Not authorized'}), 403
    db.session.delete(community)
    db.session.commit()
    return jsonify({'message': 'Community deleted'})
