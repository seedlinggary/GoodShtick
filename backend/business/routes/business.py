import os
import secrets
from datetime import datetime

from flask import Blueprint, jsonify, request
from sqlalchemy import func
from sqlalchemy.orm import selectinload

from config import db
from security import token_required, token_optional, admin_required
from upload import upload_file
from backend.business.modals.business import (
    Business, BusinessLocation, BUSINESS_CATEGORIES, FOOD_CATEGORIES, LOCATION_TYPES, slugify,
)
from backend.business.modals.business_claim import BusinessClaim
from backend.business.modals.business_site import BusinessSite
from backend.business.modals.business_post import BusinessPost
from backend.business.modals.business_comment import BusinessComment
from backend.business.schemas.business import make_business_schema, make_comment_schema, ClaimSchema
from backend.business.schemas.business_post import make_business_post_schema
from backend.business.social.holidays import auto_closure_reason
from backend.business.routes.social import maybe_publish_due_posts
from backend.business.routes.booking import maybe_generate_recurring_appointments
from backend.business.routes.promo_sync import maybe_generate_promo_posts

RECENT_POSTS_LIMIT = 5
RECENT_COMMENTS_LIMIT = 10

business_api = Blueprint('business_api', __name__, url_prefix='/business')

PAGE_SIZE = 40
CANDIDATE_CAP = 500  # see list_businesses(): only used when a Python-side filter (kashrut/open_now) applies
NAME_MAX = 150
ABOUT_MAX = 4000
ADDRESS_MAX = 300
WEBSITE_MAX = 300
SOURCE_URL_MAX = 500
SOURCE_NAME_MAX = 150
WEEKDAYS = ('mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun')
GUEST_EMAIL_MAX = 150
GUEST_PHONE_MAX = 40

BUSINESS_SITE_URL = os.environ.get('BUSINESS_SITE_URL', 'https://www.goodshtickbusiness.com')


def _feed_options():
    return [selectinload(Business.locations), selectinload(Business.claims)]


def _can_manage(business, user):
    """Owner (once claimed) or admin can always manage. Before a business is
    claimed, whoever originally submitted it can still edit it -- that right
    lapses the moment a claim is approved, so control moves to the verified
    owner instead of staying with an anonymous submitter forever."""
    if not user:
        return False
    if user.is_boss:
        return True
    if business.owner_user_id:
        return business.owner_user_id == user.public_id
    return business.created_by == user.public_id


def _location_open_now(loc):
    """Best-effort: hours are stored without a timezone, so this compares
    against server (UTC) time. Good enough for a v1 'open now' badge/filter;
    a real per-location timezone can be added to `attributes` later."""
    if (loc.attributes or {}).get('auto_holiday_closure') and auto_closure_reason():
        return False
    if not loc.hours:
        return False
    weekday = WEEKDAYS[datetime.utcnow().weekday()]
    day = loc.hours.get(weekday) if isinstance(loc.hours, dict) else None
    if not day or day.get('closed'):
        return False
    open_t, close_t = day.get('open'), day.get('close')
    if not open_t or not close_t:
        return False
    cur = datetime.utcnow().strftime('%H:%M')
    return open_t <= cur <= close_t


def _unique_slug(name):
    base = slugify(name)
    slug = base
    n = 2
    while Business.query.filter_by(slug=slug).first():
        slug = f'{base}-{n}'
        n += 1
    return slug


def _validate_location(body):
    """Returns (error_response_or_None, cleaned_fields)."""
    loc = {}
    location_type = (body.get('location_type') or 'physical').strip().lower()
    if location_type not in LOCATION_TYPES:
        return jsonify({'message': f'location_type must be one of: {", ".join(LOCATION_TYPES)}'}), None
    loc['location_type'] = location_type

    for key in ('address', 'city', 'state', 'zip_code', 'country', 'phone', 'email', 'kashrut'):
        val = (body.get(key) or '').strip()
        if key == 'address' and len(val) > ADDRESS_MAX:
            return jsonify({'message': f'Address must be {ADDRESS_MAX} characters or fewer'}), None
        loc[key] = val or None

    for key in ('lat', 'lng'):
        val = body.get(key)
        if val is None or val == '':
            loc[key] = None
        else:
            try:
                loc[key] = float(val)
            except (TypeError, ValueError):
                return jsonify({'message': f'{key} must be a number'}), None

    hours = body.get('hours')
    if hours is not None and not isinstance(hours, dict):
        return jsonify({'message': 'hours must be an object keyed by weekday'}), None
    loc['hours'] = hours

    attributes = body.get('attributes')
    if attributes is not None and not isinstance(attributes, dict):
        return jsonify({'message': 'attributes must be an object'}), None
    loc['attributes'] = attributes
    loc['is_primary'] = bool(body.get('is_primary'))
    return None, loc


