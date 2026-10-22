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
import json
from datetime import datetime, timedelta

import requests
from flask import Blueprint, jsonify, request
from sqlalchemy import text

from config import db

torah_sefaria_api = Blueprint('torah_sefaria_api', __name__, url_prefix='/torah/sefaria')

SEFARIA_BASE = 'https://www.sefaria.org/api'
CACHE_TTL = {
    'index': timedelta(days=14),  # the library's own structure, essentially static
    'book': timedelta(days=7),
    'text': timedelta(days=3),
    'links': timedelta(days=3),
}


def _cached(cache_key, ttl, fetch_fn):
    """Deliberately uses raw `db.engine.connect()`/`.begin()` instead of the
    ORM's `db.session` for both reads and writes here -- NOT a style choice.

    This cache's whole point is surviving a fetch_fn() that can be
    catastrophically slow: Sefaria's own /api/index (behind /toc's cold-cache
    path) confirmed live at 150-400+ SECONDS. `db.session` is a scoped
    session tied to the request's app context; a connection it checks out
    stays checked out -- tied to an open transaction -- for as long as that
    session lives, and manually calling `db.session.remove()` to let go of
    it mid-request turned out NOT to reliably release it in time either
    (confirmed live, repeatedly: the connection still showed up in Postgres
    as "idle in transaction" on this exact SELECT for 20-400+ seconds after
    the code had already moved on, under this app's combination of
    threaded=True, pool_size=1, and Supabase's pgbouncer in front of it --
    exactly the "goes stale mid-transaction" failure config.py's own
    SQLALCHEMY_ENGINE_OPTIONS comment already warns pool_pre_ping can't
    catch). A bare `with db.engine.connect() as conn:` block is a plain
    DBAPI connection checkout with NO ORM session/identity-map machinery at
    all -- it is unambiguously returned to the pool the instant the `with`
    block exits, which is exactly what "don't hold a connection during a
    multi-minute external call" requires. The write side uses Postgres'
    ON CONFLICT upsert for the same reason a plain INSERT-or-UPDATE doesn't
    work here: two concurrent cold-cache requests for the same key (e.g. the
    very first Talmud AND Halakhah click) can both finish fetch_fn() around
    the same time -- ON CONFLICT handles that race atomically in one
    statement instead of needing a separate read-then-write-then-catch step."""
    with db.engine.connect() as conn:
        row = conn.execute(
            text('SELECT payload, fetched_at FROM sefaria_cache WHERE cache_key = :k'),
            {'k': cache_key},
        ).first()
    if row and datetime.utcnow() - row.fetched_at < ttl:
        return row.payload, True, None
    fallback = row.payload if row else None

    try:
        payload = fetch_fn()
    except Exception as e:
        if fallback is not None:
            return fallback, True, None
        return None, False, str(e)

    with db.engine.begin() as conn:
        conn.execute(
            text('''
                INSERT INTO sefaria_cache (cache_key, payload, fetched_at)
                VALUES (:k, CAST(:p AS JSON), :t)
                ON CONFLICT (cache_key) DO UPDATE SET payload = CAST(:p AS JSON), fetched_at = :t
            '''),
            {'k': cache_key, 'p': json.dumps(payload), 't': datetime.utcnow()},
        )
    return payload, False, None


def _slice_to_requested_range(data):
    """Sefaria's /texts/{ref} returns the text for the WHOLE containing
    section whenever a ref addresses something deeper than that section --
    e.g. Genesis.1.1 (one verse) comes back with `he`/`text` holding all 31
    verses of chapter 1, and Rashi on Genesis.1.1.1 (one specific comment)
    comes back with every comment anchored to that verse. `sections`/
    `toSections` say which index range within that array is actually what
    was requested, so slice down to it.

    Only applies when the ref addresses every section level (len(sections)
    == len(sectionNames)) and the deepest level is numeric -- a ref that
    stops short of the deepest level (e.g. plain "Genesis.1", a whole
    chapter) genuinely wants the whole array, and a deepest level that's
    string-valued (Talmud dapim like '2a') is already exactly one daf's
    lines with nothing to slice. Confirmed against live Sefaria responses
    for a single verse, a verse range, a whole chapter, a Talmud daf, a
    specific Rashi comment, and a siddur leaf node -- this rule matched the
    correct behavior in every one of those cases."""
    sections = data.get('sections') or []
    section_names = data.get('sectionNames') or []
    to_sections = data.get('toSections') or []
    if not sections or len(sections) != len(section_names) or not to_sections:
        return data
    start, end = sections[-1], to_sections[-1]
    if not isinstance(start, int) or not isinstance(end, int):
        return data
    for key in ('he', 'text'):
        arr = data.get(key)
        if isinstance(arr, list) and len(arr) >= end:
            data[key] = arr[start - 1:end]
    return data


