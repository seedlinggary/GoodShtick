"""Proxies the Sefaria API (sefaria.org/developers) -- free, no API key, no
stated hard rate limit -- so the frontend never calls a third-party API
directly (consistent with how finance_market.py proxies Alpha Vantage) and
so the large, essentially-static index/book-schema responses get cached
instead of re-fetched on every page view.

Sefaria's text tree is arbitrarily deep and varies per book (a Tanakh book
is a few levels of chapter/verse; a siddur is Nusach -> Weekday/Shabbat ->
Shacharit/Mincha/Maariv -> named sections, sometimes several named levels
deep before reaching actual text -- e.g. "Siddur Ashkenaz, Weekday,
Shacharit, Amidah, Patriarchs"). Rather than hardcode any one book's shape,
/sefaria/node returns whatever level of the schema the caller asks for
(root index, or a specific book's own nested schema) and lets the frontend
walk it generically: a node with its own `nodes` is a folder to recurse
into, anything else is assumed fetchable as text via its ref."""
from datetime import datetime, timedelta

import requests
from flask import Blueprint, jsonify, request

from config import db
from backend.torah.modals.torah import SefariaCache

torah_sefaria_api = Blueprint('torah_sefaria_api', __name__, url_prefix='/torah/sefaria')

SEFARIA_BASE = 'https://www.sefaria.org/api'
CACHE_TTL = {
    'index': timedelta(days=7),
    'book': timedelta(days=7),
    'text': timedelta(days=3),
}


def _cached(cache_key, ttl, fetch_fn):
    row = SefariaCache.query.filter_by(cache_key=cache_key).first()
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
        row = SefariaCache(cache_key=cache_key, payload=payload)
        db.session.add(row)
    db.session.commit()
    return payload, False, None


@torah_sefaria_api.route('/index', methods=['GET'])
def get_index():
    """The full table of contents, trimmed to the categories relevant here
    (everything under the Sources browser's and Prayers' own entry points) --
    the raw index is large and includes hundreds of commentaries/translations
    this app has no UI for yet."""
    def fetch():
        res = requests.get(f'{SEFARIA_BASE}/index', timeout=15)
        res.raise_for_status()
        return res.json()

    payload, cached, error = _cached('index', CACHE_TTL['index'], fetch)
    if error:
        return jsonify({'message': error}), 502
    return jsonify({'categories': payload, 'cached': cached})


@torah_sefaria_api.route('/book', methods=['GET'])
def get_book_schema():
    title = (request.args.get('title') or '').strip()
    if not title:
        return jsonify({'message': 'title is required'}), 400

    def fetch():
        res = requests.get(f'{SEFARIA_BASE}/v2/index/{title}', timeout=15)
        res.raise_for_status()
        data = res.json()
        if 'error' in data:
            raise RuntimeError(data['error'])
        return data

    payload, cached, error = _cached(f'book:{title}', CACHE_TTL['book'], fetch)
    if error:
        return jsonify({'message': error}), 502
    return jsonify({**payload, 'cached': cached})


@torah_sefaria_api.route('/text', methods=['GET'])
def get_text():
    ref = (request.args.get('ref') or '').strip()
    if not ref:
        return jsonify({'message': 'ref is required'}), 400

    def fetch():
        res = requests.get(f'{SEFARIA_BASE}/texts/{ref}', timeout=15)
        res.raise_for_status()
        data = res.json()
        if data.get('error'):
            raise RuntimeError(data['error'])
        return data

    payload, cached, error = _cached(f'text:{ref}', CACHE_TTL['text'], fetch)
    if error:
        return jsonify({'message': error}), 502
    return jsonify({**payload, 'cached': cached})