@business_api.route('/categories', methods=['GET'])
def list_categories():
    return jsonify({'categories': list(BUSINESS_CATEGORIES), 'food_categories': list(FOOD_CATEGORIES)})


@business_api.route('/stats', methods=['GET'])
def business_stats():
    """Public, unauthenticated aggregate counts for the directory's own
    "trust bar" (see StatsBar.js) -- distinct cities/countries come from
    BusinessLocation since a single Business can have several locations.
    Cheap enough to run on every page load (a handful of COUNT/COUNT DISTINCT
    queries); revisit with caching if that ever stops being true.

    `categories`/`exclude_categories` (comma-separated) scope every count to
    just those businesses -- the Directory sends exclude_categories=shul,
    nonprofit so its trust bar doesn't count the Community area's listings,
    and the Community page sends categories=shul,nonprofit for its own."""
    categories = [c.strip().lower() for c in (request.args.get('categories') or '').split(',') if c.strip()]
    exclude_categories = [c.strip().lower() for c in (request.args.get('exclude_categories') or '').split(',') if c.strip()]

    def _scoped(query, business_id_col):
        query = query.filter(business_id_col.in_(
            db.session.query(Business.id).filter(Business.approved_to_publish.is_(True))))
        if categories:
            query = query.filter(business_id_col.in_(
                db.session.query(Business.id).filter(Business.category.in_(categories))))
        if exclude_categories:
            query = query.filter(business_id_col.in_(
                db.session.query(Business.id).filter(Business.category.notin_(exclude_categories))))
        return query

    business_query = db.session.query(Business.id).filter(Business.approved_to_publish.is_(True))
    if categories:
        business_query = business_query.filter(Business.category.in_(categories))
    if exclude_categories:
        business_query = business_query.filter(Business.category.notin_(exclude_categories))

    total_businesses = business_query.count()
    total_cities = _scoped(
        db.session.query(func.count(func.distinct(func.lower(BusinessLocation.city))))
        .filter(BusinessLocation.city.isnot(None), BusinessLocation.city != ''),
        BusinessLocation.business_id,
    ).scalar() or 0
    total_countries = _scoped(
        db.session.query(func.count(func.distinct(func.lower(BusinessLocation.country))))
        .filter(BusinessLocation.country.isnot(None), BusinessLocation.country != ''),
        BusinessLocation.business_id,
    ).scalar() or 0
    total_categories_query = db.session.query(func.count(func.distinct(Business.category))).filter(
        Business.approved_to_publish.is_(True))
    if categories:
        total_categories_query = total_categories_query.filter(Business.category.in_(categories))
    if exclude_categories:
        total_categories_query = total_categories_query.filter(Business.category.notin_(exclude_categories))
    total_categories = total_categories_query.scalar() or 0
    total_claimed = db.session.query(func.count(Business.id)).filter(
        Business.owner_user_id.isnot(None),
        Business.approved_to_publish.is_(True),
        *([Business.category.in_(categories)] if categories else []),
        *([Business.category.notin_(exclude_categories)] if exclude_categories else []),
    ).scalar() or 0
    total_kosher_locations = _scoped(
        db.session.query(func.count(BusinessLocation.id))
        .filter(BusinessLocation.kashrut.isnot(None), BusinessLocation.kashrut != ''),
        BusinessLocation.business_id,
    ).scalar() or 0
    total_deals = _scoped(
        db.session.query(func.count(BusinessPost.id)), BusinessPost.business_id,
    ).scalar() or 0

    return jsonify({
        'businesses': total_businesses,
        'cities': total_cities,
        'countries': total_countries,
        'categories': total_categories,
        'claimed': total_claimed,
        'kosher_locations': total_kosher_locations,
        'deals_posted': total_deals,
    })


@business_api.route('/sitemap-data', methods=['GET'])
def sitemap_data():
    """Minimal {slug, category, updated} rows for every business -- feeds the
    frontend's dynamically-generated sitemap.xml (see good-shtick/api/sitemap.js).
    Deliberately returns only these three columns (no joins, no locations)
    since a full business list payload would be wasteful for a job that just
    needs to print <url> entries; there's no separate updated_at column, so
    pub_date is the best lastmod proxy available."""
    rows = (db.session.query(Business.slug, Business.category, Business.pub_date)
            .filter(Business.approved_to_publish.is_(True)).all())
    return jsonify({
        'businesses': [
            {'slug': slug, 'category': category, 'updated': pub_date.isoformat() if pub_date else None}
            for slug, category, pub_date in rows
        ],
    })


