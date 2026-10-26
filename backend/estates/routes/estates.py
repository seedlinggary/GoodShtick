from datetime import datetime

from flask import Blueprint, jsonify, request
from sqlalchemy import func, case
from sqlalchemy.orm import selectinload

from config import db
from security import token_required, token_optional
from upload import upload_file
from backend.estates.modals.estates import (
    EstatesListing, EstatesListingPhoto, EstatesListingLike,
    LISTING_TYPES, EXPIRING_LISTING_TYPES, CURRENCIES, MAX_PHOTOS, slugify,
)
from backend.estates.schemas.estates import (
    EstatesListingCardSchema, make_listing_schema,
)

estates_api = Blueprint('estates_api', __name__, url_prefix='/estates')

PAGE_SIZE = 24
CANDIDATE_CAP = 500
TITLE_MAX = 150
DESCRIPTION_MAX = 4000
ADDRESS_MAX = 300
CONTACT_NAME_MAX = 150
EMAIL_MAX = 150
PHONE_MAX = 40


def _feed_options():
    return [selectinload(EstatesListing.photos), selectinload(EstatesListing.likes)]


def _can_manage(listing, user):
    if not user:
        return False
    if user.is_boss:
        return True
    return listing.created_by == user.public_id


def _unique_slug(title):
    base = slugify(title)
    rows = {row[0] for row in db.session.query(EstatesListing.slug).filter(EstatesListing.slug.like(f'{base}%')).all()}
    if base not in rows:
        return base
    n = 2
    while f'{base}-{n}' in rows:
        n += 1
    return f'{base}-{n}'


def _validate_listing_body(body, partial=False, existing=None):
    """Returns (error_response_or_None, cleaned_fields_dict). `partial` skips
    required-field checks for PATCH, where an omitted key just means "leave
    as-is" (checked by the caller via `'key' in body`)."""
    fields = {}

    if not partial or 'listing_type' in body:
        listing_type = (body.get('listing_type') or '').strip().lower()
        if listing_type not in LISTING_TYPES:
            return jsonify({'message': f'listing_type must be one of: {", ".join(LISTING_TYPES)}'}), None
        fields['listing_type'] = listing_type

    if not partial or 'title' in body:
        title = (body.get('title') or '').strip()
        if not title:
            return jsonify({'message': 'Title is required'}), None
        if len(title) > TITLE_MAX:
            return jsonify({'message': f'Title must be {TITLE_MAX} characters or fewer'}), None
        fields['title'] = title

    if 'description' in body:
        description = (body.get('description') or '').strip()
        if len(description) > DESCRIPTION_MAX:
            return jsonify({'message': f'Description must be {DESCRIPTION_MAX} characters or fewer'}), None
        fields['description'] = description or None

    if 'price' in body:
        price = body.get('price')
        if price is not None:
            try:
                price = float(price)
            except (TypeError, ValueError):
                return jsonify({'message': 'price must be a number'}), None
            if price < 0:
                return jsonify({'message': 'price must not be negative'}), None
        fields['price'] = price

    if 'currency' in body:
        currency = (body.get('currency') or 'USD').strip().upper()
        if currency not in CURRENCIES:
            return jsonify({'message': f'currency must be one of: {", ".join(CURRENCIES)}'}), None
        fields['currency'] = currency

    if 'price_period' in body:
        fields['price_period'] = (body.get('price_period') or '').strip().lower() or None

    for key, maxlen in (('address', ADDRESS_MAX), ('neighborhood', 120), ('city', 120), ('state', 80), ('zip_code', 20), ('country', 80)):
        if key in body:
            val = (body.get(key) or '').strip()
            if len(val) > maxlen:
                return jsonify({'message': f'{key} must be {maxlen} characters or fewer'}), None
            fields[key] = val or None

    for key in ('lat', 'lng', 'bedrooms', 'bathrooms', 'size_value'):
        if key in body:
            val = body.get(key)
            if val is not None:
                try:
                    val = float(val)
                except (TypeError, ValueError):
                    return jsonify({'message': f'{key} must be a number'}), None
            fields[key] = val

    if 'size_unit' in body:
        size_unit = (body.get('size_unit') or 'sqft').strip().lower()
        if size_unit not in ('sqft', 'sqm'):
            return jsonify({'message': 'size_unit must be sqft or sqm'}), None
        fields['size_unit'] = size_unit

    if 'is_agent' in body:
        val = body.get('is_agent')
        fields['is_agent'] = None if val is None else bool(val)

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

    # At least one direct way to reach the poster -- the one hard
    # requirement the user called out explicitly. For a PATCH, a key left
    # out of the body means "unchanged", so fall back to the existing
    # listing's current value rather than treating it as cleared --
    # otherwise a PATCH clearing the one contact method a listing has would
    # silently leave it with none.
    email = fields['contact_email'] if 'contact_email' in fields else (existing.contact_email if existing else None)
    phone = fields['contact_phone'] if 'contact_phone' in fields else (existing.contact_phone if existing else None)
    if not (email or phone):
        return jsonify({'message': 'At least one of contact_email or contact_phone is required'}), None

    if 'attributes' in body:
        attributes = body.get('attributes')
        if attributes is not None and not isinstance(attributes, dict):
            return jsonify({'message': 'attributes must be an object'}), None
        fields['attributes'] = attributes

    return None, fields


