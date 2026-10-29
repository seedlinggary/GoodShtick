"""Cross-site global search -- one GET /search?q=... that searches Shtick
posts, Hock posts, Business listings, Estates listings, Tachlis (job board)
posts, and Torah posts in a single call, grouped by site/type.

backend/feed/routes/aggregate.py already merges several of these sources
for the "Discover" recency feed, but its ?q= filter there is a plain
ILIKE substring match -- fine for "does this row happen to contain this
text", which is all a recency feed needs. An actual *search* feature wants
real relevance (term order/frequency-independent matching, multiple terms
ANDed together sensibly), so this module uses Postgres full-text search
instead: `to_tsvector(...) @@ plainto_tsquery(...)` computed at query time
over each model's existing text columns, ranked with `ts_rank`. At this
app's current scale (hundreds, not thousands+, of rows per table) computing
the tsvector on the fly for every search is cheap -- there's no stored/
indexed tsvector column anywhere, which also means this feature needed zero
schema change.

Each source is queried directly via its own ORM model (same reasoning as
aggregate.py: one Flask app, one DB -- no reason to hairpin through another
blueprint's own HTTP route internally). Results come back already grouped
by type rather than merged into one flat list: relevance scores from
`ts_rank` on completely different text (a job post vs. a dvar torah) aren't
comparable to each other, so a single cross-type ranking would be
meaningless -- a grouped results page (rank only WITHIN each group) is the
right shape for an actual multi-site search instead.

Gut News (backend/news/) is deliberately left out -- it's fully built but
still gated behind news/SuperAdminGate.js on the frontend (not launched to
regular users yet), so it shouldn't be reachable via a public search
either."""
from datetime import datetime

from flask import Blueprint, jsonify, request
from sqlalchemy.orm import contains_eager

from config import db
from backend.shtick.modals.shtick import Shtick
from backend.shtick.modals.content import Content
from backend.hock.modals.hock_post import HockPost
from backend.business.modals.business import Business
from backend.estates.modals.estates import EstatesListing
from backend.tachlis.modals.tachlis_post import TachlisPost
from backend.torah.modals.torah import TorahPost

search_api = Blueprint('search_api', __name__, url_prefix='/search')

MIN_QUERY_LEN = 2
PER_TYPE_LIMIT_DEFAULT = 8
PER_TYPE_LIMIT_MAX = 30
SNIPPET_LEN = 160


def _snippet(*parts, length=SNIPPET_LEN):
    """Builds a short result-card excerpt from whichever text fields matter
    most for that type, in priority order. Collapses newlines/repeated
    whitespace (body text often has line breaks) before truncating on a
    word boundary so a card never shows a word chopped in half."""
    text = ' '.join(' '.join((p or '').split()) for p in parts if p)
    if len(text) <= length:
        return text
    return text[:length].rsplit(' ', 1)[0] + '…'


def _tsquery(q):
    """plainto_tsquery, not to_tsquery -- a search box's raw input can carry
    punctuation/quotes/stray operator characters that to_tsquery would
    reject outright with a syntax error (it expects lexeme/operator syntax,
    not free text). plainto_tsquery tokenizes plain text the same way
    to_tsvector does and ANDs the resulting lexemes together, so it never
    throws on arbitrary user input."""
    return db.func.plainto_tsquery('english', q)


def _vector(*cols):
    """to_tsvector over several (possibly NULL) text columns. concat_ws
    (Postgres-specific) silently skips any NULL argument instead of making
    the whole concatenation NULL the way plain `||` would, so a row missing
    one of these columns (e.g. a Shtick with no Content row) still gets a
    vector built from whatever it does have."""
    return db.func.to_tsvector('english', db.func.concat_ws(' ', *cols))


def _match(vector, q):
    return vector.op('@@')(_tsquery(q))


def _rank(vector, q):
    return db.func.ts_rank(vector, _tsquery(q))