@business_api.route('/businesses', methods=['GET'])
@token_optional
def list_businesses(current_user):
    """Public directory listing. Random order by default -- so newer/less
    popular businesses surface -- unless ?sort=alpha or ?sort=rating.
    Filters: category, city, q (name/about/city/address), food_only,
    kashrut_only, open_now, and a lat/lng bounding box for the map
    (north/south/east/west, all required together).

    `categories` (comma-separated) and `exclude_categories` (comma-separated)
    are the multi-category siblings of `category` -- used to carve out the
    Community area (shuls, chessed organizations) from the regular Business
    directory: the Directory always sends `exclude_categories=shul,nonprofit`
    so those never show there, and the Community page sends
    `categories=shul,nonprofit` to show only them. Both can combine with a
    single `category` chip within their own page (e.g. Community filtering
    down to just Shul)."""
    category = (request.args.get('category') or '').strip().lower()
    categories = [c.strip().lower() for c in (request.args.get('categories') or '').split(',') if c.strip()]
    exclude_categories = [c.strip().lower() for c in (request.args.get('exclude_categories') or '').split(',') if c.strip()]
    city = (request.args.get('city') or '').strip()
    location_type = (request.args.get('location_type') or '').strip().lower()
    q = (request.args.get('q') or '').strip()
    food_only = request.args.get('food_only') in ('1', 'true', 'True')
    kashrut_only = request.args.get('kashrut_only') in ('1', 'true', 'True')
    open_now = request.args.get('open_now') in ('1', 'true', 'True')
    sort = (request.args.get('sort') or 'random').strip().lower()
    try:
        page = max(1, int(request.args.get('page', 1)))
    except (TypeError, ValueError):
        page = 1

    near_lat = near_lng = None
    if sort == 'distance':
        try:
            near_lat, near_lng = float(request.args.get('lat')), float(request.args.get('lng'))
        except (TypeError, ValueError):
            return jsonify({'message': 'sort=distance requires numeric lat and lng'}), 400

    # Small chance per public listing request to fire any social post whose
    # scheduled time has arrived -- see social.py's maybe_publish_due_posts
    # for why this is opportunistic rather than a real cron job.
    maybe_publish_due_posts()
    # Same opportunistic-sweep pattern, for the site builder's recurring
    # bookings -- see booking.py's maybe_generate_recurring_appointments.
    maybe_generate_recurring_appointments()
    # Same pattern again, for the site builder's promo-sync bolt-on --
    # see promo_sync.py's maybe_generate_promo_posts.
    maybe_generate_promo_posts()

    query = Business.query.options(*_feed_options()).filter(Business.approved_to_publish.is_(True))

    if category:
        if category not in BUSINESS_CATEGORIES:
            return jsonify({'message': f'category must be one of: {", ".join(BUSINESS_CATEGORIES)}'}), 400
        query = query.filter(Business.category == category)

    if categories:
        invalid = [c for c in categories if c not in BUSINESS_CATEGORIES]
        if invalid:
            return jsonify({'message': f'categories must be one of: {", ".join(BUSINESS_CATEGORIES)}'}), 400
        query = query.filter(Business.category.in_(categories))

    if exclude_categories:
        invalid = [c for c in exclude_categories if c not in BUSINESS_CATEGORIES]
        if invalid:
            return jsonify({'message': f'exclude_categories must be one of: {", ".join(BUSINESS_CATEGORIES)}'}), 400
        query = query.filter(Business.category.notin_(exclude_categories))

    if food_only:
        query = query.filter(Business.category.in_(FOOD_CATEGORIES))

    if city:
        loc_ids = db.session.query(BusinessLocation.business_id).filter(BusinessLocation.city.ilike(f'%{city}%'))
        query = query.filter(Business.id.in_(loc_ids))

    if location_type:
        if location_type not in LOCATION_TYPES:
            return jsonify({'message': f'location_type must be one of: {", ".join(LOCATION_TYPES)}'}), 400
        loc_ids = db.session.query(BusinessLocation.business_id).filter(BusinessLocation.location_type == location_type)
        query = query.filter(Business.id.in_(loc_ids))

    if q:
        like = f'%{q}%'
        loc_ids = db.session.query(BusinessLocation.business_id).filter(
            db.or_(BusinessLocation.city.ilike(like), BusinessLocation.address.ilike(like)))
        query = query.filter(db.or_(Business.name.ilike(like), Business.about.ilike(like), Business.id.in_(loc_ids)))

    bbox_keys = ('north', 'south', 'east', 'west')
    if all(request.args.get(k) not in (None, '') for k in bbox_keys):
        try:
            north, south, east, west = (float(request.args.get(k)) for k in bbox_keys)
        except (TypeError, ValueError):
            return jsonify({'message': 'north/south/east/west must be numbers'}), 400
        loc_ids = db.session.query(BusinessLocation.business_id).filter(
            BusinessLocation.lat.isnot(None), BusinessLocation.lng.isnot(None),
            BusinessLocation.lat.between(south, north), BusinessLocation.lng.between(west, east))
        query = query.filter(Business.id.in_(loc_ids))

    # Captured before order_by is applied -- an ORDER BY (especially the
    # random-sort default) is irrelevant to a row count and only adds cost.
    # Reflects every SQL-level filter above; the kashrut/open_now branch
    # below overrides this with the Python-filtered count instead, since
    # those two live in per-location JSON and aren't filtered in SQL.
    total = query.count()

    # Boosted businesses (see routes/business_owner_tools.py) always sort
    # first, regardless of the requested sort -- that's the entire point of
    # earning one. Distance sort is applied in Python below (see the
    # candidate-window branch) since it needs a per-location computation.
    now = datetime.utcnow()
    boost_first = db.case((Business.boost_until.isnot(None) & (Business.boost_until > now), 0), else_=1)
    if sort == 'alpha':
        query = query.order_by(boost_first, Business.name.asc())
    elif sort == 'rating':
        query = query.order_by(boost_first, Business.rating_avg.desc(), Business.rating_count.desc())
    elif sort == 'newest':
        query = query.order_by(boost_first, Business.pub_date.desc())
    elif sort == 'distance':
        query = query.order_by(boost_first)  # final distance ordering happens in Python below
    else:
        query = query.order_by(boost_first, func.random())

    if kashrut_only or open_now or sort == 'distance':
        # Hours/kashrut live in per-location JSON and distance needs a
        # per-location computation, so all three are filtered/sorted in
        # Python against a capped candidate window rather than in SQL --
        # simple and correct at this site's current scale.
        candidates = query.limit(CANDIDATE_CAP).all()

        def matches(b):
            if kashrut_only and not any(l.kashrut for l in b.locations):
                return False
            if open_now and not any(_location_open_now(l) for l in b.locations):
                return False
            if sort == 'distance' and not any(l.lat is not None and l.lng is not None for l in b.locations):
                return False
            return True

        filtered = [b for b in candidates if matches(b)]

        if sort == 'distance':
            def min_distance(b):
                dists = [(l.lat - near_lat) ** 2 + (l.lng - near_lng) ** 2
                         for l in b.locations if l.lat is not None and l.lng is not None]
                return min(dists) if dists else float('inf')
            boosted_active = {b.id for b in filtered if b.boost_until and b.boost_until > now}
            filtered.sort(key=lambda b: (0 if b.id in boosted_active else 1, min_distance(b)))

        # Same CANDIDATE_CAP caveat as the query above: if there are more
        # than CANDIDATE_CAP SQL-level matches, this undercounts. Matches
        # the existing "simple and correct at this site's current scale"
        # tradeoff rather than a separate uncapped count query.
        total = len(filtered)
        start = (page - 1) * PAGE_SIZE
        page_rows = filtered[start:start + PAGE_SIZE + 1]
        has_more = len(page_rows) > PAGE_SIZE
        businesses = page_rows[:PAGE_SIZE]
    else:
        rows = query.limit(PAGE_SIZE + 1).offset((page - 1) * PAGE_SIZE).all()
        has_more = len(rows) > PAGE_SIZE
        businesses = rows[:PAGE_SIZE]

    schema = make_business_schema(current_user, many=True, card=True)
    return jsonify({'businesses': schema.dump(businesses), 'page': page, 'has_more': has_more, 'total': total})


