"""'Buy before it's built' -- a developer project where a large-enough group
of buyers banding together can get a bulk-purchase discount (common in
Israel's pre-construction/'al haneyar' market, also relevant to US new-build
developments). Joining just records interest + contact note; the organizer
coordinates the actual group/discount off-platform once enough people have
joined (see EstatesGroupBuyMember's docstring on why only the organizer sees
the member list)."""
from flask import Blueprint, jsonify, request
from sqlalchemy.orm import selectinload

from config import db
from security import token_required, token_optional
from upload import upload_file
from backend.estates.modals.estates import (
    EstatesGroupBuy, EstatesGroupBuyPhoto, EstatesGroupBuyMember,
    GROUP_BUY_STAGES, CURRENCIES, MAX_PHOTOS, slugify,
)
from backend.estates.schemas.estates import EstatesGroupBuyCardSchema, make_group_buy_schema

group_buy_api = Blueprint('group_buy_api', __name__, url_prefix='/estates')

PAGE_SIZE = 24
TITLE_MAX = 150
DESCRIPTION_MAX = 4000
NOTE_MAX = 500


def _feed_options():
    return [selectinload(EstatesGroupBuy.photos), selectinload(EstatesGroupBuy.members)]


def _can_manage(group_buy, user):
    if not user:
        return False
    if user.is_boss:
        return True
    return group_buy.created_by == user.public_id


def _unique_slug(title):
    base = slugify(title)
    rows = {row[0] for row in db.session.query(EstatesGroupBuy.slug).filter(EstatesGroupBuy.slug.like(f'{base}%')).all()}
    if base not in rows:
        return base
    n = 2
    while f'{base}-{n}' in rows:
        n += 1
    return f'{base}-{n}'


def _validate_body(body, partial=False, existing=None):
    fields = {}

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

    if 'developer_name' in body:
        fields['developer_name'] = (body.get('developer_name') or '').strip() or None

    if 'stage' in body:
        stage = (body.get('stage') or '').strip().lower()
        if stage and stage not in GROUP_BUY_STAGES:
            return jsonify({'message': f'stage must be one of: {", ".join(GROUP_BUY_STAGES)}'}), None
        fields['stage'] = stage or None

    for key, maxlen in (('address', 300), ('neighborhood', 120), ('city', 120), ('state', 80), ('country', 80)):
        if key in body:
            val = (body.get(key) or '').strip()
            if len(val) > maxlen:
                return jsonify({'message': f'{key} must be {maxlen} characters or fewer'}), None
            fields[key] = val or None

    for key in ('lat', 'lng', 'price_per_unit_estimate'):
        if key in body:
            val = body.get(key)
            if val is not None:
                try:
                    val = float(val)
                except (TypeError, ValueError):
                    return jsonify({'message': f'{key} must be a number'}), None
            fields[key] = val

    if 'currency' in body:
        currency = (body.get('currency') or 'USD').strip().upper()
        if currency not in CURRENCIES:
            return jsonify({'message': f'currency must be one of: {", ".join(CURRENCIES)}'}), None
        fields['currency'] = currency

    for key in ('total_units', 'min_group_size'):
        if key in body:
            val = body.get(key)
            if val is not None:
                try:
                    val = int(val)
                except (TypeError, ValueError):
                    return jsonify({'message': f'{key} must be a whole number'}), None
            fields[key] = val

    if 'expected_completion' in body:
        fields['expected_completion'] = (body.get('expected_completion') or '').strip()[:40] or None

    if 'contact_name' in body:
        fields['contact_name'] = (body.get('contact_name') or '').strip()[:150] or None
    for key in ('contact_email', 'contact_phone', 'contact_whatsapp'):
        if key in body:
            fields[key] = (body.get(key) or '').strip()[:150] or None

    # For a PATCH, a key left out of the body means "unchanged", so fall
    # back to the existing group buy's current value rather than treating
    # it as cleared -- otherwise a PATCH clearing the one contact method it
    # has would silently leave it with none.
    email = fields['contact_email'] if 'contact_email' in fields else (existing.contact_email if existing else None)
    phone = fields['contact_phone'] if 'contact_phone' in fields else (existing.contact_phone if existing else None)
    if not (email or phone):
        return jsonify({'message': 'At least one of contact_email or contact_phone is required'}), None

    return None, fields