def _apply_photos(listing, photo_filenames):
    if photo_filenames is None:
        return None
    if not isinstance(photo_filenames, list) or len(photo_filenames) > MAX_PHOTOS:
        return jsonify({'message': f'photos must be a list of at most {MAX_PHOTOS} filenames'}), 400
    for photo in list(listing.photos):
        db.session.delete(photo)
    db.session.flush()
    for i, filename in enumerate(photo_filenames):
        if filename:
            db.session.add(EstatesListingPhoto(listing_id=listing.id, filename=filename, position=i))
    return None


@estates_api.route('/listing-types', methods=['GET'])
def list_listing_types():
    return jsonify({'listing_types': list(LISTING_TYPES), 'currencies': list(CURRENCIES), 'max_photos': MAX_PHOTOS})


@estates_api.route('/stats', methods=['GET'])
def estates_stats():
    now = datetime.utcnow()
    active = EstatesListing.query.filter(
        db.or_(EstatesListing.expires_at.is_(None), EstatesListing.expires_at > now))
    total = active.count()
    total_cities = (db.session.query(func.count(func.distinct(func.lower(EstatesListing.city))))
                     .filter(EstatesListing.city.isnot(None), EstatesListing.city != '',
                             db.or_(EstatesListing.expires_at.is_(None), EstatesListing.expires_at > now))
                     .scalar() or 0)
    total_countries = (db.session.query(func.count(func.distinct(func.lower(EstatesListing.country))))
                        .filter(EstatesListing.country.isnot(None), EstatesListing.country != '',
                                db.or_(EstatesListing.expires_at.is_(None), EstatesListing.expires_at > now))
                        .scalar() or 0)
    by_type = dict(
        db.session.query(EstatesListing.listing_type, func.count(EstatesListing.id))
        .filter(db.or_(EstatesListing.expires_at.is_(None), EstatesListing.expires_at > now))
        .group_by(EstatesListing.listing_type).all()
    )
    return jsonify({
        'listings': total,
        'cities': total_cities,
        'countries': total_countries,
        'by_type': by_type,
    })


