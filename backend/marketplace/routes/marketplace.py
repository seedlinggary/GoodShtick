"""Community Marketplace -- buy/sell/trade/giveaway, open to the whole
network (lives on the main site, same placement reasoning as Hock: general-
interest content, not one sub-site's own vertical). Goes live immediately on
posting, same philosophy as EstatesListing/Business/Community -- an
unclaimed directory-style post, nothing to impersonate yet."""
import math
from datetime import datetime, timedelta

import requests
from flask import Blueprint, jsonify, request
from sqlalchemy.orm import selectinload

from config import db
from security import token_required, token_optional, admin_required
from upload import upload_file
from backend.marketplace.modals.marketplace import (
    MarketplaceListing, MarketplaceListingPhoto, MarketplaceListingLike,
    MARKETPLACE_CATEGORIES, CONDITIONS, CURRENCIES, MAX_PHOTOS, SAVED_STATUSES,
    NOTE_MAX, MARKETPLACE_STATUSES, slugify,
)
from backend.marketplace.schemas.marketplace import MarketplaceListingSchema, MarketplaceListingCardSchema

marketplace_api = Blueprint('marketplace_api', __name__, url_prefix='/marketplace')

TITLE_MAX = 150
DESCRIPTION_MAX = 4000
ADDRESS_MAX, CITY_MAX, STATE_MAX, COUNTRY_MAX = 300, 120, 80, 80
CONTACT_NAME_MAX, EMAIL_MAX, PHONE_MAX, CONTACT_LINK_MAX = 150, 150, 40, 500
MILES_PER_DEGREE_LAT = 69
DEFAULT_NEAR_RADIUS_MILES = 25
PAGE_SIZE = 24
GUEST_EMAIL_MAX = 150
GUEST_PHONE_MAX = 40

PHOTON_URL = 'https://photon.komoot.io/api/'
# Same honest identification as the Tachlis geocoder this was copied from --
# Photon returns 403 to Python's default User-Agent.
PHOTON_HEADERS = {'User-Agent': 'GutShtick-Backend/1.0 (https://www.goodshtick.com)'}

# Non-place / vague location terms rejected outright rather than geocoded --
# see backend/tachlis/routes/tachlis_post.py's _geocode for the full
# reasoning (confirmed live: Photon returns a real-but-wrong match for
# "Remote" rather than correctly reporting no result).
_VAGUE_LOCATION_TERMS = {
    'remote', 'anywhere', 'various', 'n/a', 'na', 'tbd', 'usa', 'us',
    'nationwide', 'worldwide', 'flexible', 'ships only', 'online',
}


def _geocode(location_text):
    """Best-effort geocoding via Photon -- identical hardened logic to
    backend/tachlis/routes/tachlis_post.py's _geocode (vague-term rejection,
    trailing-parenthetical stripping, whole-country-match rejection),
    duplicated per this codebase's established per-domain convention rather
    than cross-imported. Returns (lat, lng) or (None, None)."""
    import re
    if not location_text:
        return None, None
    text = re.sub(r'\s*\([^)]*\)\s*$', '', location_text).strip()
    if '-' in text:
        prefix, _, rest = text.partition('-')
        if prefix.strip().lower() in _VAGUE_LOCATION_TERMS and rest.strip():
            text = rest.strip()
    if not text or text.lower() in _VAGUE_LOCATION_TERMS:
        return None, None
    try:
        res = requests.get(PHOTON_URL, params={'q': text, 'limit': 1},
                            headers=PHOTON_HEADERS, timeout=5)
        res.raise_for_status()
        features = res.json().get('features') or []
        if not features:
            return None, None
        top = features[0]
        if top['properties'].get('osm_value') == 'country':
            return None, None
        lng, lat = top['geometry']['coordinates']
        return lat, lng
    except Exception:
        return None, None


def _bbox_from_point(lat, lng, miles):
    lat_delta = miles / MILES_PER_DEGREE_LAT
    lng_delta = miles / (MILES_PER_DEGREE_LAT * math.cos(math.radians(lat))) if lat else miles / MILES_PER_DEGREE_LAT
    return lat - lat_delta, lat + lat_delta, lng - lng_delta, lng + lng_delta