def _business_site_url(business):
    """Public URL of a business's own Good-Shtick-built site -- None unless
    it's actually live (published AND, if it set a custom domain, that
    domain is verified), so BusinessProfile.js only ever shows a "Visit
    our website" link that actually resolves. A verified custom domain
    takes priority over the subdomain since that's the address the owner
    wants shown publicly."""
    site = getattr(business, 'site', None)
    if not site or site.status != 'published':
        return None
    if site.custom_domain and site.custom_domain_status == 'verified':
        return f'https://{site.custom_domain}'
    base = os.environ.get('BUSINESS_SITE_BASE_DOMAIN')
    return f'https://{site.subdomain}.{base}' if base else None


@business_api.route('/businesses/<identifier>', methods=['GET'])
@token_optional
def get_business(current_user, identifier):
    """Looked up by numeric id or slug."""
    query = Business.query.options(*_feed_options())
    business = query.filter_by(id=int(identifier)).first() if identifier.isdigit() else query.filter_by(slug=identifier).first()
    if not business or (business.approved_to_publish is not True and not _can_manage(business, current_user)):
        return jsonify({'message': 'Business not found'}), 404
    schema = make_business_schema(current_user, many=False, card=False)
    data = schema.dump(business)
    data['site_url'] = _business_site_url(business)

    recent_posts = (BusinessPost.query
                     .filter_by(business_id=business.id, approved_to_publish=True)
                     .order_by(BusinessPost.pub_date.desc())
                     .limit(RECENT_POSTS_LIMIT).all())
    recent_comments = (BusinessComment.query
                        .filter_by(business_id=business.id, approved_to_publish=True)
                        .order_by(BusinessComment.pub_date.desc())
                        .limit(RECENT_COMMENTS_LIMIT).all())
    data['recent_posts'] = make_business_post_schema(current_user, many=True).dump(recent_posts)
    data['recent_comments'] = make_comment_schema(current_user, many=True).dump(recent_comments)
    return jsonify(data)


