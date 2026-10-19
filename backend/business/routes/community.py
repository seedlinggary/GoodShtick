"""'Find a Community' -- each Community is a point (usually a city, sometimes
a finer neighborhood) whose shuls/mikvahs/groceries/restaurants/attractions
are found by a radius query against the existing Business/BusinessLocation
data (same bbox math the Directory's "Near me" already uses), not a manually
maintained link list. That means every business already imported into the
directory is automatically part of whichever community it's near, including
the explicit "or nearby" case for things like restaurants."""
import math
import re
import unicodedata

from flask import Blueprint, jsonify, request
from sqlalchemy import func
from sqlalchemy.orm import selectinload

from config import db
from security import token_required, token_optional
from backend.business.modals.community import Community
from backend.business.modals.business import Business, BusinessLocation
from backend.business.schemas.community import CommunitySchema
from backend.business.schemas.business import make_business_schema

community_api = Blueprint('community_api', __name__, url_prefix='/business')

NAME_MAX, DESC_MAX = 150, 2000
ERUV_STATUS_MAX, ERUV_URL_MAX = 300, 500
DEFAULT_RADIUS_MILES = 15
MILES_PER_DEGREE_LAT = 69

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

    query = Community.query
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
    rows = db.session.query(Community.slug, Community.pub_date).all()
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
    if not community:
        return jsonify({'message': 'Community not found'}), 404

    data = CommunitySchema().dump(community)
    data['can_manage'] = _can_manage_community(community, current_user)
    if community.eruv_status or community.eruv_map_image:
        data['eruv_disclaimer'] = ERUV_DISCLAIMER

    if community.lat is None or community.lng is None:
        data['amenities'] = {key: [] for key in AMENITY_CATEGORIES}
        data['amenities_note'] = 'This community has no map location yet, so nearby businesses can’t be found automatically.'
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
            .filter(Business.category == category, Business.id.in_(loc_ids))
            .order_by(Business.name)
            .limit(30).all())
        amenities[key] = schema.dump(businesses)

    data['amenities'] = amenities
    data['radius_miles'] = DEFAULT_RADIUS_MILES
    return jsonify(data)


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
    )
    db.session.add(community)
    db.session.commit()
    return jsonify(CommunitySchema().dump(community)), 201


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