def _unique_slug(title):
    base = slugify(title)
    rows = {row[0] for row in db.session.query(MarketplaceListing.slug).filter(MarketplaceListing.slug.like(f'{base}%')).all()}
    if base not in rows:
        return base
    n = 2
    while f'{base}-{n}' in rows:
        n += 1
    return f'{base}-{n}'


def _can_manage(listing, user):
    if not user:
        return False
    if user.is_boss:
        return True
    return listing.created_by == user.public_id


def _feed_options():
    return (selectinload(MarketplaceListing.photos),)


def _validate_listing_body(body, partial=False, existing=None):
    """Returns (error_response_or_None, cleaned_fields_dict). `partial`
    skips required-field checks for PATCH, where an omitted key means
    'leave as-is' (checked by the caller via `'key' in body`)."""
    fields = {}

    if not partial or 'title' in body:
        title = (body.get('title') or '').strip()
        if not title:
            return jsonify({'message': 'Title is required'}), None
        if len(title) > TITLE_MAX:
            return jsonify({'message': f'Title must be {TITLE_MAX} characters or fewer'}), None
        fields['title'] = title

    if not partial or 'category' in body:
        category = (body.get('category') or '').strip().lower()
        if category not in MARKETPLACE_CATEGORIES:
            return jsonify({'message': f'category must be one of: {", ".join(MARKETPLACE_CATEGORIES)}'}), None
        fields['category'] = category

    if 'subcategory' in body:
        subcategory = (body.get('subcategory') or '').strip()
        cat = fields.get('category') or (existing.category if existing else None)
        valid_subs = MARKETPLACE_CATEGORIES.get(cat, {}).get('subcategories', [])
        if subcategory and subcategory not in valid_subs:
            return jsonify({'message': f'subcategory must be one of: {", ".join(valid_subs)}' if valid_subs else 'This category has no subcategories'}), None
        fields['subcategory'] = subcategory or None

    if 'description' in body:
        description = (body.get('description') or '').strip()
        if len(description) > DESCRIPTION_MAX:
            return jsonify({'message': f'Description must be {DESCRIPTION_MAX} characters or fewer'}), None
        fields['description'] = description or None

    if 'condition' in body:
        condition = (body.get('condition') or '').strip().lower()
        if condition and condition not in CONDITIONS:
            return jsonify({'message': f'condition must be one of: {", ".join(CONDITIONS)}'}), None
        fields['condition'] = condition or None

    if 'is_free' in body:
        fields['is_free'] = bool(body.get('is_free'))
    if 'ships' in body:
        fields['ships'] = bool(body.get('ships'))

    is_free = fields.get('is_free') if 'is_free' in fields else (existing.is_free if existing else False)
    if 'price' in body:
        price = body.get('price')
        if is_free:
            fields['price'] = None
        elif price is not None:
            try:
                price = float(price)
            except (TypeError, ValueError):
                return jsonify({'message': 'price must be a number'}), None
            if price < 0:
                return jsonify({'message': 'price must not be negative'}), None
            fields['price'] = price
        else:
            fields['price'] = None
    elif is_free:
        fields['price'] = None

    if 'currency' in body:
        currency = (body.get('currency') or 'USD').strip().upper()
        if currency not in CURRENCIES:
            return jsonify({'message': f'currency must be one of: {", ".join(CURRENCIES)}'}), None
        fields['currency'] = currency

    for key, maxlen in (('address', ADDRESS_MAX), ('city', CITY_MAX), ('state', STATE_MAX), ('country', COUNTRY_MAX)):
        if key in body:
            val = (body.get(key) or '').strip()
            if len(val) > maxlen:
                return jsonify({'message': f'{key} must be {maxlen} characters or fewer'}), None
            fields[key] = val or None

    for key in ('lat', 'lng'):
        if key in body:
            val = body.get(key)
            if val is not None and val != '':
                try:
                    val = float(val)
                except (TypeError, ValueError):
                    return jsonify({'message': f'{key} must be a number'}), None
                fields[key] = val
            else:
                fields[key] = None

    # Geocode from city/country when the caller didn't already supply real
    # coordinates (e.g. from AddressAutocomplete.js) -- best-effort, never
    # blocks posting if it comes back empty.
    if fields.get('lat') is None and fields.get('lng') is None and ('city' in fields or 'country' in fields):
        location_text = ', '.join(filter(None, [fields.get('city'), fields.get('state'), fields.get('country')]))
        lat, lng = _geocode(location_text)
        if lat is not None:
            fields['lat'], fields['lng'] = lat, lng

    if 'contact_name' in body:
        val = (body.get('contact_name') or '').strip()
        if len(val) > CONTACT_NAME_MAX:
            return jsonify({'message': f'contact_name must be {CONTACT_NAME_MAX} characters or fewer'}), None
        fields['contact_name'] = val or None

    for key in ('contact_email', 'contact_phone', 'contact_whatsapp'):
        if key in body:
            val = (body.get(key) or '').strip()
            if len(val) > (EMAIL_MAX if key == 'contact_email' else PHONE_MAX):
                return jsonify({'message': f'{key} is too long'}), None
            fields[key] = val or None

    if 'contact_link' in body:
        val = (body.get('contact_link') or '').strip()
        if len(val) > CONTACT_LINK_MAX:
            return jsonify({'message': 'contact_link is too long'}), None
        fields['contact_link'] = val or None

    email = fields['contact_email'] if 'contact_email' in fields else (existing.contact_email if existing else None)
    phone = fields['contact_phone'] if 'contact_phone' in fields else (existing.contact_phone if existing else None)
    link = fields['contact_link'] if 'contact_link' in fields else (existing.contact_link if existing else None)
    if not (email or phone or link):
        return jsonify({'message': 'At least one of contact_email, contact_phone, or contact_link is required'}), None

    return None, fields