@business_api.route('/businesses', methods=['POST'])
@token_required
def create_business(current_user):
    """Goes live immediately -- an unclaimed listing is just directory data,
    nothing to impersonate yet. See BusinessClaim for the actual trust gate."""
    body = request.get_json() or {}
    name = (body.get('name') or '').strip()
    category = (body.get('category') or '').strip().lower()
    about = (body.get('about') or '').strip()

    if not name:
        return jsonify({'message': 'Name is required'}), 400
    if len(name) > NAME_MAX:
        return jsonify({'message': f'Name must be {NAME_MAX} characters or fewer'}), 400
    if category not in BUSINESS_CATEGORIES:
        return jsonify({'message': f'category must be one of: {", ".join(BUSINESS_CATEGORIES)}'}), 400
    if len(about) > ABOUT_MAX:
        return jsonify({'message': f'About must be {ABOUT_MAX} characters or fewer'}), 400
    attributes = body.get('attributes')
    if attributes is not None and not isinstance(attributes, dict):
        return jsonify({'message': 'attributes must be an object'}), 400

    website = (body.get('website') or '').strip()
    if len(website) > WEBSITE_MAX:
        return jsonify({'message': f'Website must be {WEBSITE_MAX} characters or fewer'}), 400
    source_url = (body.get('source_url') or '').strip()
    if len(source_url) > SOURCE_URL_MAX:
        return jsonify({'message': f'source_url must be {SOURCE_URL_MAX} characters or fewer'}), 400
    source_name = (body.get('source_name') or '').strip()
    if len(source_name) > SOURCE_NAME_MAX:
        return jsonify({'message': f'source_name must be {SOURCE_NAME_MAX} characters or fewer'}), 400

    business = Business(
        slug=_unique_slug(name),
        name=name,
        category=category,
        about=about or None,
        logo=body.get('logo') or None,
        created_by=current_user.public_id,
        attributes=attributes,
        website=website or None,
        source_url=source_url or None,
        source_name=source_name or None,
        # Derived, not client-trusted as a raw flag: a listing counts as
        # "imported" exactly when it comes with a source citation rather
        # than being entered firsthand by/for the business itself.
        imported=bool(source_url or source_name),
        approved_to_publish=True,
    )
    db.session.add(business)
    db.session.flush()

    for loc_body in (body.get('locations') or []):
        error, fields = _validate_location(loc_body)
        if error:
            db.session.rollback()
            return error, 400
        db.session.add(BusinessLocation(business_id=business.id, **fields))

    db.session.commit()
    schema = make_business_schema(current_user, many=False, card=False)
    return jsonify(schema.dump(business)), 201


@business_api.route('/businesses/guest', methods=['POST'])
def create_guest_business():
    """Same validation as create_business, minus the login requirement --
    goes into the pending queue instead of live immediately (see
    Business.approved_to_publish). This is how "discount"/deal coverage
    is offered to a guest without opening deal-posting itself to anyone
    anonymous: get the business listed first, then claim it for real."""
    body = request.get_json() or {}
    name = (body.get('name') or '').strip()
    category = (body.get('category') or '').strip().lower()
    about = (body.get('about') or '').strip()

    if not name:
        return jsonify({'message': 'Name is required'}), 400
    if len(name) > NAME_MAX:
        return jsonify({'message': f'Name must be {NAME_MAX} characters or fewer'}), 400
    if category not in BUSINESS_CATEGORIES:
        return jsonify({'message': f'category must be one of: {", ".join(BUSINESS_CATEGORIES)}'}), 400
    if len(about) > ABOUT_MAX:
        return jsonify({'message': f'About must be {ABOUT_MAX} characters or fewer'}), 400
    attributes = body.get('attributes')
    if attributes is not None and not isinstance(attributes, dict):
        return jsonify({'message': 'attributes must be an object'}), 400

    website = (body.get('website') or '').strip()
    if len(website) > WEBSITE_MAX:
        return jsonify({'message': f'Website must be {WEBSITE_MAX} characters or fewer'}), 400

    guest_email = (body.get('guest_email') or '').strip()[:GUEST_EMAIL_MAX]
    guest_phone = (body.get('guest_phone') or '').strip()[:GUEST_PHONE_MAX]
    if not (guest_email or guest_phone):
        return jsonify({'message': 'At least one of guest_email or guest_phone is required'}), 400

    from backend.guest.modals.guest_throttle import check_and_record_guest_submission
    if not check_and_record_guest_submission(request):
        return jsonify({'message': 'Too many submissions from this network today -- please try again tomorrow.'}), 429

    business = Business(
        slug=_unique_slug(name),
        name=name,
        category=category,
        about=about or None,
        logo=body.get('logo') or None,
        created_by=None,
        attributes=attributes,
        website=website or None,
        approved_to_publish=None,
        guest_email=guest_email or None,
        guest_phone=guest_phone or None,
        guest_manage_token=secrets.token_urlsafe(32),
    )
    db.session.add(business)
    db.session.flush()

    for loc_body in (body.get('locations') or []):
        error, fields = _validate_location(loc_body)
        if error:
            db.session.rollback()
            return error, 400
        db.session.add(BusinessLocation(business_id=business.id, **fields))

    db.session.commit()

    if guest_email:
        try:
            from backend.alerts import emails
            emails.send_guest_submission_email(
                guest_email, 'your business listing', business.name,
                f'{BUSINESS_SITE_URL}/guest/business/{business.guest_manage_token}',
            )
        except Exception:
            pass  # an email failure should never break the actual submission

    schema = make_business_schema(None, many=False, card=False)
    data = schema.dump(business)
    data['guest_manage_token'] = business.guest_manage_token
    return jsonify(data), 201