@estates_api.route('/listings', methods=['GET'])
@token_optional
def list_listings(current_user):
    """Public search/map feed. Expired sale/long-term listings are excluded
    by default (see EstatesListing.is_expired) -- pass
    ?include_expired=1&created_by=me (via /my/listings instead, which is the
    only caller that ever needs that) to see them."""
    listing_type = (request.args.get('listing_type') or '').strip().lower()
    city = (request.args.get('city') or '').strip()
    country = (request.args.get('country') or '').strip()
    q = (request.args.get('q') or '').strip()
    agent_only = request.args.get('agent_only') in ('1', 'true', 'True')
    owner_only = request.args.get('owner_only') in ('1', 'true', 'True')
    sort = (request.args.get('sort') or 'random').strip().lower()
    try:
        page = max(1, int(request.args.get('page', 1)))
    except (TypeError, ValueError):
        page = 1
    try:
        min_price = float(request.args.get('min_price')) if request.args.get('min_price') not in (None, '') else None
        max_price = float(request.args.get('max_price')) if request.args.get('max_price') not in (None, '') else None
    except (TypeError, ValueError):
        return jsonify({'message': 'min_price/max_price must be numbers'}), 400

    near_lat = near_lng = None
    if sort == 'distance':
        try:
            near_lat, near_lng = float(request.args.get('lat')), float(request.args.get('lng'))
        except (TypeError, ValueError):
            return jsonify({'message': 'sort=distance requires numeric lat and lng'}), 400

    now = datetime.utcnow()
    query = EstatesListing.query.options(*_feed_options()).filter(
        db.or_(EstatesListing.expires_at.is_(None), EstatesListing.expires_at > now))

    if listing_type:
        if listing_type not in LISTING_TYPES:
            return jsonify({'message': f'listing_type must be one of: {", ".join(LISTING_TYPES)}'}), 400
        query = query.filter(EstatesListing.listing_type == listing_type)
    if city:
        # Matches neighborhood too -- a search for "Givat Hamivtar" should
        # find listings where that's the neighborhood even though the city
        # field says "Yerushalayim", since users searching a city box don't
        # necessarily know (or care) which of the two fields it landed in.
        like = f'%{city}%'
        query = query.filter(db.or_(EstatesListing.city.ilike(like), EstatesListing.neighborhood.ilike(like)))
    if country:
        query = query.filter(EstatesListing.country.ilike(f'%{country}%'))
    if agent_only:
        query = query.filter(EstatesListing.is_agent.is_(True))
    if owner_only:
        query = query.filter(EstatesListing.is_agent.is_(False))
    if min_price is not None:
        query = query.filter(EstatesListing.price.isnot(None), EstatesListing.price >= min_price)
    if max_price is not None:
        query = query.filter(EstatesListing.price.isnot(None), EstatesListing.price <= max_price)
    if q:
        like = f'%{q}%'
        query = query.filter(db.or_(
            EstatesListing.title.ilike(like), EstatesListing.description.ilike(like),
            EstatesListing.city.ilike(like), EstatesListing.neighborhood.ilike(like),
            EstatesListing.address.ilike(like)))

    bbox_keys = ('north', 'south', 'east', 'west')
    if all(request.args.get(k) not in (None, '') for k in bbox_keys):
        try:
            north, south, east, west = (float(request.args.get(k)) for k in bbox_keys)
        except (TypeError, ValueError):
            return jsonify({'message': 'north/south/east/west must be numbers'}), 400
        query = query.filter(EstatesListing.lat.isnot(None), EstatesListing.lng.isnot(None),
                              EstatesListing.lat.between(south, north), EstatesListing.lng.between(west, east))

    total = query.count()

    if sort == 'alpha':
        query = query.order_by(EstatesListing.title.asc())
    elif sort in ('price_asc', 'price_desc'):
        # Raw `price` alone mixes currencies ($/₪) and billing cadence
        # (nightly/weekly/monthly rent, or a one-time sale lump sum) --
        # comparing those numbers directly is meaningless (a ₪5,000/month
        # rental's raw number has nothing to do with a $450,000 sale's).
        # Normalizing currency (-> USD, via a fixed approximate rate -- a
        # live FX rate would need its own fetch+cache infra for more
        # precision than a sort order actually needs) and rental cadence
        # (-> monthly-equivalent) makes "price" comparable within rentals
        # and within sales. A sale (lump sum) vs. a rental (recurring cost)
        # remains an inherently different kind of number no unit
        # conversion can fix -- filtering to one listing type first is
        # still the most meaningful way to sort by price.
        usd_per_ils = 1 / 3.7
        period_multiplier = case(
            (EstatesListing.price_period == 'night', 30),
            (EstatesListing.price_period == 'week', 4.33),
            else_=1,
        )
        currency_multiplier = case(
            (EstatesListing.currency == 'ILS', usd_per_ils),
            else_=1,
        )
        normalized_price = EstatesListing.price * period_multiplier * currency_multiplier
        query = query.order_by(normalized_price.asc().nulls_last() if sort == 'price_asc' else normalized_price.desc().nulls_last())
    elif sort == 'newest':
        query = query.order_by(EstatesListing.pub_date.desc())
    elif sort == 'distance':
        pass  # final ordering happens in Python below
    else:
        query = query.order_by(func.random())

    if sort == 'distance':
        candidates = query.limit(CANDIDATE_CAP).all()
        candidates = [c for c in candidates if c.lat is not None and c.lng is not None]
        candidates.sort(key=lambda c: (c.lat - near_lat) ** 2 + (c.lng - near_lng) ** 2)
        total = len(candidates)
        start = (page - 1) * PAGE_SIZE
        page_rows = candidates[start:start + PAGE_SIZE + 1]
        has_more = len(page_rows) > PAGE_SIZE
        listings = page_rows[:PAGE_SIZE]
    else:
        rows = query.limit(PAGE_SIZE + 1).offset((page - 1) * PAGE_SIZE).all()
        has_more = len(rows) > PAGE_SIZE
        listings = rows[:PAGE_SIZE]

    return jsonify({
        'listings': EstatesListingCardSchema(many=True).dump(listings),
        'page': page, 'has_more': has_more, 'total': total,
    })