@marketplace_api.route('/categories', methods=['GET'])
def list_categories():
    return jsonify({'categories': MARKETPLACE_CATEGORIES})


@marketplace_api.route('/listings', methods=['GET'])
@token_optional
def list_listings(current_user):
    q = (request.args.get('q') or '').strip()
    category = (request.args.get('category') or '').strip().lower()
    subcategory = (request.args.get('subcategory') or '').strip()
    country = (request.args.get('country') or '').strip()
    city = (request.args.get('city') or '').strip()
    condition = (request.args.get('condition') or '').strip().lower()
    free_only = (request.args.get('free_only') or '').strip() in ('1', 'true')
    ships_only = (request.args.get('ships_only') or '').strip() in ('1', 'true')
    sort = (request.args.get('sort') or 'newest').strip().lower()
    try:
        price_min = float(request.args.get('price_min')) if request.args.get('price_min') else None
        price_max = float(request.args.get('price_max')) if request.args.get('price_max') else None
    except (TypeError, ValueError):
        return jsonify({'message': 'price_min/price_max must be numbers'}), 400
    try:
        page = max(1, int(request.args.get('page', 1)))
    except (TypeError, ValueError):
        page = 1

    near_lat = near_lng = None
    radius_miles = DEFAULT_NEAR_RADIUS_MILES
    if sort == 'nearest' or request.args.get('lat'):
        try:
            near_lat, near_lng = float(request.args.get('lat')), float(request.args.get('lng'))
            radius_miles = float(request.args.get('radius_miles', DEFAULT_NEAR_RADIUS_MILES))
        except (TypeError, ValueError):
            return jsonify({'message': 'lat/lng must be numeric'}), 400

    now = datetime.utcnow()
    query = MarketplaceListing.query.options(*_feed_options()).filter(
        MarketplaceListing.status == 'active',
        MarketplaceListing.approved_to_publish.is_(True),
        db.or_(MarketplaceListing.expires_at.is_(None), MarketplaceListing.expires_at > now),
    )
    if q:
        like = f'%{q}%'
        query = query.filter(db.or_(MarketplaceListing.title.ilike(like), MarketplaceListing.description.ilike(like)))
    if category:
        query = query.filter(MarketplaceListing.category == category)
    if subcategory:
        query = query.filter(MarketplaceListing.subcategory == subcategory)
    if country:
        query = query.filter(MarketplaceListing.country.ilike(country))
    if city:
        query = query.filter(MarketplaceListing.city.ilike(f'%{city}%'))
    if condition:
        query = query.filter(MarketplaceListing.condition == condition)
    if free_only:
        query = query.filter(MarketplaceListing.is_free.is_(True))
    if ships_only:
        query = query.filter(MarketplaceListing.ships.is_(True))
    if price_min is not None:
        query = query.filter(MarketplaceListing.price.isnot(None), MarketplaceListing.price >= price_min)
    if price_max is not None:
        query = query.filter(MarketplaceListing.price.isnot(None), MarketplaceListing.price <= price_max)

    # "Near me" never excludes shippable items -- a buyer searching near
    # their own location should still see a seforim seller across the
    # world who ships, not just local pickup-only furniture.
    if near_lat is not None:
        south, north, west, east = _bbox_from_point(near_lat, near_lng, radius_miles)
        query = query.filter(db.or_(
            MarketplaceListing.ships.is_(True),
            db.and_(MarketplaceListing.lat.isnot(None), MarketplaceListing.lng.isnot(None),
                    MarketplaceListing.lat.between(south, north), MarketplaceListing.lng.between(west, east)),
        ))

    total = query.count()

    if sort == 'price_asc':
        query = query.order_by(MarketplaceListing.price.asc().nulls_last())
    elif sort == 'price_desc':
        query = query.order_by(MarketplaceListing.price.desc().nulls_last())
    elif sort == 'nearest' and near_lat is not None:
        # Python-side distance sort over this page's candidate window --
        # same reasoning as Community/Business's own distance sorts: a
        # simple squared-distance comparison is enough at this scale, no
        # need for a real geo index.
        rows = query.offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE * 3).all()
        rows.sort(key=lambda r: ((r.lat - near_lat) ** 2 + (r.lng - near_lng) ** 2) if r.lat is not None else 1e9)
        rows = rows[:PAGE_SIZE]
        return jsonify({
            'items': MarketplaceListingCardSchema(many=True).dump(rows),
            'page': page, 'total': total, 'per_page': PAGE_SIZE, 'has_more': page * PAGE_SIZE < total,
        })
    else:
        query = query.order_by(MarketplaceListing.pub_date.desc())

    rows = query.offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE).all()
    return jsonify({
        'items': MarketplaceListingCardSchema(many=True).dump(rows),
        'page': page, 'total': total, 'per_page': PAGE_SIZE, 'has_more': page * PAGE_SIZE < total,
    })