@group_buy_api.route('/group-buys/stages', methods=['GET'])
def list_stages():
    return jsonify({'stages': list(GROUP_BUY_STAGES)})


@group_buy_api.route('/group-buys', methods=['GET'])
@token_optional
def list_group_buys(current_user):
    city = (request.args.get('city') or '').strip()
    country = (request.args.get('country') or '').strip()
    q = (request.args.get('q') or '').strip()
    include_closed = request.args.get('include_closed') in ('1', 'true', 'True')
    try:
        page = max(1, int(request.args.get('page', 1)))
    except (TypeError, ValueError):
        page = 1

    query = EstatesGroupBuy.query.options(*_feed_options())
    if not include_closed:
        query = query.filter(EstatesGroupBuy.is_closed.is_(False))
    if city:
        like = f'%{city}%'
        query = query.filter(db.or_(EstatesGroupBuy.city.ilike(like), EstatesGroupBuy.neighborhood.ilike(like)))
    if country:
        query = query.filter(EstatesGroupBuy.country.ilike(f'%{country}%'))
    if q:
        like = f'%{q}%'
        query = query.filter(db.or_(
            EstatesGroupBuy.title.ilike(like), EstatesGroupBuy.description.ilike(like),
            EstatesGroupBuy.city.ilike(like), EstatesGroupBuy.neighborhood.ilike(like)))

    bbox_keys = ('north', 'south', 'east', 'west')
    if all(request.args.get(k) not in (None, '') for k in bbox_keys):
        try:
            north, south, east, west = (float(request.args.get(k)) for k in bbox_keys)
        except ValueError:
            return jsonify({'message': 'north/south/east/west must be numbers'}), 400
        query = query.filter(EstatesGroupBuy.lat.between(south, north), EstatesGroupBuy.lng.between(west, east))

    total = query.count()
    query = query.order_by(EstatesGroupBuy.pub_date.desc())
    rows = query.limit(PAGE_SIZE + 1).offset((page - 1) * PAGE_SIZE).all()
    has_more = len(rows) > PAGE_SIZE
    group_buys = rows[:PAGE_SIZE]

    return jsonify({
        'group_buys': EstatesGroupBuyCardSchema(many=True).dump(group_buys),
        'page': page, 'has_more': has_more, 'total': total,
    })


@group_buy_api.route('/group-buys/<identifier>', methods=['GET'])
@token_optional
def get_group_buy(current_user, identifier):
    query = EstatesGroupBuy.query.options(*_feed_options())
    gb = query.filter_by(id=int(identifier)).first() if identifier.isdigit() else query.filter_by(slug=identifier).first()
    if not gb:
        return jsonify({'message': 'Group buy not found'}), 404
    return jsonify(make_group_buy_schema(current_user).dump(gb))


@group_buy_api.route('/group-buys', methods=['POST'])
@token_required
def create_group_buy(current_user):
    body = request.get_json() or {}
    error, fields = _validate_body(body, partial=False)
    if error:
        return error, 400

    photos = body.get('photos')
    if photos is not None and (not isinstance(photos, list) or len(photos) > MAX_PHOTOS):
        return jsonify({'message': f'photos must be a list of at most {MAX_PHOTOS} filenames'}), 400

    gb = EstatesGroupBuy(slug=_unique_slug(fields['title']), created_by=current_user.public_id, **fields)
    db.session.add(gb)
    db.session.flush()
    for i, filename in enumerate((photos or [])[:MAX_PHOTOS]):
        if filename:
            db.session.add(EstatesGroupBuyPhoto(group_buy_id=gb.id, filename=filename, position=i))
    db.session.commit()
    return jsonify(make_group_buy_schema(current_user).dump(gb)), 201


