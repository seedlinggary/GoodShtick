import random
import re
from datetime import datetime

from flask import Blueprint, jsonify, request, redirect

from config import db, FRONTEND_ORIGINS
from security import token_optional, super_admin_required
from backend.ads.modals.ad import Ad
from backend.ads.modals.ad_impression import AdImpression
from backend.ads.modals.ad_click import AdClick
from backend.ads.schemas.ad import ad_schema, ads_schema, ad_serve_schema
from upload import upload_file

ads_api = Blueprint('ads_api', __name__, url_prefix='/ads')

VALID_STATUSES = {'draft', 'active', 'paused', 'archived'}
VALID_DESTINATION_TYPES = {'url', 'whatsapp', 'phone', 'email', 'internal'}
VALID_PLACEMENTS = {'feed', 'games_hub', 'game_page', 'top', 'bottom', 'sidebar_left', 'sidebar_right'}
VALID_GENDERS = {'male', 'female', 'other'}


def _visitor_country():
    """Vercel injects geo headers at the edge for every request; None outside Vercel (e.g. local dev)."""
    return request.headers.get('x-vercel-ip-country') or None


def _parse_dt(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00')).replace(tzinfo=None)
    except (ValueError, AttributeError):
        return None


def _matches_targeting(ad, age, gender, country):
    """An ad with no targeting set on an axis is eligible for everyone on that axis."""
    if ad.target_age_min is not None or ad.target_age_max is not None:
        if age is None:
            return False
        if ad.target_age_min is not None and age < ad.target_age_min:
            return False
        if ad.target_age_max is not None and age > ad.target_age_max:
            return False
    if ad.target_gender:
        if not gender or gender.lower() != ad.target_gender.lower():
            return False
    if ad.target_countries:
        allowed = {c.strip().lower() for c in ad.target_countries.split(',') if c.strip()}
        if not country or country.lower() not in allowed:
            return False
    return True


def _pick_ad(placement, excluded_ids, now, age, gender, country):
    """Selects one eligible active ad for a placement via weighted random choice,
    or None if nothing qualifies. Shared by /serve and /serve_batch."""
    candidates = Ad.query.filter_by(placement=placement, status='active').all()
    candidates = [
        a for a in candidates
        if a.id not in excluded_ids
        and (a.start_date is None or a.start_date <= now)
        and (a.end_date is None or a.end_date >= now)
    ]
    eligible = [a for a in candidates if _matches_targeting(a, age, gender, country)]
    if not eligible:
        return None
    return random.choices(eligible, weights=[max(1, a.weight or 1) for a in eligible], k=1)[0]


def _log_impression(ad, placement, current_user, country):
    try:
        db.session.add(AdImpression(
            ad_id=ad.id,
            user_id=current_user.public_id if current_user else None,
            placement=placement,
            country=country,
        ))
        ad.impression_count = (ad.impression_count or 0) + 1
    except Exception:
        pass


def _normalize_destination_value(destination_type, value):
    """A bare 'url' destination without a scheme (e.g. 'www.example.com') isn't
    a valid absolute URL — Flask's redirect() treats it as relative to the
    current request path, sending visitors to something like
    /ads/1/www.example.com on our own backend instead of the real site.
    Force a scheme onto plain 'url' values; other destination types build
    their own scheme (tel:/mailto:/wa.me) and don't need this."""
    value = (value or '').strip()
    if destination_type == 'url' and value and not re.match(r'^[a-zA-Z][a-zA-Z0-9+.-]*://', value):
        value = 'https://' + value
    return value


def _build_destination(ad):
    value = _normalize_destination_value(ad.destination_type, ad.destination_value)
    if ad.destination_type == 'whatsapp':
        if value.startswith('http'):
            return value
        digits = ''.join(ch for ch in value if ch.isdigit())
        return f'https://wa.me/{digits}'
    if ad.destination_type == 'phone':
        return f'tel:{value}'
    if ad.destination_type == 'email':
        return f'mailto:{value}'
    if ad.destination_type == 'internal':
        base = FRONTEND_ORIGINS[0] if FRONTEND_ORIGINS else ''
        path = value if value.startswith('/') else '/' + value
        return base + path
    return value  # 'url'


# ── Public: serve + click ────────────────────────────────────────────────

@ads_api.route('/serve', methods=['GET'])
@token_optional
def serve_ad(current_user):
    placement = request.args.get('placement', 'feed')
    if placement not in VALID_PLACEMENTS:
        return jsonify(None), 400

    exclude_raw = request.args.get('exclude', '')
    excluded_ids = {int(x) for x in exclude_raw.split(',') if x.strip().isdigit()}

    now = datetime.utcnow()
    age = current_user.age if current_user else None
    gender = current_user.gender if current_user else None
    country = (current_user.location_country if current_user and current_user.location_country
               else _visitor_country())

    chosen = _pick_ad(placement, excluded_ids, now, age, gender, country)
    if not chosen:
        return jsonify(None)

    _log_impression(chosen, placement, current_user, country)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()

    return jsonify(ad_serve_schema.dump(chosen))


@ads_api.route('/serve_batch', methods=['GET'])
@token_optional
def serve_ads_batch(current_user):
    """Same targeting/serving/impression-logging as /serve, but for several
    placements in one round trip — used by pages with multiple fixed ad slots
    (home page's top/bottom/sidebar banners) so the browser fires one request
    instead of one per slot."""
    placements = [p.strip() for p in request.args.get('placements', '').split(',') if p.strip() in VALID_PLACEMENTS]
    if not placements:
        return jsonify({})

    exclude_raw = request.args.get('exclude', '')
    excluded_ids = {int(x) for x in exclude_raw.split(',') if x.strip().isdigit()}

    now = datetime.utcnow()
    age = current_user.age if current_user else None
    gender = current_user.gender if current_user else None
    country = (current_user.location_country if current_user and current_user.location_country
               else _visitor_country())

    result = {}
    for placement in placements:
        chosen = _pick_ad(placement, excluded_ids, now, age, gender, country)
        if chosen:
            _log_impression(chosen, placement, current_user, country)
        result[placement] = ad_serve_schema.dump(chosen) if chosen else None

    try:
        db.session.commit()
    except Exception:
        db.session.rollback()

    return jsonify(result)


@ads_api.route('/<int:ad_id>/click', methods=['GET'])
@token_optional
def click_ad(current_user, ad_id):
    ad = db.session.get(Ad, ad_id)
    if not ad:
        return redirect('/')

    country = (current_user.location_country if current_user and current_user.location_country
               else _visitor_country())
    try:
        db.session.add(AdClick(
            ad_id=ad.id,
            user_id=current_user.public_id if current_user else None,
            country=country,
        ))
        ad.click_count = (ad.click_count or 0) + 1
        db.session.commit()
    except Exception:
        db.session.rollback()

    return redirect(_build_destination(ad))


# ── Superadmin management ────────────────────────────────────────────────

@ads_api.route('', methods=['GET'])
@super_admin_required
def list_ads(_current_user):
    ads = Ad.query.order_by(Ad.pub_date.desc()).all()
    return jsonify(ads_schema.dump(ads))


@ads_api.route('', methods=['POST'])
@super_admin_required
def create_ad(current_user):
    body = request.get_json() or {}
    if not body.get('name') or not body.get('destination_value'):
        return jsonify({'message': 'name and destination_value are required'}), 400

    destination_type = body.get('destination_type', 'url')
    if destination_type not in VALID_DESTINATION_TYPES:
        return jsonify({'message': f'Invalid destination_type. Must be one of: {", ".join(VALID_DESTINATION_TYPES)}'}), 400
    placement = body.get('placement', 'feed')
    if placement not in VALID_PLACEMENTS:
        return jsonify({'message': f'Invalid placement. Must be one of: {", ".join(VALID_PLACEMENTS)}'}), 400
    target_gender = (body.get('target_gender') or '').lower() or None
    if target_gender and target_gender not in VALID_GENDERS:
        return jsonify({'message': f'Invalid target_gender. Must be one of: {", ".join(VALID_GENDERS)}'}), 400

    ad = Ad(
        name=body['name'],
        advertiser_name=body.get('advertiser_name', ''),
        status='draft',
        image_name=body.get('image_name'),
        headline=body.get('headline', ''),
        body_text=body.get('body_text', ''),
        cta_label=body.get('cta_label') or 'Learn More',
        destination_type=destination_type,
        destination_value=_normalize_destination_value(destination_type, body['destination_value']),
        placement=placement,
        target_age_min=body.get('target_age_min'),
        target_age_max=body.get('target_age_max'),
        target_gender=target_gender,
        target_countries=body.get('target_countries'),
        start_date=_parse_dt(body.get('start_date')),
        end_date=_parse_dt(body.get('end_date')),
        weight=body.get('weight') or 1,
        created_by=current_user.public_id,
    )
    db.session.add(ad)
    db.session.commit()
    return jsonify(ad_schema.dump(ad)), 201


@ads_api.route('/<int:ad_id>', methods=['PUT'])
@super_admin_required
def update_ad(_current_user, ad_id):
    ad = db.session.get(Ad, ad_id)
    if not ad:
        return jsonify({'message': 'Ad not found'}), 404
    body = request.get_json() or {}

    if 'status' in body:
        if body['status'] not in VALID_STATUSES:
            return jsonify({'message': f'Invalid status. Must be one of: {", ".join(VALID_STATUSES)}'}), 400
        ad.status = body['status']
    if 'destination_type' in body:
        if body['destination_type'] not in VALID_DESTINATION_TYPES:
            return jsonify({'message': f'Invalid destination_type. Must be one of: {", ".join(VALID_DESTINATION_TYPES)}'}), 400
        ad.destination_type = body['destination_type']
    if 'placement' in body:
        if body['placement'] not in VALID_PLACEMENTS:
            return jsonify({'message': f'Invalid placement. Must be one of: {", ".join(VALID_PLACEMENTS)}'}), 400
        ad.placement = body['placement']
    if 'target_gender' in body:
        tg = (body['target_gender'] or '').lower() or None
        if tg and tg not in VALID_GENDERS:
            return jsonify({'message': f'Invalid target_gender. Must be one of: {", ".join(VALID_GENDERS)}'}), 400
        ad.target_gender = tg

    for field in ('name', 'advertiser_name', 'image_name', 'headline', 'body_text',
                  'cta_label', 'target_countries'):
        if field in body:
            setattr(ad, field, body[field])
    if 'destination_value' in body:
        ad.destination_value = _normalize_destination_value(ad.destination_type, body['destination_value'])
    for field in ('target_age_min', 'target_age_max', 'weight'):
        if field in body:
            setattr(ad, field, body[field])
    if 'start_date' in body:
        ad.start_date = _parse_dt(body['start_date'])
    if 'end_date' in body:
        ad.end_date = _parse_dt(body['end_date'])

    db.session.commit()
    return jsonify(ad_schema.dump(ad))


@ads_api.route('/<int:ad_id>', methods=['DELETE'])
@super_admin_required
def delete_ad(_current_user, ad_id):
    ad = db.session.get(Ad, ad_id)
    if not ad:
        return jsonify({'message': 'Ad not found'}), 404
    if ad.status != 'draft':
        return jsonify({'message': 'Only draft ads can be deleted — archive live/paused ads instead to keep their stats.'}), 409
    db.session.delete(ad)
    db.session.commit()
    return jsonify({'message': 'deleted'})


@ads_api.route('/<int:ad_id>/image', methods=['POST'])
@super_admin_required
def upload_ad_image(_current_user, ad_id):
    ad = db.session.get(Ad, ad_id)
    if not ad:
        return jsonify({'message': 'Ad not found'}), 404
    filename = upload_file(request)
    if not filename:
        return jsonify({'message': 'Upload failed'}), 400
    ad.image_name = filename
    db.session.commit()
    return jsonify(ad_schema.dump(ad))


@ads_api.route('/<int:ad_id>/stats', methods=['GET'])
@super_admin_required
def ad_stats(_current_user, ad_id):
    ad = db.session.get(Ad, ad_id)
    if not ad:
        return jsonify({'message': 'Ad not found'}), 404
    impressions = AdImpression.query.filter_by(ad_id=ad_id).count()
    clicks = AdClick.query.filter_by(ad_id=ad_id).count()
    ctr = round((clicks / impressions) * 100, 2) if impressions else 0
    return jsonify({
        'ad_id': ad_id,
        'impressions': impressions,
        'clicks': clicks,
        'ctr_percent': ctr,
    })