@marketplace_api.route('/listings/<identifier>', methods=['GET'])
@token_optional
def get_listing(current_user, identifier):
    query = MarketplaceListing.query.options(*_feed_options())
    listing = query.filter_by(id=int(identifier)).first() if identifier.isdigit() else query.filter_by(slug=identifier).first()
    if not listing or (listing.approved_to_publish is not True and not _can_manage(listing, current_user)):
        return jsonify({'message': 'Listing not found'}), 404
    listing.views_count = (listing.views_count or 0) + 1
    db.session.commit()
    data = MarketplaceListingSchema().dump(listing)
    data['can_manage'] = _can_manage(listing, current_user)
    data['is_saved'] = bool(current_user and MarketplaceListingLike.query.filter_by(
        listing_id=listing.id, user_id=current_user.public_id).first())
    return jsonify(data)


@marketplace_api.route('/listings', methods=['POST'])
@token_required
def create_listing(current_user):
    body = request.get_json() or {}
    error, fields = _validate_listing_body(body, partial=False)
    if error:
        return error, 400

    listing = MarketplaceListing(
        slug=_unique_slug(fields['title']), title=fields['title'], category=fields['category'],
        created_by=current_user.public_id, approved_to_publish=True,
        **{k: v for k, v in fields.items() if k not in ('title', 'category')},
    )
    db.session.add(listing)
    db.session.flush()

    for i, filename in enumerate((body.get('photos') or [])[:MAX_PHOTOS]):
        db.session.add(MarketplaceListingPhoto(listing_id=listing.id, filename=filename, position=i))

    db.session.commit()
    return jsonify(MarketplaceListingSchema().dump(listing)), 201