def fetch_sefaria_text(ref):
    """Shared by GET /text below and the source-sheet routes (which snapshot
    a source's text at the moment it's added to a sheet, rather than storing
    just a bare ref) -- one Sefaria text-fetch implementation, not two."""
    def fetch():
        res = requests.get(f'{SEFARIA_BASE}/texts/{ref}', timeout=15)
        res.raise_for_status()
        data = res.json()
        if data.get('error'):
            raise RuntimeError(data['error'])
        return _slice_to_requested_range(data)

    payload, _cached_flag, error = _cached(f'text:{ref}', CACHE_TTL['text'], fetch)
    if error:
        raise RuntimeError(error)
    return payload


def _walk_toc_path(tree, path_parts):
    """`tree` is the full raw Sefaria index (a list of top-level category
    dicts); `path_parts` is a list of category names to descend through.
    Returns the `contents` list at that point, or None if any part of the
    path doesn't resolve to a real category."""
    nodes = tree
    for part in path_parts:
        found = next((n for n in nodes if n.get('category') == part), None)
        if not found:
            return None
        nodes = found.get('contents', [])
    return nodes


def _trim_toc_entry(n):
    """The raw index carries a lot per entry (compDate, order, corpus,
    long descriptions, ...) that a navigation UI never needs -- trimmed
    here rather than shipping all of it to the browser. A node with
    `category` is a folder to descend into further via /toc?path=...; one
    with `title` is an actual book, fetched via /book then /text same as
    Prayers.js already does for siddurim."""
    if 'category' in n:
        return {'category': n['category'], 'heCategory': n.get('heCategory', '')}
    return {'title': n.get('title'), 'heTitle': n.get('heTitle', ''), 'enShortDesc': n.get('enShortDesc', '')}


@torah_sefaria_api.route('/toc', methods=['GET'])
def get_toc():
    """Browse any point in Sefaria's full library tree -- Talmud ->
    Bavli/Yerushalmi -> Seder -> tractate, or Halakhah -> Mishneh Torah ->
    (one of its 14 books) -> chapter, etc. `path` is a '/'-separated list of
    category names (e.g. 'Talmud/Bavli/Seder Zeraim'); omitted/empty returns
    the top-level categories (Tanakh, Talmud, Halakhah, ...). The full ~4MB
    raw index is fetched from Sefaria and cached whole exactly once (it's
    essentially static) -- every request just re-slices the already-cached
    copy, so no repeated Sefaria calls as users navigate deeper."""
    path = (request.args.get('path') or '').strip()
    path_parts = [p for p in path.split('/') if p]

    def fetch_full():
        # Confirmed live: Sefaria's own /api/index (its full ~4MB raw
        # category tree) regularly takes 150-260+ SECONDS to respond --
        # this isn't a flaky outlier, it's just how slow that one endpoint
        # is. A (connect, read) tuple timeout bounds each individually: a
        # dead/unreachable Sefaria still fails fast via the connect leg,
        # while a merely-very-slow response (the normal case here) gets
        # room to actually finish instead of erroring out before it can.
        res = requests.get(f'{SEFARIA_BASE}/index', timeout=(10, 240))
        res.raise_for_status()
        return res.json()

    full, cached, error = _cached('index_raw', CACHE_TTL['index'], fetch_full)
    if error:
        return jsonify({'message': error}), 502
    nodes = _walk_toc_path(full, path_parts)
    if nodes is None:
        return jsonify({'message': f'Category path not found: {path}'}), 404
    return jsonify({'items': [_trim_toc_entry(n) for n in nodes], 'cached': cached})


@torah_sefaria_api.route('/links', methods=['GET'])
def get_links():
    """Commentaries available on a specific ref (e.g. 'Berakhot.2a') --
    Sefaria doesn't publish a flat "list of all commentaries" anywhere;
    which ones exist is discovered per-page via this links API, same as
    Sefaria's own reader does it. Grouped by commentator (collectiveTitle)
    since one commentator often has several separate comment-refs anchored
    to the same base ref (e.g. multiple Rashi comments on one Gemara line)."""
    ref = (request.args.get('ref') or '').strip()
    if not ref:
        return jsonify({'message': 'ref is required'}), 400

    def fetch():
        res = requests.get(f'{SEFARIA_BASE}/links/{ref}', timeout=20)
        res.raise_for_status()
        data = res.json()
        if isinstance(data, dict) and data.get('error'):
            raise RuntimeError(data['error'])
        by_commentator = {}
        for link in data:
            if link.get('category') != 'Commentary':
                continue
            collective = link.get('collectiveTitle') or {}
            title = collective.get('en') or link.get('index_title')
            if not title:
                continue
            entry = by_commentator.setdefault(title, {'title': title, 'heTitle': collective.get('he', ''), 'refs': []})
            if link.get('ref') and link['ref'] not in entry['refs']:
                entry['refs'].append(link['ref'])
        return sorted(by_commentator.values(), key=lambda c: c['title'])

    payload, cached, error = _cached(f'links:{ref}', CACHE_TTL['links'], fetch)
    if error:
        return jsonify({'message': error}), 502
    return jsonify({'commentaries': payload, 'cached': cached})


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