def _search_shtick(q, limit):
    """Shtick's own body text lives on a separate one-to-one Content row
    (`content.stuff`), not on Shtick itself -- outerjoin (not an inner
    join) because a URL- or picture-only Shtick has no Content row at all,
    and that must still be searchable by its caption/credit alone.
    contains_eager populates shtick.content from this same join instead of
    a second lazy-load query per row."""
    vector = _vector(Shtick.caption, Shtick.credit, Content.stuff)
    rank_expr = _rank(vector, q).label('rank')
    rows = (Shtick.query
            .outerjoin(Shtick.content)
            .options(contains_eager(Shtick.content))
            .add_columns(rank_expr)
            .filter(Shtick.approved_to_publish.is_(True))
            .filter(_match(vector, q))
            .order_by(rank_expr.desc(), Shtick.pub_date.desc())
            .limit(limit)
            .all())
    items = []
    for shtick, _r in rows:
        body = shtick.content.stuff if shtick.content else ''
        items.append({
            'id': shtick.id,
            'title': shtick.caption or 'Untitled',
            'snippet': _snippet(body, shtick.credit),
            'site_id': 'main',
            'path': f'/post/{shtick.id}',
            'pub_date': shtick.pub_date.isoformat() if shtick.pub_date else None,
        })
    return items


def _search_hock(q, limit):
    vector = _vector(HockPost.title, HockPost.body)
    rank_expr = _rank(vector, q).label('rank')
    rows = (HockPost.query
            .add_columns(rank_expr)
            .filter(HockPost.approved_to_publish.is_(True))
            .filter(_match(vector, q))
            .order_by(rank_expr.desc(), HockPost.pub_date.desc())
            .limit(limit)
            .all())
    return [{
        'id': p.id,
        'title': p.title,
        'snippet': _snippet(p.body),
        'site_id': 'main',
        'path': f'/hock/post/{p.id}',
        'pub_date': p.pub_date.isoformat() if p.pub_date else None,
    } for p, _r in rows]


def _search_business(q, limit):
    """Business has no approval gate at all (every listing -- self-submitted
    or bulk-imported -- is public immediately, see backend/business/routes/
    business.py's list_businesses), so there's no visibility filter to apply
    here beyond the match itself."""
    vector = _vector(Business.name, Business.about)
    rank_expr = _rank(vector, q).label('rank')
    rows = (Business.query
            .add_columns(rank_expr)
            .filter(_match(vector, q))
            .order_by(rank_expr.desc(), Business.pub_date.desc())
            .limit(limit)
            .all())
    return [{
        'id': b.id,
        'title': b.name,
        'snippet': _snippet(b.about),
        'site_id': 'business',
        'path': f'/business/{b.slug}',
        'pub_date': b.pub_date.isoformat() if b.pub_date else None,
    } for b, _r in rows]


def _search_estates(q, limit):
    """No approved_to_publish column on EstatesListing -- `expires_at`
    is the one visibility gate (see EstatesListing.is_expired), and a
    manually-marked 'rented'/'sold' status also sets expires_at to now
    (routes/estates.py's set_listing_status), so filtering on expires_at
    alone already excludes both expired AND rented/sold listings."""
    now = datetime.utcnow()
    vector = _vector(EstatesListing.title, EstatesListing.description,
                      EstatesListing.neighborhood, EstatesListing.city)
    rank_expr = _rank(vector, q).label('rank')
    rows = (EstatesListing.query
            .add_columns(rank_expr)
            .filter(db.or_(EstatesListing.expires_at.is_(None), EstatesListing.expires_at > now))
            .filter(_match(vector, q))
            .order_by(rank_expr.desc(), EstatesListing.pub_date.desc())
            .limit(limit)
            .all())
    items = []
    for listing, _r in rows:
        place = listing.neighborhood or listing.city
        items.append({
            'id': listing.id,
            'title': listing.title,
            'snippet': _snippet(listing.description, place),
            'site_id': 'estates',
            'path': f'/listings/{listing.slug}',
            'pub_date': listing.pub_date.isoformat() if listing.pub_date else None,
        })
    return items