@marketplace_api.route('/listings/guest', methods=['POST'])
def create_guest_listing():
    body = request.get_json() or {}
    error, fields = _validate_listing_body(body, partial=False)
    if error:
        return error, 400

    guest_email = (body.get('guest_email') or '').strip()[:GUEST_EMAIL_MAX]
    guest_phone = (body.get('guest_phone') or '').strip()[:GUEST_PHONE_MAX]
    if not (guest_email or guest_phone):
        return jsonify({'message': 'At least one of guest_email or guest_phone is required'}), 400

    from backend.guest.modals.guest_throttle import check_and_record_guest_submission
    if not check_and_record_guest_submission(request):
        return jsonify({'message': 'Too many submissions from this network today -- please try again tomorrow.'}), 429

    import secrets
    listing = MarketplaceListing(
        slug=_unique_slug(fields['title']), title=fields['title'], category=fields['category'],
        created_by=None, approved_to_publish=None,
        guest_email=guest_email or None, guest_phone=guest_phone or None,
        guest_manage_token=secrets.token_urlsafe(32),
        **{k: v for k, v in fields.items() if k not in ('title', 'category')},
    )
    db.session.add(listing)
    db.session.flush()

    for i, filename in enumerate((body.get('photos') or [])[:MAX_PHOTOS]):
        db.session.add(MarketplaceListingPhoto(listing_id=listing.id, filename=filename, position=i))

    db.session.commit()

    if guest_email:
        try:
            from backend.alerts import emails
            from backend.alerts.routes.alert import MAIN_SITE_URL
            emails.send_guest_submission_email(
                guest_email, 'your Marketplace listing', listing.title,
                f'{MAIN_SITE_URL}/guest/marketplace/{listing.guest_manage_token}',
            )
        except Exception:
            pass  # an email failure should never break the actual submission

    data = MarketplaceListingSchema().dump(listing)
    data['guest_manage_token'] = listing.guest_manage_token
    return jsonify(data), 201


@marketplace_api.route('/listings/guest/<token>', methods=['GET'])
def get_guest_listing(token):
    listing = MarketplaceListing.query.options(*_feed_options()).filter_by(guest_manage_token=token).first()
    if not listing:
        return jsonify({'message': 'Listing not found'}), 404
    return jsonify(MarketplaceListingSchema().dump(listing))


@marketplace_api.route('/listings/guest/<token>', methods=['PATCH'])
def edit_guest_listing(token):
    listing = MarketplaceListing.query.filter_by(guest_manage_token=token).first()
    if not listing:
        return jsonify({'message': 'Listing not found'}), 404

    body = request.get_json() or {}
    error, fields = _validate_listing_body(body, partial=True, existing=listing)
    if error:
        return error, 400
    for key, value in fields.items():
        setattr(listing, key, value)

    if 'photos' in body:
        MarketplaceListingPhoto.query.filter_by(listing_id=listing.id).delete()
        db.session.flush()
        for i, filename in enumerate((body.get('photos') or [])[:MAX_PHOTOS]):
            db.session.add(MarketplaceListingPhoto(listing_id=listing.id, filename=filename, position=i))

    db.session.commit()
    return jsonify(MarketplaceListingSchema().dump(listing))


@marketplace_api.route('/listings/guest/<token>', methods=['DELETE'])
def delete_guest_listing(token):
    listing = MarketplaceListing.query.filter_by(guest_manage_token=token).first()
    if not listing:
        return jsonify({'message': 'Listing not found'}), 404
    db.session.delete(listing)
    db.session.commit()
    return jsonify({'message': 'Deleted'})


