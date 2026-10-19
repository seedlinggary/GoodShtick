"""Minyan times for a shul. The one hard rule: a minyan is never saved
without a source (see _validate_minyan) -- a URL is preferred but not every
shul publishes one online, so a short source description ("called the shul
office 3/2026", "posted sign in shul") is accepted too. Every read path that
returns minyan data pairs it with a disclaimer to confirm with the shul
directly, since times shift with the season/the sun and shuls change them
without us finding out."""
from datetime import datetime, time as dtime

from flask import Blueprint, jsonify, request

from config import db
from security import token_required, token_optional
from backend.business.modals.business import Business
from backend.business.modals.minyan import Minyan, TEFILAH_TYPES, RELATIVE_ANCHORS
from backend.business.schemas.community import MinyanSchema

minyan_api = Blueprint('minyan_api', __name__, url_prefix='/business')

DISCLAIMER = ('Minyan times can change with the season, the day of the week, or at the '
              'shul’s discretion. Please confirm with the shul or its website before relying on these times.')

LABEL_MAX, DAYS_MAX, SEASON_MAX, NOTES_MAX = 150, 100, 60, 300
SOURCE_NAME_MAX, SOURCE_URL_MAX = 200, 500


def _can_manage(business, user):
    if not user:
        return False
    if user.is_boss:
        return True
    if business.owner_user_id:
        return business.owner_user_id == user.public_id
    return business.created_by == user.public_id


def _validate_minyan(body):
    """Returns (error_response_or_None, cleaned_fields)."""
    tefilah = (body.get('tefilah') or '').strip().lower()
    if tefilah not in TEFILAH_TYPES:
        return jsonify({'message': f'tefilah must be one of: {", ".join(TEFILAH_TYPES)}'}), None

    source_name = (body.get('source_name') or '').strip()
    if not source_name:
        return jsonify({'message': 'A source is required -- where did this time come from? '
                                    '(the shul’s website, a call to the office, a sign posted in shul, ...)'}), None
    if len(source_name) > SOURCE_NAME_MAX:
        return jsonify({'message': f'Source must be {SOURCE_NAME_MAX} characters or fewer'}), None
    source_url = (body.get('source_url') or '').strip()
    if len(source_url) > SOURCE_URL_MAX:
        return jsonify({'message': f'Source URL must be {SOURCE_URL_MAX} characters or fewer'}), None

    fixed_time_raw = (body.get('fixed_time') or '').strip()
    relative_anchor = (body.get('relative_anchor') or '').strip().lower()
    relative_offset = body.get('relative_offset_minutes')

    fixed_time = None
    if fixed_time_raw:
        try:
            hh, mm = fixed_time_raw.split(':')
            fixed_time = dtime(int(hh), int(mm))
        except (ValueError, TypeError):
            return jsonify({'message': 'fixed_time must be "HH:MM" (24-hour)'}), None
    elif relative_anchor:
        if relative_anchor not in RELATIVE_ANCHORS:
            return jsonify({'message': f'relative_anchor must be one of: {", ".join(RELATIVE_ANCHORS)}'}), None
        try:
            relative_offset = int(relative_offset) if relative_offset not in (None, '') else 0
        except (TypeError, ValueError):
            return jsonify({'message': 'relative_offset_minutes must be a whole number'}), None
    else:
        return jsonify({'message': 'Give either a fixed_time (HH:MM) or a relative_anchor '
                                    '(e.g. shkiya) with relative_offset_minutes'}), None

    for key, maxlen in (('label', LABEL_MAX), ('days', DAYS_MAX), ('season', SEASON_MAX), ('notes', NOTES_MAX)):
        val = (body.get(key) or '').strip()
        if len(val) > maxlen:
            return jsonify({'message': f'{key} must be {maxlen} characters or fewer'}), None

    return None, {
        'tefilah': tefilah,
        'label': (body.get('label') or '').strip() or None,
        'days': (body.get('days') or '').strip() or None,
        'season': (body.get('season') or '').strip() or None,
        'fixed_time': fixed_time,
        'relative_anchor': relative_anchor or None if not fixed_time else None,
        'relative_offset_minutes': relative_offset if not fixed_time else None,
        'notes': (body.get('notes') or '').strip() or None,
        'source_name': source_name,
        'source_url': source_url or None,
    }


@minyan_api.route('/businesses/<int:business_id>/minyanim', methods=['GET'])
def list_minyanim(business_id):
    business = db.session.get(Business, business_id)
    if not business:
        return jsonify({'message': 'Business not found'}), 404
    rows = Minyan.query.filter_by(business_id=business_id).order_by(Minyan.tefilah, Minyan.fixed_time).all()
    return jsonify({'results': MinyanSchema(many=True).dump(rows), 'disclaimer': DISCLAIMER})