@group_buy_api.route('/group-buys/<int:group_buy_id>', methods=['PATCH'])
@token_required
def edit_group_buy(current_user, group_buy_id):
    gb = db.session.get(EstatesGroupBuy, group_buy_id)
    if not gb:
        return jsonify({'message': 'Group buy not found'}), 404
    if not _can_manage(gb, current_user):
        return jsonify({'message': 'Not authorized'}), 403

    body = request.get_json() or {}
    error, fields = _validate_body(body, partial=True, existing=gb)
    if error:
        return error, 400
    for key, value in fields.items():
        setattr(gb, key, value)
    if 'is_closed' in body:
        gb.is_closed = bool(body.get('is_closed'))

    if 'photos' in body:
        photos = body.get('photos')
        if photos is not None and (not isinstance(photos, list) or len(photos) > MAX_PHOTOS):
            return jsonify({'message': f'photos must be a list of at most {MAX_PHOTOS} filenames'}), 400
        for photo in list(gb.photos):
            db.session.delete(photo)
        db.session.flush()
        for i, filename in enumerate(photos or []):
            if filename:
                db.session.add(EstatesGroupBuyPhoto(group_buy_id=gb.id, filename=filename, position=i))

    db.session.commit()
    return jsonify(make_group_buy_schema(current_user).dump(gb))


@group_buy_api.route('/group-buys/<int:group_buy_id>', methods=['DELETE'])
@token_required
def delete_group_buy(current_user, group_buy_id):
    gb = db.session.get(EstatesGroupBuy, group_buy_id)
    if not gb:
        return jsonify({'message': 'Group buy not found'}), 404
    if not _can_manage(gb, current_user):
        return jsonify({'message': 'Not authorized'}), 403
    db.session.delete(gb)
    db.session.commit()
    return jsonify({'message': 'Deleted'})


@group_buy_api.route('/group-buys/sitemap-data', methods=['GET'])
def group_buy_sitemap_data():
    """Minimal {slug, updated} rows for every open group buy -- same lean-
    query pattern as estates.py's own sitemap_data()."""
    rows = (db.session.query(EstatesGroupBuy.slug, EstatesGroupBuy.pub_date)
            .filter(EstatesGroupBuy.is_closed.is_(False)).all())
    return jsonify({
        'group_buys': [{'slug': slug, 'updated': pub_date.isoformat() if pub_date else None} for slug, pub_date in rows],
    })


@group_buy_api.route('/group-buys/<int:group_buy_id>/join', methods=['POST'])
@token_required
def join_group_buy(current_user, group_buy_id):
    gb = db.session.get(EstatesGroupBuy, group_buy_id)
    if not gb:
        return jsonify({'message': 'Group buy not found'}), 404
    if gb.is_closed:
        return jsonify({'message': 'This group buy is closed'}), 400
    note = ((request.get_json() or {}).get('note') or '').strip()[:NOTE_MAX]
    existing = EstatesGroupBuyMember.query.filter_by(group_buy_id=group_buy_id, user_id=current_user.public_id).first()
    if existing:
        existing.note = note or existing.note
    else:
        db.session.add(EstatesGroupBuyMember(group_buy_id=group_buy_id, user_id=current_user.public_id, note=note or None))
    db.session.commit()
    return jsonify({'joined': True})


@group_buy_api.route('/group-buys/<int:group_buy_id>/join', methods=['DELETE'])
@token_required
def leave_group_buy(current_user, group_buy_id):
    member = EstatesGroupBuyMember.query.filter_by(group_buy_id=group_buy_id, user_id=current_user.public_id).first()
    if member:
        db.session.delete(member)
        db.session.commit()
    return jsonify({'joined': False})


@group_buy_api.route('/my/group-buys', methods=['GET'])
@token_required
def my_group_buys(current_user):
    created = (EstatesGroupBuy.query.options(*_feed_options())
               .filter_by(created_by=current_user.public_id)
               .order_by(EstatesGroupBuy.pub_date.desc()).all())
    joined = (EstatesGroupBuy.query.options(*_feed_options())
              .join(EstatesGroupBuyMember, EstatesGroupBuyMember.group_buy_id == EstatesGroupBuy.id)
              .filter(EstatesGroupBuyMember.user_id == current_user.public_id)
              .order_by(EstatesGroupBuyMember.created_at.desc()).all())
    return jsonify({
        'created': make_group_buy_schema(current_user, many=True).dump(created),
        'joined': make_group_buy_schema(current_user, many=True).dump(joined),
    })