def _search_tachlis(q, limit):
    """Same expires_at/status relationship as Estates (TachlisPost.renew()/
    set_post_status mirror EstatesListing's exactly), plus the moderation
    gate every on-site-submitted post still needs (approved_to_publish)."""
    now = datetime.utcnow()
    vector = _vector(TachlisPost.title, TachlisPost.body,
                      TachlisPost.location, TachlisPost.category)
    rank_expr = _rank(vector, q).label('rank')
    rows = (TachlisPost.query
            .add_columns(rank_expr)
            .filter(TachlisPost.approved_to_publish.is_(True))
            .filter(db.or_(TachlisPost.expires_at.is_(None), TachlisPost.expires_at > now))
            .filter(_match(vector, q))
            .order_by(rank_expr.desc(), TachlisPost.pub_date.desc())
            .limit(limit)
            .all())
    items = []
    for post, _r in rows:
        items.append({
            'id': post.id,
            'title': post.title,
            'snippet': _snippet(post.body, post.location, post.compensation),
            'site_id': 'money',
            'path': f'/tachlis/post/{post.id}',
            'pub_date': post.pub_date.isoformat() if post.pub_date else None,
        })
    return items


def _search_torah(q, limit):
    """No approval gate on TorahPost either (posts auto-publish). Only
    `body_text` carries free text -- a video/photo-only post still has a
    title at minimum, which is enough on its own to be findable."""
    vector = _vector(TorahPost.title, TorahPost.body_text, TorahPost.category)
    rank_expr = _rank(vector, q).label('rank')
    rows = (TorahPost.query
            .add_columns(rank_expr)
            .filter(_match(vector, q))
            .order_by(rank_expr.desc(), TorahPost.pub_date.desc())
            .limit(limit)
            .all())
    return [{
        'id': p.id,
        'title': p.title,
        'snippet': _snippet(p.body_text),
        'site_id': 'torah',
        'path': f'/posts/{p.slug}',
        'pub_date': p.pub_date.isoformat() if p.pub_date else None,
    } for p, _r in rows]


# (type key, display label, owning site id -- see src/sites/registry.js /
# siteMode.js's siteUrl('main', ...) for 'main', fetcher function)
GROUP_DEFS = [
    ('shtick', 'Shtick', 'main', _search_shtick),
    ('hock', 'Hock Forum', 'main', _search_hock),
    ('business', 'Business Directory', 'business', _search_business),
    ('estates', 'Estates Listings', 'estates', _search_estates),
    ('tachlis', 'Job Board', 'money', _search_tachlis),
    ('torah', 'Torah Posts', 'torah', _search_torah),
]
VALID_TYPES = {key for key, *_ in GROUP_DEFS}


@search_api.route('', methods=['GET'])
def search():
    """?q=search-term (required, 2+ chars) & ?limit=1..30 (per type, default
    8) & ?types=shtick,hock,... (default: every type). Returns
    {q, total, groups: [{type, label, site_id, count, items}]} -- every
    registered type is included (even with count 0) so the results page
    doesn't have to special-case a type that just had no matches."""
    q = (request.args.get('q') or '').strip()
    if len(q) < MIN_QUERY_LEN:
        return jsonify({'message': f'Search term must be at least {MIN_QUERY_LEN} characters'}), 400

    try:
        limit = int(request.args.get('limit', PER_TYPE_LIMIT_DEFAULT))
    except (TypeError, ValueError):
        limit = PER_TYPE_LIMIT_DEFAULT
    limit = min(PER_TYPE_LIMIT_MAX, max(1, limit))

    requested = (request.args.get('types') or '').strip()
    wanted = {t for t in requested.split(',') if t} if requested else None
    if wanted:
        unknown = wanted - VALID_TYPES
        if unknown:
            return jsonify({'message': f'Unknown type(s): {", ".join(sorted(unknown))}. '
                                        f'Valid: {", ".join(sorted(VALID_TYPES))}'}), 400

    groups = []
    total = 0
    for type_key, label, site_id, fetcher in GROUP_DEFS:
        if wanted and type_key not in wanted:
            continue
        items = fetcher(q, limit)
        total += len(items)
        groups.append({'type': type_key, 'label': label, 'site_id': site_id,
                        'count': len(items), 'items': items})

    return jsonify({'q': q, 'total': total, 'groups': groups})
