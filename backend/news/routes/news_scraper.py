"""Gut News's own scraper -- same approach as content_pipeline/routes/
scraper.py (which feeds Shtick on the main site with Jewish/Israel-interest
sources), reusing its generic, source-agnostic RSS/image helpers directly
rather than re-implementing them, but creating NewsArticle rows instead of
Shtick rows, for genuinely general-interest news sources.

Sources (verified live 2026-10-20): NPR's "Topics: News" RSS and BBC News's
World RSS, both standard RSS 2.0, both explicitly published for syndication/
personal use. Only title + short summary + a link back to the source are
stored -- never the full article body -- so traffic flows back to the
original publisher, same policy as the Shtick scraper.

New articles land with approved_to_publish=None (pending) -- see
NewsArticle's own docstring for why scraped (not self-authored) content
gets a human check before going public, same as the Shtick pipeline."""
import httpx
from flask import Blueprint, jsonify, request

from config import db
from security import super_admin_required
from backend.content_pipeline.routes.scraper import (
    USER_AGENT, _parse_rss_items, _resolve_image,
)
from backend.news.modals.news import NewsArticle, slugify

news_scraper_api = Blueprint('news_scraper_api', __name__, url_prefix='/news/scrape')

DEFAULT_COUNT = 10
MAX_COUNT = 50
DUPLICATE_STREAK_LIMIT = 5
URL_MAX = 500
EXCERPT_MAX = 500

SOURCES = {
    'npr': {
        'feed': 'https://feeds.npr.org/1001/rss.xml',
        'credit': 'NPR',
        'category': 'world',
    },
    'bbc': {
        'feed': 'https://feeds.bbci.co.uk/news/world/rss.xml',
        'credit': 'BBC News',
        'category': 'world',
    },
}


def _unique_slug(title):
    base = slugify(title)
    rows = {row[0] for row in db.session.query(NewsArticle.slug).filter(NewsArticle.slug.like(f'{base}%')).all()}
    if base not in rows:
        return base
    n = 2
    while f'{base}-{n}' in rows:
        n += 1
    return f'{base}-{n}'


@news_scraper_api.route('/<source>', methods=['POST'])
@super_admin_required
def run_scraper(current_user, source):
    if source not in SOURCES:
        return jsonify({'message': f"Unknown source '{source}'. Expected one of: {', '.join(SOURCES)}"}), 400

    body = request.get_json(silent=True) or {}
    try:
        count = int(body.get('count', DEFAULT_COUNT))
    except (TypeError, ValueError):
        count = DEFAULT_COUNT
    count = max(1, min(count, MAX_COUNT))

    cfg = SOURCES[source]

    try:
        with httpx.Client(headers={'User-Agent': USER_AGENT}, timeout=25, follow_redirects=True) as client:
            resp = client.get(cfg['feed'])
            resp.raise_for_status()
            articles = _parse_rss_items(resp.text)

            added = 0
            checked = 0
            duplicate_streak = 0
            stopped_reason = 'no_more_articles'

            for art in articles:
                checked += 1
                link = art['url']
                if len(link) > URL_MAX:
                    continue

                existing = NewsArticle.query.filter_by(source_url=link, imported=True).first()
                if existing is not None:
                    duplicate_streak += 1
                    if duplicate_streak >= DUPLICATE_STREAK_LIMIT:
                        stopped_reason = 'duplicate_limit'
                        break
                    continue
                duplicate_streak = 0

                excerpt = (art.get('summary') or '')[:EXCERPT_MAX]
                article = NewsArticle(
                    slug=_unique_slug(art['title']), title=art['title'][:200],
                    excerpt=excerpt or None, category=cfg['category'],
                    source_url=link, source_name=cfg['credit'],
                    imported=True, approved_to_publish=None,
                )
                db.session.add(article)
                db.session.flush()

                picture_name = _resolve_image(client, art)
                if picture_name:
                    article.image = picture_name

                db.session.commit()
                added += 1
                if added >= count:
                    stopped_reason = 'count_reached'
                    break
    except (httpx.HTTPError, ValueError) as e:
        return jsonify({'source': source, 'message': f'Failed to fetch source feed: {e}'}), 502

    return jsonify({'source': source, 'added': added, 'checked': checked, 'stopped_reason': stopped_reason})