@estates_api.route('/listings/<identifier>', methods=['GET'])
@token_optional
def get_listing(current_user, identifier):
    query = EstatesListing.query.options(*_feed_options())
    listing = query.filter_by(id=int(identifier)).first() if identifier.isdigit() else query.filter_by(slug=identifier).first()
    if not listing:
        return jsonify({'message': 'Listing not found'}), 404
    listing.views_count = (listing.views_count or 0) + 1
    db.session.commit()
    return jsonify(make_listing_schema(current_user).dump(listing))


@estates_api.route('/listings/<identifier>/seo', methods=['GET'])
def get_listing_seo(identifier):
    """Same lookup as get_listing, for the SEO meta-injection proxy (see
    good-shtick/api/render.js) -- split out so a search crawler or link
    unfurl hitting every listing page doesn't inflate views_count alongside
    genuine visits."""
    query = EstatesListing.query.options(*_feed_options())
    listing = query.filter_by(id=int(identifier)).first() if identifier.isdigit() else query.filter_by(slug=identifier).first()
    if not listing:
        return jsonify({'message': 'Listing not found'}), 404
    return jsonify(EstatesListingCardSchema().dump(listing))


@estates_api.route('/listings', methods=['POST'])
@token_required
def create_listing(current_user):
    body = request.get_json() or {}
    error, fields = _validate_listing_body(body, partial=False)
    if error:
        return error, 400

    photos = body.get('photos')
    if photos is not None and (not isinstance(photos, list) or len(photos) > MAX_PHOTOS):
        return jsonify({'message': f'photos must be a list of at most {MAX_PHOTOS} filenames'}), 400

    listing = EstatesListing(
        slug=_unique_slug(fields['title']),
        created_by=current_user.public_id,
        **fields,
    )
    db.session.add(listing)
    db.session.flush()

    for i, filename in enumerate((photos or [])[:MAX_PHOTOS]):
        if filename:
            db.session.add(EstatesListingPhoto(listing_id=listing.id, filename=filename, position=i))

    db.session.commit()
    return jsonify(make_listing_schema(current_user).dump(listing)), 201


@estates_api.route('/listings/<int:listing_id>', methods=['PATCH'])
@token_required
def edit_listing(current_user, listing_id):
    listing = db.session.get(EstatesListing, listing_id)
    if not listing:
        return jsonify({'message': 'Listing not found'}), 404
    if not _can_manage(listing, current_user):
        return jsonify({'message': 'Not authorized'}), 403

    body = request.get_json() or {}
    error, fields = _validate_listing_body(body, partial=True, existing=listing)
    if error:
        return error, 400

    type_changing_to = fields.get('listing_type', listing.listing_type)
    for key, value in fields.items():
        setattr(listing, key, value)

    # If the type changed into/out of the expiring set, or the type stayed
    # the same but an already-expiring listing has no expiry yet (shouldn't
    # happen, but defensive), reconcile expires_at rather than leaving it
    # stuck on whatever the listing was created with.
    if 'listing_type' in fields:
        if type_changing_to in EXPIRING_LISTING_TYPES and listing.expires_at is None:
            listing.renew()
        elif type_changing_to not in EXPIRING_LISTING_TYPES:
            listing.expires_at = None

    if 'photos' in body:
        error_resp = _apply_photos(listing, body.get('photos'))
        if error_resp:
            return error_resp

    db.session.commit()
    return jsonify(make_listing_schema(current_user).dump(listing))