@marketplace_api.route('/listings/guest/<token>/status', methods=['PATCH'])
def set_guest_listing_status(token):
    listing = MarketplaceListing.query.filter_by(guest_manage_token=token).first()
    if not listing:
        return jsonify({'message': 'Listing not found'}), 404
    body = request.get_json(silent=True) or {}
    status = body.get('status')
    if status not in MARKETPLACE_STATUSES:
        return jsonify({'message': f'status must be one of: {", ".join(MARKETPLACE_STATUSES)}'}), 400
    listing.status = status
    if status != 'active':
        listing.expires_at = datetime.utcnow()
    db.session.commit()
    return jsonify(MarketplaceListingSchema().dump(listing))


@marketplace_api.route('/listings/guest/<token>/renew', methods=['POST'])
def renew_guest_listing(token):
    listing = MarketplaceListing.query.filter_by(guest_manage_token=token).first()
    if not listing:
        return jsonify({'message': 'Listing not found'}), 404
    listing.renew()
    db.session.commit()
    return jsonify(MarketplaceListingSchema().dump(listing))


@marketplace_api.route('/admin/listings/pending', methods=['GET'])
@admin_required
def get_pending_listings(_current_user):
    pending = (MarketplaceListing.query.options(*_feed_options())
               .filter_by(approved_to_publish=None)
               .order_by(MarketplaceListing.pub_date.asc()).all())
    return jsonify(MarketplaceListingSchema(many=True).dump(pending))


@marketplace_api.route('/admin/listings/<int:listing_id>/approve', methods=['POST'])
@admin_required
def approve_listing(_current_user, listing_id):
    listing = db.session.get(MarketplaceListing, listing_id)
    if not listing:
        return jsonify({'message': 'Listing not found'}), 404
    body = request.get_json(silent=True) or {}
    approved = not body.get('reject', False)
    listing.approved_to_publish = approved
    db.session.commit()
    return jsonify({'message': 'approved' if approved else 'rejected'})


@marketplace_api.route('/listings/<int:listing_id>', methods=['PATCH'])
@token_required
def edit_listing(current_user, listing_id):
    listing = db.session.get(MarketplaceListing, listing_id)
    if not listing:
        return jsonify({'message': 'Listing not found'}), 404
    if not _can_manage(listing, current_user):
        return jsonify({'message': 'Not authorized'}), 403

    body = request.get_json() or {}
    error, fields = _validate_listing_body(body, partial=True, existing=listing)
    if error:
        return error, 400
    for key, value in fields.items():
        setattr(listing, key, value)

    if 'photos' in body:
        MarketplaceListingPhoto.query.filter_by(listing_id=listing.id).delete()
        db.session.flush()
        for i, filename in enumerate((body.get('photos') or [])[:MAX_PHOTOS]):
            db.session.add(MarketplaceListingPhoto(listing_id=listing.id, filename=filename, position=i))

    db.session.commit()
    return jsonify(MarketplaceListingSchema().dump(listing))


@marketplace_api.route('/listings/<int:listing_id>', methods=['DELETE'])
@token_required
def delete_listing(current_user, listing_id):
    listing = db.session.get(MarketplaceListing, listing_id)
    if not listing:
        return jsonify({'message': 'Listing not found'}), 404
    if not _can_manage(listing, current_user):
        return jsonify({'message': 'Not authorized'}), 403
    db.session.delete(listing)
    db.session.commit()
    return jsonify({'message': 'Deleted'})


@marketplace_api.route('/listings/<int:listing_id>/status', methods=['PATCH'])
@token_required
def set_listing_status(current_user, listing_id):
    listing = db.session.get(MarketplaceListing, listing_id)
    if not listing:
        return jsonify({'message': 'Listing not found'}), 404
    if not _can_manage(listing, current_user):
        return jsonify({'message': 'Not authorized'}), 403
    body = request.get_json(silent=True) or {}
    status = body.get('status')
    if status not in MARKETPLACE_STATUSES:
        return jsonify({'message': f'status must be one of: {", ".join(MARKETPLACE_STATUSES)}'}), 400
    listing.status = status
    if status != 'active':
        listing.expires_at = datetime.utcnow()
    db.session.commit()
    return jsonify(MarketplaceListingSchema().dump(listing))


