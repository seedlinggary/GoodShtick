"""Proxies Hebcal's free, no-API-key-required zmanim and Shabbat-times APIs
(hebcal.com/home/developer-apis). Hebcal has no daily quota (only a 90-
requests/10-second burst limit), so this cache exists for latency, not quota
survival like finance_market.py's -- keyed per rounded location + date,
since zmanim for a given place and day are a fixed astronomical calculation
that never changes once computed."""
from datetime import datetime, timedelta, date

import requests
from flask import Blueprint, jsonify, request

from config import db
from backend.torah.modals.torah import SefariaCache

torah_zmanim_api = Blueprint('torah_zmanim_api', __name__, url_prefix='/torah')

CACHE_TTL = timedelta(hours=24)


def _cached(cache_key, fetch_fn):
    row = SefariaCache.query.filter_by(cache_key=cache_key).first()
    if row and datetime.utcnow() - row.fetched_at < CACHE_TTL:
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
        row = SefariaCache(cache_key=cache_key, payload=payload)
        db.session.add(row)
    db.session.commit()
    return payload, False, None


def _parse_latlng():
    try:
        lat = float(request.args.get('lat'))
        lng = float(request.args.get('lng'))
    except (TypeError, ValueError):
        return None, None, (jsonify({'message': 'lat and lng are required numbers'}), 400)
    return lat, lng, None


@torah_zmanim_api.route('/zmanim', methods=['GET'])
def get_zmanim():
    lat, lng, error = _parse_latlng()
    if error:
        return error
    tzid = (request.args.get('tzid') or '').strip()
    day = (request.args.get('date') or date.today().isoformat()).strip()
    # Rounded to ~1.1km -- plenty precise for zmanim (which don't meaningfully
    # change over that distance) and lets nearby visitors share a cache entry.
    key = f'zmanim:{round(lat, 2)}:{round(lng, 2)}:{tzid}:{day}'

    def fetch():
        params = {'cfg': 'json', 'latitude': lat, 'longitude': lng, 'date': day}
        if tzid:
            params['tzid'] = tzid
        res = requests.get('https://www.hebcal.com/zmanim', params=params, timeout=15)
        res.raise_for_status()
        data = res.json()
        if 'error' in data:
            raise RuntimeError(data['error'])
        return data

    payload, cached, err = _cached(key, fetch)
    if err:
        return jsonify({'message': err}), 502
    return jsonify({**payload, 'cached': cached})


@torah_zmanim_api.route('/shabbat-times', methods=['GET'])
def get_shabbat_times():
    """Upcoming candle lighting / havdalah / this week's parasha for a
    location -- Hebcal defaults to the next Shabbat (and a couple of weeks
    around it) when given a location and no explicit range."""
    lat, lng, error = _parse_latlng()
    if error:
        return error
    tzid = (request.args.get('tzid') or '').strip()
    key = f'shabbat:{round(lat, 2)}:{round(lng, 2)}:{tzid}:{date.today().isocalendar()[1]}'

    def fetch():
        params = {'cfg': 'json', 'latitude': lat, 'longitude': lng, 'geo': 'pos', 'm': 50}
        if tzid:
            params['tzid'] = tzid
        res = requests.get('https://www.hebcal.com/shabbat', params=params, timeout=15)
        res.raise_for_status()
        data = res.json()
        if 'error' in data:
            raise RuntimeError(data['error'])
        return data

    payload, cached, err = _cached(key, fetch)
    if err:
        return jsonify({'message': err}), 502
    return jsonify({**payload, 'cached': cached})
