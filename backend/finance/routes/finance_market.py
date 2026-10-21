"""Proxies Alpha Vantage so the API key never reaches the browser, and so a
single shared key's free-tier quota (25 requests/day, 5/minute -- shared
across every visitor to the whole site, not per-user) stretches as far as
possible via FinanceDataCache. A request is only ever forwarded to Alpha
Vantage when nothing fresh enough is already cached; every response is read
straight back from the cache afterward, cached entry included, so the
caller's code path is identical either way.

Response field names: Alpha Vantage's own JSON uses awkward "1. symbol",
"2. open"-style numbered keys. _normalize() strips the "N. " prefix so the
frontend gets plain {symbol, open, high, ...} keys -- confirmed against the
live API for GLOBAL_QUOTE/TIME_SERIES_DAILY; SYMBOL_SEARCH's bestMatches
entries are assumed to follow the same numbered-key convention (Alpha
Vantage uses it consistently across endpoints) since the free "demo" key
blocks that endpoint entirely, so it couldn't be directly confirmed here."""
import os
from datetime import datetime, timedelta

import requests
from flask import Blueprint, jsonify, request

from config import db
from backend.finance.modals.finance import FinanceDataCache

finance_market_api = Blueprint('finance_market_api', __name__, url_prefix='/finance')

ALPHA_VANTAGE_URL = 'https://www.alphavantage.co/query'
ALPHA_VANTAGE_KEY = os.environ.get('ALPHA_VANTAGE_API_KEY', 'demo')

CACHE_TTL = {
    'quote': timedelta(minutes=20),
    'chart': timedelta(hours=12),
    'chart_weekly': timedelta(hours=24),
    'search': timedelta(days=7),
    'indicator': timedelta(hours=24),
}

# TIME_SERIES_DAILY's free-tier "compact" size (the only size the free key
# can request -- outputsize=full is a premium-only feature, confirmed live)
# is capped at the latest ~100 trading days, so it only covers roughly the
# last 4-5 months. TIME_SERIES_WEEKLY has no such cap on the free tier and
# always returns its FULL history (confirmed live -- 1,400+ weekly points
# back to 1999 for an established ticker), so it's used for every range a
# user picks longer than that, and for every "look back a year/look at the
# 52-week range" insight below, which daily data alone can't reliably cover.

INDICATOR_FUNCTIONS = {
    'cpi': 'CPI',
    'unemployment': 'UNEMPLOYMENT',
    'federal_funds_rate': 'FEDERAL_FUNDS_RATE',
    'real_gdp': 'REAL_GDP',
}


def _normalize(d):
    """{'1. symbol': 'AAPL', '2. name': 'Apple'} -> {'symbol': 'AAPL', 'name': 'Apple'}"""
    out = {}
    for k, v in d.items():
        key = k.split('. ', 1)[1] if '. ' in k else k
        out[key] = v
    return out


def _cached(cache_key, ttl, fetch_fn):
    """Returns (payload, from_cache_bool, error_or_None). Serves a stale
    cache entry rather than a hard error if Alpha Vantage itself fails or
    the day's quota is already spent -- stale market data is still far more
    useful to show than nothing."""
    row = FinanceDataCache.query.filter_by(cache_key=cache_key).first()
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
        row = FinanceDataCache(cache_key=cache_key, payload=payload)
        db.session.add(row)
    db.session.commit()
    return payload, False, None


def _av_get(params):
    params = {**params, 'apikey': ALPHA_VANTAGE_KEY}
    res = requests.get(ALPHA_VANTAGE_URL, params=params, timeout=10)
    res.raise_for_status()
    data = res.json()
    # A real, successful response from any of these endpoints never includes
    # these three keys -- they're how Alpha Vantage reports a bad symbol, a
    # demo-key restriction, or (most importantly, given the 25/day free
    # quota) a rate-limit notice, all as a 200 OK with a message instead of
    # an HTTP error status.
    for key in ('Error Message', 'Information', 'Note'):
        if key in data:
            raise RuntimeError(data[key])
    return data