@estates_api.route('/listings/<int:listing_id>', methods=['DELETE'])
@token_required
def delete_listing(current_user, listing_id):
    listing = db.session.get(EstatesListing, listing_id)
    if not listing:
        return jsonify({'message': 'Listing not found'}), 404
    if not _can_manage(listing, current_user):
        return jsonify({'message': 'Not authorized'}), 403
    db.session.delete(listing)
    db.session.commit()
    return jsonify({'message': 'Deleted'})


@estates_api.route('/listings/<int:listing_id>/renew', methods=['POST'])
@token_required
def renew_listing(current_user, listing_id):
    """Pushes a sale/long-term listing's expiry another 30 days out -- the
    owner-side lever for keeping a still-available listing visible past its
    first month (see EstatesListing.renew)."""
    listing = db.session.get(EstatesListing, listing_id)
    if not listing:
        return jsonify({'message': 'Listing not found'}), 404
    if not _can_manage(listing, current_user):
        return jsonify({'message': 'Not authorized'}), 403
    if listing.listing_type not in EXPIRING_LISTING_TYPES:
        return jsonify({'message': 'Only sale/long-term listings expire, so there is nothing to renew'}), 400
    listing.renew()
    db.session.commit()
    return jsonify(make_listing_schema(current_user).dump(listing))


@estates_api.route('/listings/<int:listing_id>/like', methods=['POST'])
@token_required
def like_listing(current_user, listing_id):
    listing = db.session.get(EstatesListing, listing_id)
    if not listing:
        return jsonify({'message': 'Listing not found'}), 404
    if listing.created_by == current_user.public_id:
        return jsonify({'message': 'You cannot save your own listing'}), 403
    existing = EstatesListingLike.query.filter_by(listing_id=listing_id, user_id=current_user.public_id).first()
    if not existing:
        db.session.add(EstatesListingLike(listing_id=listing_id, user_id=current_user.public_id))
        db.session.commit()
    return jsonify({'liked': True})


@estates_api.route('/listings/<int:listing_id>/like', methods=['DELETE'])
@token_required
def unlike_listing(current_user, listing_id):
    like = EstatesListingLike.query.filter_by(listing_id=listing_id, user_id=current_user.public_id).first()
    if like:
        db.session.delete(like)
        db.session.commit()
    return jsonify({'liked': False})


@estates_api.route('/my/listings', methods=['GET'])
@token_required
def my_listings(current_user):
    """Everything the current user has posted -- including expired ones, so
    they stay visible for historical reference even once auto-hidden from
    the public feed (and so there's somewhere to hit "renew" from)."""
    rows = (EstatesListing.query.options(*_feed_options())
            .filter_by(created_by=current_user.public_id)
            .order_by(EstatesListing.pub_date.desc()).all())
    return jsonify({'listings': make_listing_schema(current_user, many=True).dump(rows)})


@estates_api.route('/my/likes', methods=['GET'])
@token_required
def my_liked_listings(current_user):
    rows = (EstatesListing.query.options(*_feed_options())
            .join(EstatesListingLike, EstatesListingLike.listing_id == EstatesListing.id)
            .filter(EstatesListingLike.user_id == current_user.public_id)
            .order_by(EstatesListingLike.created_at.desc()).all())
    return jsonify({'listings': make_listing_schema(current_user, many=True).dump(rows)})


@estates_api.route('/sitemap-data', methods=['GET'])
def sitemap_data():
    """Minimal {slug, updated} rows for every non-expired listing -- same
    lean-query pattern as business.py's own sitemap_data()."""
    now = datetime.utcnow()
    rows = (db.session.query(EstatesListing.slug, EstatesListing.pub_date)
            .filter(db.or_(EstatesListing.expires_at.is_(None), EstatesListing.expires_at > now)).all())
    return jsonify({
        'listings': [{'slug': slug, 'updated': pub_date.isoformat() if pub_date else None} for slug, pub_date in rows],
    })


@estates_api.route('/upload', methods=['POST'])
@token_required
def estates_upload(_current_user):
    """Reuses the shared Supabase upload pipeline -- same as /business/upload.
    Called once per photo (up to MAX_PHOTOS) from the listing form."""
    filename = upload_file(request)
    if not filename:
        return jsonify({'message': 'Upload failed'}), 400
    return jsonify(filename)