@business_api.route('/businesses/guest/<token>', methods=['GET'])
def get_guest_business(token):
    business = Business.query.options(*_feed_options()).filter_by(guest_manage_token=token).first()
    if not business:
        return jsonify({'message': 'Business not found'}), 404
    schema = make_business_schema(None, many=False, card=False)
    return jsonify(schema.dump(business))


@business_api.route('/businesses/guest/<token>', methods=['PATCH'])
def edit_guest_business(token):
    business = Business.query.filter_by(guest_manage_token=token).first()
    if not business:
        return jsonify({'message': 'Business not found'}), 404

    body = request.get_json() or {}
    if 'name' in body:
        name = (body.get('name') or '').strip()
        if not name:
            return jsonify({'message': 'Name is required'}), 400
        if len(name) > NAME_MAX:
            return jsonify({'message': f'Name must be {NAME_MAX} characters or fewer'}), 400
        business.name = name
    if 'category' in body:
        category = (body.get('category') or '').strip().lower()
        if category not in BUSINESS_CATEGORIES:
            return jsonify({'message': f'category must be one of: {", ".join(BUSINESS_CATEGORIES)}'}), 400
        business.category = category
    if 'about' in body:
        about = (body.get('about') or '').strip()
        if len(about) > ABOUT_MAX:
            return jsonify({'message': f'About must be {ABOUT_MAX} characters or fewer'}), 400
        business.about = about or None
    if 'logo' in body:
        business.logo = body.get('logo') or None
    if 'website' in body:
        website = (body.get('website') or '').strip()
        if len(website) > WEBSITE_MAX:
            return jsonify({'message': f'Website must be {WEBSITE_MAX} characters or fewer'}), 400
        business.website = website or None
    if 'attributes' in body:
        attributes = body.get('attributes')
        if attributes is not None and not isinstance(attributes, dict):
            return jsonify({'message': 'attributes must be an object'}), 400
        business.attributes = attributes

    db.session.commit()
    schema = make_business_schema(None, many=False, card=False)
    return jsonify(schema.dump(business))


@business_api.route('/businesses/guest/<token>', methods=['DELETE'])
def delete_guest_business(token):
    business = Business.query.filter_by(guest_manage_token=token).first()
    if not business:
        return jsonify({'message': 'Business not found'}), 404
    db.session.delete(business)
    db.session.commit()
    return jsonify({'message': 'Deleted'})


@business_api.route('/admin/businesses/pending', methods=['GET'])
@admin_required
def get_pending_businesses(_current_user):
    pending = (Business.query.options(*_feed_options())
               .filter_by(approved_to_publish=None)
               .order_by(Business.pub_date.asc()).all())
    schema = make_business_schema(None, many=True, card=False)
    return jsonify(schema.dump(pending))


@business_api.route('/admin/businesses/<int:business_id>/approve', methods=['POST'])
@admin_required
def approve_business(_current_user, business_id):
    business = db.session.get(Business, business_id)
    if not business:
        return jsonify({'message': 'Business not found'}), 404
    body = request.get_json(silent=True) or {}
    approved = not body.get('reject', False)
    business.approved_to_publish = approved
    db.session.commit()
    return jsonify({'message': 'approved' if approved else 'rejected'})