@torah_sefaria_api.route('/shape', methods=['GET'])
def get_shape():
    """Tells the browser exactly which chapters/dapim/simanim actually exist
    for a ref, via Sefaria's own /api/shape -- this is what makes a real
    clickable chapter list possible instead of a blind free-text box.

    Some books (confirmed live: Tur, which has no top-level Orach Chayim/
    Yoreh De'ah/Even HaEzer/Choshen Mishpat entries in the library index at
    all -- just one bare "Tur" leaf) turn out to be "complex texts" one
    level down: Sefaria's own shape response marks this with
    isComplex=true and a `chapters` array of named sub-sections instead of
    chapter lengths. Returned here as `{type: 'complex', children: [...]}`
    so the frontend can drill one level further (recursively calling this
    same endpoint on a child's title -- confirmed live that Tur's children
    are already simple/leaf, so this never needs to recurse more than once
    in practice, but nothing here assumes that depth is fixed at 1).

    Otherwise it's `{type: 'leaf', items: [{label, ref}, ...]}`, one entry
    per actual chapter/daf that exists (zero-length placeholder slots --
    e.g. index 0/1 for a Talmud tractate, which starts its real content at
    daf 2a -- are dropped). `style=talmud` renders labels as daf+amud
    ("2a", "2b", ...) instead of plain chapter numbers, since Sefaria's
    shape response doesn't itself say which address style a ref uses --
    the frontend already knows (it's the one data point it has that this
    endpoint doesn't), so it's passed in rather than guessed here from the
    ref string."""
    ref = (request.args.get('ref') or '').strip()
    if not ref:
        return jsonify({'message': 'ref is required'}), 400
    style = (request.args.get('style') or '').strip().lower()

    def fetch():
        res = requests.get(f'{SEFARIA_BASE}/shape/{ref}', timeout=20)
        res.raise_for_status()
        data = res.json()
        if not isinstance(data, list) or not data:
            raise RuntimeError('No chapter/section data for this reference')
        return data[0]

    payload, cached, error = _cached(f'shape:{ref}:{style}', CACHE_TTL['book'], fetch)
    if error:
        return jsonify({'message': error}), 502

    if payload.get('isComplex'):
        children = [
            {'title': c.get('title'), 'heTitle': c.get('heTitle', '')}
            for c in (payload.get('chapters') or []) if c.get('title')
        ]
        return jsonify({'type': 'complex', 'children': children, 'cached': cached})

    chapters = payload.get('chapters')
    items = []
    if isinstance(chapters, int):
        # A single-level text (no "chapter" grouping at all -- e.g. "Tur,
        # Orach Chayim, Introduction", which is just a flat list of
        # paragraphs, confirmed live: its shape's `chapters` is the bare
        # int 8, not an array of 8 per-chapter lengths). Every entry here
        # IS the deepest level already, so `count` is always 1 -- there's
        # nothing further to drill into underneath any one of these.
        for i in range(chapters):
            items.append({'label': str(i + 1), 'ref': f'{ref}.{i + 1}', 'count': 1})
    else:
        for i, length in enumerate(chapters or []):
            if not length:
                continue
            if style == 'talmud':
                label = f'{(i // 2) + 1}{"a" if i % 2 == 0 else "b"}'
            else:
                label = str(i + 1)
            # `count` is how many verses/lines/seifim THIS SPECIFIC chapter/
            # daf/siman has (Sefaria's shape already told us this in one
            # call -- no second request needed) -- lets the frontend offer
            # "just one pasuk/line/seif" as a further click, not force the
            # whole chapter/daf/siman every time. Talmud's shape entries
            # are already a LINE count per daf (not a further Talmud-style
            # sub-address), so this next level down is always plain
            # sequential integers regardless of `style` at THIS level.
            items.append({'label': label, 'ref': f'{ref}.{label}', 'count': int(length)})
    return jsonify({'type': 'leaf', 'items': items, 'cached': cached})


@torah_sefaria_api.route('/text', methods=['GET'])
def get_text():
    ref = (request.args.get('ref') or '').strip()
    if not ref:
        return jsonify({'message': 'ref is required'}), 400
    try:
        payload = fetch_sefaria_text(ref)
    except RuntimeError as e:
        return jsonify({'message': str(e)}), 502
    return jsonify(payload)
