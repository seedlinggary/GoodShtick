"""GutKol's ticker -- short admin-written blurbs shown as a scrolling/
rotating strip on every page (see src/news/NewsTicker.js), plus a public
no-time-limit feed of them (src/news/TickerFeed.js) and an admin
management view (src/news/TickerAdmin.js). Reads are public; writes are
@admin_required, same split as news_article.py's own moderation routes.

Three different GET shapes, each feeding a different piece of frontend,
rather than one endpoint with query flags for all of them:
  - /live   -- the homepage widget's feed: ticker items from the last 24h
              PLUS recent article headlines, merged, since the owner wants
              both in the same rotating strip.
  - /all    -- the public "every ticker, ever" page: active ticker items
              only, no time cutoff, paginated.
  - /admin  -- the management page: EVERY ticker item (including retired
              ones), paginated, admin-only.
"""
from datetime import datetime, timedelta

from flask import Blueprint, jsonify, request

from config import db
from security import admin_required
from backend.news.modals.news_ticker import NewsTickerItem, TICKER_TEXT_MAX_WORDS, TICKER_TEXT_MAX_LEN
from backend.news.modals.news import NewsArticle
from backend.news.schemas.news_ticker import NewsTickerItemSchema

news_ticker_api = Blueprint('news_ticker_api', __name__, url_prefix='/news/ticker')

PAGE_SIZE = 30
LIVE_WINDOW_HOURS = 24
# Plenty for a scrolling/rotating strip -- a hard cap so a very busy 24h
# window can't bloat the one response every visitor's browser fetches.
LIVE_MAX_ITEMS = 40


def _word_count(text):
    return len(text.split())


def _validate_text(text):
    """Returns an error message, or None if `text` is valid. Shared by
    create/update so the word/char caps can't drift out of sync between
    the two routes."""
    if not text:
        return 'Text is required'
    if len(text) > TICKER_TEXT_MAX_LEN:
        return f'Text must be {TICKER_TEXT_MAX_LEN} characters or fewer'
    if _word_count(text) > TICKER_TEXT_MAX_WORDS:
        return f'Keep it to {TICKER_TEXT_MAX_WORDS} words or fewer'
    return None


def _paginate(query, page):
    rows = query.limit(PAGE_SIZE + 1).offset((page - 1) * PAGE_SIZE).all()
    has_more = len(rows) > PAGE_SIZE
    return rows[:PAGE_SIZE], has_more


@news_ticker_api.route('/live', methods=['GET'])
def live_ticker():
    """Ticker items (is_active=True) AND publicly-visible articles, both
    from the last LIVE_WINDOW_HOURS, merged into one list sorted newest
    first -- what the homepage's scrolling+rotating widget renders. Each
    entry is tagged `type` so the frontend can show an "Article" label on
    the article ones and tell the two apart for styling."""
    cutoff = datetime.utcnow() - timedelta(hours=LIVE_WINDOW_HOURS)

    ticker_rows = (NewsTickerItem.query
                   .filter(NewsTickerItem.is_active.is_(True), NewsTickerItem.created_at >= cutoff)
                   .order_by(NewsTickerItem.created_at.desc()).all())
    article_rows = (NewsArticle.query
                    .filter(NewsArticle.approved_to_publish.is_(True), NewsArticle.pub_date >= cutoff)
                    .order_by(NewsArticle.pub_date.desc()).all())

    merged = [
        {'id': f'ticker-{t.id}', 'type': 'ticker', 'text': t.text, 'link_url': t.link_url,
         'created_at': t.created_at.isoformat() if t.created_at else None}
        for t in ticker_rows
    ] + [
        {'id': f'article-{a.id}', 'type': 'article', 'text': a.title, 'link_url': f'/articles/{a.slug}',
         'created_at': a.pub_date.isoformat() if a.pub_date else None}
        for a in article_rows
    ]
    merged.sort(key=lambda x: x['created_at'] or '', reverse=True)

    return jsonify({'items': merged[:LIVE_MAX_ITEMS], 'rotate_ms': 5000})


@news_ticker_api.route('/all', methods=['GET'])
def all_ticker():
    """Public, no time cutoff: every active ticker item ever, newest
    first, paginated -- the "scroll through all tickers" page."""
    try:
        page = max(1, int(request.args.get('page', 1)))
    except (TypeError, ValueError):
        page = 1
    query = NewsTickerItem.query.filter_by(is_active=True).order_by(NewsTickerItem.created_at.desc())
    rows, has_more = _paginate(query, page)
    return jsonify({'items': NewsTickerItemSchema(many=True).dump(rows), 'page': page, 'has_more': has_more})


@news_ticker_api.route('/admin', methods=['GET'])
@admin_required
def admin_list_ticker(current_user):
    """Admin-only management listing -- includes retired (is_active=False)
    items, which neither /live nor /all ever show."""
    try:
        page = max(1, int(request.args.get('page', 1)))
    except (TypeError, ValueError):
        page = 1
    query = NewsTickerItem.query.order_by(NewsTickerItem.created_at.desc())
    rows, has_more = _paginate(query, page)
    return jsonify({
        'items': NewsTickerItemSchema(many=True).dump(rows), 'page': page, 'has_more': has_more,
        'max_words': TICKER_TEXT_MAX_WORDS,
    })


@news_ticker_api.route('', methods=['POST'])
@admin_required
def create_ticker_item(current_user):
    body = request.get_json() or {}
    text = (body.get('text') or '').strip()
    error = _validate_text(text)
    if error:
        return jsonify({'message': error}), 400
    link_url = (body.get('link_url') or '').strip() or None

    item = NewsTickerItem(text=text, created_by=current_user.public_id, link_url=link_url, is_active=True)
    db.session.add(item)
    db.session.commit()
    return jsonify(NewsTickerItemSchema().dump(item)), 201


@news_ticker_api.route('/<int:item_id>', methods=['PATCH'])
@admin_required
def update_ticker_item(current_user, item_id):
    item = db.session.get(NewsTickerItem, item_id)
    if not item:
        return jsonify({'message': 'Not found'}), 404
    body = request.get_json() or {}
    if 'text' in body:
        text = (body.get('text') or '').strip()
        error = _validate_text(text)
        if error:
            return jsonify({'message': error}), 400
        item.text = text
    if 'link_url' in body:
        item.link_url = (body.get('link_url') or '').strip() or None
    if 'is_active' in body:
        item.is_active = bool(body.get('is_active'))
    db.session.commit()
    return jsonify(NewsTickerItemSchema().dump(item))


@news_ticker_api.route('/<int:item_id>', methods=['DELETE'])
@admin_required
def delete_ticker_item(current_user, item_id):
    item = db.session.get(NewsTickerItem, item_id)
    if not item:
        return jsonify({'message': 'Not found'}), 404
    db.session.delete(item)
    db.session.commit()
    return jsonify({'message': 'Deleted'})