@marketplace_api.route('/listings/<int:listing_id>/renew', methods=['POST'])
@token_required
def renew_listing(current_user, listing_id):
    listing = db.session.get(MarketplaceListing, listing_id)
    if not listing:
        return jsonify({'message': 'Listing not found'}), 404
    if not _can_manage(listing, current_user):
        return jsonify({'message': 'Not authorized'}), 403
    listing.renew()
    db.session.commit()
    return jsonify(MarketplaceListingSchema().dump(listing))


@marketplace_api.route('/listings/<int:listing_id>/contact-tap', methods=['POST'])
def track_contact_tap(listing_id):
    listing = db.session.get(MarketplaceListing, listing_id)
    if listing:
        listing.contact_taps = (listing.contact_taps or 0) + 1
        db.session.commit()
    return jsonify({'ok': True})


@marketplace_api.route('/listings/<int:listing_id>/save', methods=['POST'])
@token_required
def save_listing(current_user, listing_id):
    listing = db.session.get(MarketplaceListing, listing_id)
    if not listing:
        return jsonify({'message': 'Listing not found'}), 404
    if listing.created_by == current_user.public_id:
        return jsonify({'message': 'You cannot save your own listing'}), 403
    existing = MarketplaceListingLike.query.filter_by(listing_id=listing_id, user_id=current_user.public_id).first()
    if not existing:
        db.session.add(MarketplaceListingLike(listing_id=listing_id, user_id=current_user.public_id))
        db.session.commit()
    return jsonify({'saved': True})


@marketplace_api.route('/listings/<int:listing_id>/save', methods=['DELETE'])
@token_required
def unsave_listing(current_user, listing_id):
    like = MarketplaceListingLike.query.filter_by(listing_id=listing_id, user_id=current_user.public_id).first()
    if like:
        db.session.delete(like)
        db.session.commit()
    return jsonify({'saved': False})


@marketplace_api.route('/listings/<int:listing_id>/save', methods=['PATCH'])
@token_required
def update_saved_listing(current_user, listing_id):
    like = MarketplaceListingLike.query.filter_by(listing_id=listing_id, user_id=current_user.public_id).first()
    if not like:
        return jsonify({'message': 'You have not saved this listing'}), 404
    body = request.get_json(silent=True) or {}
    if 'status' in body:
        if body['status'] not in SAVED_STATUSES:
            return jsonify({'message': f'status must be one of: {", ".join(SAVED_STATUSES)}'}), 400
        like.status = body['status']
    if 'note' in body:
        like.note = (body['note'] or '').strip()[:NOTE_MAX] or None
    db.session.commit()
    return jsonify({'status': like.status, 'note': like.note})


@marketplace_api.route('/my/listings', methods=['GET'])
@token_required
def my_listings(current_user):
    rows = (MarketplaceListing.query.options(*_feed_options())
            .filter_by(created_by=current_user.public_id)
            .order_by(MarketplaceListing.pub_date.desc()).all())
    return jsonify({'listings': MarketplaceListingSchema(many=True).dump(rows)})


@marketplace_api.route('/my/likes', methods=['GET'])
@token_required
def my_liked_listings(current_user):
    rows = (MarketplaceListing.query.options(*_feed_options())
            .join(MarketplaceListingLike, MarketplaceListingLike.listing_id == MarketplaceListing.id)
            .filter(MarketplaceListingLike.user_id == current_user.public_id)
            .order_by(MarketplaceListingLike.created_at.desc()).all())
    likes_by_listing = {
        l.listing_id: l for l in MarketplaceListingLike.query.filter_by(user_id=current_user.public_id).all()
    }
    dumped = MarketplaceListingCardSchema(many=True).dump(rows)
    for d in dumped:
        like = likes_by_listing.get(d['id'])
        d['saved_status'] = like.status if like else 'saved'
        d['saved_note'] = like.note if like else None
    return jsonify({'listings': dumped})


@marketplace_api.route('/upload', methods=['POST'])
@token_required
def marketplace_upload(_current_user):
    """Reuses the shared Supabase upload pipeline -- same as /estates/upload
    and /business/upload."""
    filename = upload_file(request)
    if not filename:
        return jsonify({'message': 'Upload failed'}), 400
    return jsonify(filename)