@minyan_api.route('/businesses/<int:business_id>/minyanim', methods=['POST'])
@token_required
def add_minyan(current_user, business_id):
    business = db.session.get(Business, business_id)
    if not business:
        return jsonify({'message': 'Business not found'}), 404
    if not _can_manage(business, current_user):
        return jsonify({'message': 'Not authorized'}), 403

    error, fields = _validate_minyan(request.get_json() or {})
    if error:
        return error, 400

    minyan = Minyan(business_id=business_id, created_by=current_user.public_id, **fields)
    db.session.add(minyan)
    db.session.commit()
    return jsonify(MinyanSchema().dump(minyan)), 201


@minyan_api.route('/minyanim/<int:minyan_id>', methods=['PATCH'])
@token_required
def edit_minyan(current_user, minyan_id):
    minyan = db.session.get(Minyan, minyan_id)
    if not minyan:
        return jsonify({'message': 'Minyan not found'}), 404
    if not _can_manage(minyan.business, current_user):
        return jsonify({'message': 'Not authorized'}), 403

    body = request.get_json() or {}
    merged = {
        'tefilah': body.get('tefilah', minyan.tefilah),
        'label': body.get('label', minyan.label),
        'days': body.get('days', minyan.days),
        'season': body.get('season', minyan.season),
        'fixed_time': body.get('fixed_time', minyan.fixed_time.strftime('%H:%M') if minyan.fixed_time else None),
        'relative_anchor': body.get('relative_anchor', minyan.relative_anchor),
        'relative_offset_minutes': body.get('relative_offset_minutes', minyan.relative_offset_minutes),
        'notes': body.get('notes', minyan.notes),
        'source_name': body.get('source_name', minyan.source_name),
        'source_url': body.get('source_url', minyan.source_url),
    }
    error, fields = _validate_minyan(merged)
    if error:
        return error, 400

    for key, value in fields.items():
        setattr(minyan, key, value)
    minyan.updated_at = datetime.utcnow()
    db.session.commit()
    return jsonify(MinyanSchema().dump(minyan))


@minyan_api.route('/minyanim/<int:minyan_id>', methods=['DELETE'])
@token_required
def delete_minyan(current_user, minyan_id):
    minyan = db.session.get(Minyan, minyan_id)
    if not minyan:
        return jsonify({'message': 'Minyan not found'}), 404
    if not _can_manage(minyan.business, current_user):
        return jsonify({'message': 'Not authorized'}), 403
    db.session.delete(minyan)
    db.session.commit()
    return jsonify({'message': 'Minyan deleted'})


@minyan_api.route('/minyanim/search', methods=['GET'])
@token_optional
def search_minyanim(current_user):
    """'Find all minyan times' -- across every shul, not just one. Filter by
    city and/or tefilah type; free-text q matches the shul's own name."""
    from backend.business.modals.business import BusinessLocation

    city = (request.args.get('city') or '').strip()
    tefilah = (request.args.get('tefilah') or '').strip().lower()
    q = (request.args.get('q') or '').strip()
    try:
        page = max(1, int(request.args.get('page', 1)))
    except (TypeError, ValueError):
        page = 1
    per_page = 50

    query = (Minyan.query
        .join(Business, Business.id == Minyan.business_id)
        .filter(Business.category == 'shul'))
    if city:
        loc_ids = db.session.query(BusinessLocation.business_id).filter(BusinessLocation.city.ilike(f'%{city}%'))
        query = query.filter(Business.id.in_(loc_ids))
    if tefilah:
        if tefilah not in TEFILAH_TYPES:
            return jsonify({'message': f'tefilah must be one of: {", ".join(TEFILAH_TYPES)}'}), 400
        query = query.filter(Minyan.tefilah == tefilah)
    if q:
        query = query.filter(Business.name.ilike(f'%{q}%'))

    total = query.count()
    rows = (query.order_by(Business.name, Minyan.tefilah, Minyan.fixed_time)
            .offset((page - 1) * per_page).limit(per_page).all())

    results = []
    for m in rows:
        loc = next((l for l in m.business.locations if l.is_primary), None)
        row = MinyanSchema().dump(m)
        row['business_name'] = m.business.name
        row['business_slug'] = m.business.slug
        row['city'] = loc.city if loc else None
        row['state'] = loc.state if loc else None
        results.append(row)

    return jsonify({
        'results': results, 'total': total, 'page': page, 'per_page': per_page,
        'has_more': page * per_page < total, 'disclaimer': DISCLAIMER,
    })