@finance_market_api.route('/quote', methods=['GET'])
def get_quote():
    symbol = (request.args.get('symbol') or '').strip().upper()
    if not symbol:
        return jsonify({'message': 'symbol is required'}), 400

    def fetch():
        data = _av_get({'function': 'GLOBAL_QUOTE', 'symbol': symbol})
        quote = data.get('Global Quote') or {}
        if not quote:
            raise RuntimeError('No data returned for this symbol')
        return _normalize(quote)

    payload, cached, error = _cached(f'quote:{symbol}', CACHE_TTL['quote'], fetch)
    if error:
        return jsonify({'message': error}), 502
    return jsonify({'quote': payload, 'cached': cached})


@finance_market_api.route('/chart', methods=['GET'])
def get_chart():
    symbol = (request.args.get('symbol') or '').strip().upper()
    if not symbol:
        return jsonify({'message': 'symbol is required'}), 400
    weekly = (request.args.get('series') or '').strip().lower() == 'weekly'

    def fetch():
        if weekly:
            # No outputsize param here -- TIME_SERIES_WEEKLY has nothing to
            # restrict, it always returns full history.
            data = _av_get({'function': 'TIME_SERIES_WEEKLY', 'symbol': symbol})
            series = data.get('Weekly Time Series')
        else:
            # outputsize is left unset deliberately -- Alpha Vantage already
            # defaults TIME_SERIES_DAILY to "compact" (latest ~100 points)
            # with no param at all, and outputsize=full/compact are both
            # premium-only for this endpoint on the free tier (confirmed
            # live), so there's no way to request more than compact anyway.
            data = _av_get({'function': 'TIME_SERIES_DAILY', 'symbol': symbol})
            series = data.get('Time Series (Daily)')
        if not series:
            raise RuntimeError('No data returned for this symbol')
        points = [
            {'date': date, **_normalize(values)}
            for date, values in series.items()
        ]
        points.sort(key=lambda p: p['date'])
        return points

    cache_key = f'chart_weekly:{symbol}' if weekly else f'chart:{symbol}'
    ttl = CACHE_TTL['chart_weekly'] if weekly else CACHE_TTL['chart']
    payload, cached, error = _cached(cache_key, ttl, fetch)
    if error:
        return jsonify({'message': error}), 502
    return jsonify({'points': payload, 'cached': cached})


@finance_market_api.route('/search', methods=['GET'])
def search_symbols():
    q = (request.args.get('q') or '').strip()
    if not q:
        return jsonify({'message': 'q is required'}), 400

    def fetch():
        data = _av_get({'function': 'SYMBOL_SEARCH', 'keywords': q})
        matches = data.get('bestMatches') or []
        return [_normalize(m) for m in matches]

    payload, cached, error = _cached(f'search:{q.lower()}', CACHE_TTL['search'], fetch)
    if error:
        return jsonify({'message': error}), 502
    return jsonify({'results': payload, 'cached': cached})


@finance_market_api.route('/indicator/<name>', methods=['GET'])
def get_indicator(name):
    function = INDICATOR_FUNCTIONS.get(name)
    if not function:
        return jsonify({'message': f'name must be one of: {", ".join(INDICATOR_FUNCTIONS)}'}), 400

    def fetch():
        # Only CPI actually takes/wants an `interval` param (confirmed live --
        # UNEMPLOYMENT rejects the request outright if it's present, since it
        # has no interval option of its own; REAL_GDP/FEDERAL_FUNDS_RATE
        # weren't reachable to test against the free "demo" key at all, so
        # they're left at their own default interval rather than guessed).
        params = {'function': function}
        if name == 'cpi':
            params['interval'] = 'monthly'
        data = _av_get(params)
        if 'data' not in data:
            raise RuntimeError('No data returned for this indicator')
        return data

    payload, cached, error = _cached(f'indicator:{name}', CACHE_TTL['indicator'], fetch)
    if error:
        return jsonify({'message': error}), 502
    return jsonify({**payload, 'cached': cached})