@business_api.route('/businesses/<int:business_id>', methods=['PATCH'])
@token_required
def edit_business(current_user, business_id):
    business = db.session.get(Business, business_id)
    if not business:
        return jsonify({'message': 'Business not found'}), 404
    if not _can_manage(business, current_user):
        return jsonify({'message': 'Not authorized'}), 403

    body = request.get_json() or {}
    if 'name' in body:
        name = (body.get('name') or '').strip()
        if not name:
            return jsonify({'message': 'Name is required'}), 400
        if len(name) > NAME_MAX:
            return jsonify({'message': f'Name must be {NAME_MAX} characters or fewer'}), 400
        business.name = name
    if 'category' in body:
        category = (body.get('category') or '').strip().lower()
        if category not in BUSINESS_CATEGORIES:
            return jsonify({'message': f'category must be one of: {", ".join(BUSINESS_CATEGORIES)}'}), 400
        business.category = category
    if 'about' in body:
        about = (body.get('about') or '').strip()
        if len(about) > ABOUT_MAX:
            return jsonify({'message': f'About must be {ABOUT_MAX} characters or fewer'}), 400
        business.about = about or None
    if 'logo' in body:
        business.logo = body.get('logo') or None
    if 'website' in body:
        website = (body.get('website') or '').strip()
        if len(website) > WEBSITE_MAX:
            return jsonify({'message': f'Website must be {WEBSITE_MAX} characters or fewer'}), 400
        business.website = website or None
    if 'attributes' in body:
        attributes = body.get('attributes')
        if attributes is not None and not isinstance(attributes, dict):
            return jsonify({'message': 'attributes must be an object'}), 400
        business.attributes = attributes

    db.session.commit()
    schema = make_business_schema(current_user, many=False, card=False)
    return jsonify(schema.dump(business))


@business_api.route('/businesses/<int:business_id>', methods=['DELETE'])
@token_required
def delete_business(current_user, business_id):
    business = db.session.get(Business, business_id)
    if not business:
        return jsonify({'message': 'Business not found'}), 404
    if not _can_manage(business, current_user):
        return jsonify({'message': 'Not authorized'}), 403
    db.session.delete(business)
    db.session.commit()
    return jsonify({'message': 'Deleted'})


# ── Locations ────────────────────────────────────────────────────────────

@business_api.route('/businesses/<int:business_id>/locations', methods=['POST'])
@token_required
def add_location(current_user, business_id):
    business = db.session.get(Business, business_id)
    if not business:
        return jsonify({'message': 'Business not found'}), 404
    if not _can_manage(business, current_user):
        return jsonify({'message': 'Not authorized'}), 403

    body = request.get_json() or {}
    error, fields = _validate_location(body)
    if error:
        return error, 400
    location = BusinessLocation(business_id=business.id, **fields)
    db.session.add(location)
    db.session.commit()
    schema = make_business_schema(current_user, many=False, card=False)
    return jsonify(schema.dump(business)), 201


@business_api.route('/locations/<int:location_id>', methods=['PATCH'])
@token_required
def edit_location(current_user, location_id):
    location = db.session.get(BusinessLocation, location_id)
    if not location:
        return jsonify({'message': 'Location not found'}), 404
    if not _can_manage(location.business, current_user):
        return jsonify({'message': 'Not authorized'}), 403

    body = request.get_json() or {}
    error, fields = _validate_location({**_location_to_dict(location), **body})
    if error:
        return error, 400
    for key, value in fields.items():
        setattr(location, key, value)
    db.session.commit()
    schema = make_business_schema(current_user, many=False, card=False)
    return jsonify(schema.dump(location.business))


def _location_to_dict(location):
    return {
        'location_type': location.location_type,
        'address': location.address, 'city': location.city, 'state': location.state,
        'zip_code': location.zip_code, 'country': location.country, 'lat': location.lat,
        'lng': location.lng, 'phone': location.phone, 'email': location.email,
        'hours': location.hours, 'kashrut': location.kashrut, 'attributes': location.attributes,
        'is_primary': location.is_primary,
    }


@business_api.route('/locations/<int:location_id>', methods=['DELETE'])
@token_required
def delete_location(current_user, location_id):
    location = db.session.get(BusinessLocation, location_id)
    if not location:
        return jsonify({'message': 'Location not found'}), 404
    if not _can_manage(location.business, current_user):
        return jsonify({'message': 'Not authorized'}), 403
    business = location.business
    db.session.delete(location)
    db.session.commit()
    schema = make_business_schema(current_user, many=False, card=False)
    return jsonify(schema.dump(business))


@business_api.route('/upload', methods=['POST'])
@token_required
def add_upload(_current_user):
    """Reuses the shared Supabase upload pipeline -- same as /hock/upload."""
    filename = upload_file(request)
    if not filename:
        return jsonify({'message': 'Upload failed'}), 400
    return jsonify(filename)


# ── Claiming ─────────────────────────────────────────────────────────────

@business_api.route('/businesses/<int:business_id>/claim', methods=['POST'])
@token_required
def claim_business(current_user, business_id):
    business = db.session.get(Business, business_id)
    if not business:
        return jsonify({'message': 'Business not found'}), 404
    if business.owner_user_id:
        return jsonify({'message': 'This business is already claimed'}), 400
    existing = BusinessClaim.query.filter_by(
        business_id=business_id, user_id=current_user.public_id, status='pending').first()
    if existing:
        return jsonify({'message': 'You already have a pending claim on this business'}), 409

    body = request.get_json() or {}
    claim = BusinessClaim(business_id=business_id, user_id=current_user.public_id,
                           message=(body.get('message') or '').strip() or None)
    db.session.add(claim)
    db.session.commit()
    return jsonify(ClaimSchema().dump(claim)), 201


def _owned_sites(owned):
    """One extra query (not N+1) mapping each owned business to its
    BusinessSite, if any -- lets MyBusinesses.js show a direct "Manage
    website" / "View live site" link per business without the profile
    dropdown or this list otherwise having any way to know a site even
    exists (previously the only path in was already being inside a
    specific business's own Manage Tools page and knowing to look for the
    Site tab there)."""
    if not owned:
        return {}
    base = os.environ.get('BUSINESS_SITE_BASE_DOMAIN')
    sites = BusinessSite.query.filter(BusinessSite.business_id.in_([b.id for b in owned])).all()
    return {
        s.business_id: {
            'status': s.status,
            'subdomain': s.subdomain,
            'url': f'https://{s.subdomain}.{base}' if base else None,
        }
        for s in sites
    }


@business_api.route('/my/businesses', methods=['GET'])
@token_required
def my_businesses(current_user):
    owned = Business.query.options(*_feed_options()).filter_by(owner_user_id=current_user.public_id).all()
    created = Business.query.options(*_feed_options()).filter_by(created_by=current_user.public_id).all()
    claims = BusinessClaim.query.filter_by(user_id=current_user.public_id).order_by(BusinessClaim.created_at.desc()).all()

    schema = make_business_schema(current_user, many=True, card=True)
    owned_dump = schema.dump(owned)
    sites_by_business = _owned_sites(owned)
    for row, business in zip(owned_dump, owned):
        row['site'] = sites_by_business.get(business.id)

    return jsonify({
        'owned': owned_dump,
        'created': schema.dump(created),
        'claims': ClaimSchema(many=True).dump(claims),
    })


@business_api.route('/admin/claims/pending', methods=['GET'])
@admin_required
def admin_pending_claims(_current_user):
    claims = (BusinessClaim.query
              .filter_by(status='pending')
              .order_by(BusinessClaim.created_at.asc())
              .all())
    return jsonify(ClaimSchema(many=True).dump(claims))


@business_api.route('/admin/claims/<int:claim_id>/approve', methods=['POST'])
@admin_required
def approve_claim(current_user, claim_id):
    claim = db.session.get(BusinessClaim, claim_id)
    if not claim:
        return jsonify({'message': 'Claim not found'}), 404
    if claim.status != 'pending':
        return jsonify({'message': 'Claim already reviewed'}), 400

    business = claim.business
    if business.owner_user_id:
        claim.status = 'rejected'
        claim.reviewed_by = current_user.public_id
        claim.reviewed_at = datetime.utcnow()
        db.session.commit()
        return jsonify({'message': 'This business was already claimed by someone else -- request auto-rejected'}), 409

    business.owner_user_id = claim.user_id
    claim.status = 'approved'
    claim.reviewed_by = current_user.public_id
    claim.reviewed_at = datetime.utcnow()

    (BusinessClaim.query
     .filter(BusinessClaim.business_id == business.id, BusinessClaim.id != claim.id, BusinessClaim.status == 'pending')
     .update({'status': 'rejected', 'reviewed_by': current_user.public_id, 'reviewed_at': datetime.utcnow()}))

    db.session.commit()
    return jsonify({'message': 'approved'})


@business_api.route('/admin/claims/<int:claim_id>/reject', methods=['POST'])
@admin_required
def reject_claim(current_user, claim_id):
    claim = db.session.get(BusinessClaim, claim_id)
    if not claim:
        return jsonify({'message': 'Claim not found'}), 404
    if claim.status != 'pending':
        return jsonify({'message': 'Claim already reviewed'}), 400
    claim.status = 'rejected'
    claim.reviewed_by = current_user.public_id
    claim.reviewed_at = datetime.utcnow()
    db.session.commit()
    return jsonify({'message': 'rejected'})
