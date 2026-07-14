"""News scraper for the SuperAdmin dashboard.

A super-admin triggers a run for one of three news sites; we pull that site's
most-recent articles (title + short summary + link only -- never the full
article body, so traffic flows back to the source), skip anything already
scraped, and drop the new ones into the existing pending-approval queue as
unapproved Shticks.

Data source per site (verified 2026-07-12, israelnationalnews + yeshivaworld
re-verified/switched later the same day):
  * israelnationalnews -- originally used /Rss.aspx ("News Briefs"), but that
    feed's <enclosure> is a static placeholder shared by every item, AND each
    brief's own og:image turned out to *also* fall back to the same generic
    site-logo image (alt="Israel National News") rather than a real photo --
    confirmed by hashing several "different" downloaded images and finding
    them byte-identical. /flashes/ and /news are both empty client-rendered
    SPA shells (Nuxt), so can't be scraped either. The homepage root (/),
    though, IS server-rendered with real distinct per-article thumbnails,
    titles and short summaries baked into the initial HTML
    (<article class="article"> blocks) -- one request gets everything, no
    per-article fetch needed. See _fetch_israelnationalnews.
  * yeshivaworld -- originally used the site's /feed/ (WordPress RSS), but that
    aggregates every post type including live-blog/breaking-news flashes that
    have no featured image and are noisier than the site's actual main story
    stream. Switched to the WordPress REST API (/wp-json/wp/v2/posts?_embed=1),
    which is the same data that drives the homepage's main feed: clean
    most-recent-first title + excerpt + link, restricted to real posts
    (type=post), plus the featured image comes back for free via _embed --
    no extra per-article request needed.
  * dansdeals -- the homepage sits behind Cloudflare and returns HTTP 403 to
    any non-browser client; the public WordPress /feed/ is served normally,
    and its RSS <description> already embeds the featured <img>, so no extra
    per-article request is needed here either.

robots.txt (checked 2026-07-12):
  * israelnationalnews -- the homepage (/) is not disallowed, nor are
    individual /news/<id> article links found on it (only /Controls/,
    /search, /flashes/1*-5*, /News/Section.aspx/N and /section/N -- a
    different path pattern entirely -- are).
  * yeshivaworld -- only /wp-admin/ disallowed. /feed/ and /wp-json/ OK.
  * dansdeals -- generic "User-agent: *" gets "Allow: /" (only /wp-admin/
    blocked). NOTE: dansdeals additionally names and fully disallows several
    AI crawlers (ClaudeBot, GPTBot, CCBot, Amazonbot, Google-Extended, ...).
    Our User-Agent is a distinct, honest "GoodShtickBot" (NOT any of those),
    which falls under the permissive "*" group -- so /feed/ is allowed. The UA
    string must never be changed to impersonate one of the blocked names.
"""
import html
import mimetypes
import os
import re
import tempfile
import uuid

import httpx
from bs4 import BeautifulSoup
from flask import Blueprint, jsonify, request

from config import db
from security import super_admin_required
from backend.shtick.modals.shtick import Shtick
from backend.shtick.modals.content import Content
from backend.shtick.modals.url import Url
from backend.shtick.modals.picture import Picture
from backend.shtick.modals.generalc import Generalc
from backend.content_pipeline.modals.scraped_article import ScrapedArticle
from upload import _get_bucket

scraper_api = Blueprint('scraper_api', __name__, url_prefix='/content-pipeline/scrape')

# Honest bot identity -- do NOT change to impersonate a browser or a named
# crawler that a site's robots.txt blocks (see module docstring re: dansdeals).
USER_AGENT = 'GoodShtickBot/1.0 (+https://thegoodshtick.com; news aggregator bot)'

DEFAULT_COUNT = 10
MAX_COUNT = 50
DUPLICATE_STREAK_LIMIT = 5   # stop once we hit this many already-seen articles in a row
SUMMARY_MAX = 400            # keep summaries short -- drive readers to the source
CAPTION_MAX = 120            # Shtick.caption is String(120)
URL_MAX = 300               # Url.name is String(300)

# ── Per-article image ──────────────────────────────────────────────────────
# dansdeals embeds a real featured-image <img> right in its RSS <description>,
# so that costs zero extra requests. israelnationalnews's RSS <enclosure> is a
# static placeholder shared by every item (verified 2026-07-12 -- not usable),
# and yeshivaworld's feed carries no image at all -- for both, we fetch the
# individual article's og:image meta tag (one extra polite request per article
# that needs it; dansdeals articles never need this fallback).
IMAGE_FETCH_TIMEOUT = 15
MAX_IMAGE_BYTES = 8 * 1024 * 1024  # sanity cap
IMAGE_CONTENT_TYPES = {
    'image/jpeg': 'jpg', 'image/jpg': 'jpg', 'image/png': 'png',
    'image/webp': 'webp', 'image/gif': 'gif',
}
# Category all scraped news is tagged under. Get-or-created once, reused.
NEWS_CATEGORY_NAME = 'News'

# Sources for which robots.txt disallows the path we would hit. Currently empty
# -- every feed path we use is permitted. If a site later disallows its feed,
# add its key here and the route will refuse to run it (see the gate below).
ROBOTS_BLOCKED = set()


def _clean_summary(raw, limit=SUMMARY_MAX):
    """Turn an RSS <description> (which may be HTML, or HTML-escaped inside the
    XML as israelnationalnews does) into a short plain-text summary."""
    if not raw:
        return ''
    text = html.unescape(raw)
    if '<' in text and '>' in text:
        text = BeautifulSoup(text, 'html.parser').get_text(' ', strip=True)
    text = re.sub(r'\s+', ' ', text).strip()
    if len(text) > limit:
        text = text[:limit].rsplit(' ', 1)[0].rstrip() + '…'
    return text


def _extract_description_image(unescaped_desc_html):
    """Pull the first <img src> out of an RSS <description>'s embedded HTML
    (dansdeals inlines its featured image this way -- free, no extra request).
    Returns None if the description has no image."""
    if not unescaped_desc_html or '<img' not in unescaped_desc_html:
        return None
    img = BeautifulSoup(unescaped_desc_html, 'html.parser').find('img')
    src = img.get('src') if img else None
    return src.strip() if src else None


def _parse_rss_items(text):
    """Shared RSS/XML walk -> [{title, url, summary, image_url}] in feed
    (most-recent-first) order. All three sources currently expose standard
    RSS, so the three per-site parsers below delegate here; each stays a
    separate seam so a site that changes format can get its own bespoke logic
    without touching the others. `image_url` is only populated here when the
    site embeds a real image directly in the description (dansdeals); other
    sources fall back to an og:image lookup in run_scraper."""
    soup = BeautifulSoup(text, 'xml')
    items = []
    for it in soup.find_all('item'):
        title_el = it.find('title')
        link_el = it.find('link')
        desc_el = it.find('description')
        title = title_el.get_text(strip=True) if title_el else ''
        link = link_el.get_text(strip=True) if link_el else ''
        if not title or not link:
            continue
        raw_desc = desc_el.get_text() if desc_el else ''
        unescaped_desc = html.unescape(raw_desc)
        items.append({
            'title': title,
            'url': link,
            'summary': _clean_summary(raw_desc),
            'image_url': _extract_description_image(unescaped_desc),
        })
    return items


def _parse_dansdeals(html_text):
    """dansdeals.com /feed/ (WordPress RSS)."""
    return _parse_rss_items(html_text)


ISRAELNATIONALNEWS_HOME_URL = 'https://www.israelnationalnews.com/'


def _fetch_israelnationalnews(client, count):
    """israelnationalnews.com's own homepage. Switched away from Rss.aspx
    (verified 2026-07-12): that "News Briefs" feed's <enclosure> is a static
    placeholder shared by every item, and even each brief's own og:image
    falls back to the same generic site-logo image (alt="Israel National
    News") rather than a real photo -- confirmed by hashing several
    downloaded "different" images and finding them byte-identical. /flashes/
    and /news are both empty client-rendered SPA shells, so can't be scraped
    either. The homepage root, though, IS server-rendered with real distinct
    per-article thumbnails, titles and short summaries baked into the initial
    HTML (<article class="article"> blocks) -- one request gets everything,
    no per-article fetch needed. Not disallowed by robots.txt (only
    /News/Section.aspx/N and /section/N are blocked, a different path)."""
    resp = client.get(ISRAELNATIONALNEWS_HOME_URL)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, 'html.parser')

    items = []
    for art in soup.find_all('article', class_='article'):
        content_a = art.find('a', class_='article-content')
        img_a = art.find('a', class_='article-img')
        title_el = art.find('h2', class_='article-content--title')
        summary_el = art.find('p', class_='article-content--short')
        img = img_a.find('img') if img_a else None

        href = content_a.get('href') if content_a else None
        title = title_el.get_text(strip=True) if title_el else ''
        if not href or not title:
            continue

        link = href if href.startswith('http') else f'https://www.israelnationalnews.com{href}'
        summary = _clean_summary(summary_el.get_text(strip=True) if summary_el else '')
        image_url = (img.get('src') or '').strip() if img else None

        items.append({'title': title, 'url': link, 'summary': summary, 'image_url': image_url or None})
    return items


YESHIVAWORLD_WPJSON_URL = 'https://www.theyeshivaworld.com/wp-json/wp/v2/posts'


def _fetch_yeshivaworld(client, count):
    """theyeshivaworld.com's own WordPress REST API -- the same data that
    drives the site's main/homepage feed, restricted to real posts (not
    live-blog/breaking-news flashes), most-recent-first, with the featured
    image included via _embed (no extra per-article request needed)."""
    per_page = min(max(count + DUPLICATE_STREAK_LIMIT + 5, 20), 100)
    resp = client.get(YESHIVAWORLD_WPJSON_URL, params={'per_page': per_page, '_embed': 1})
    resp.raise_for_status()
    posts = resp.json()

    items = []
    for p in posts:
        title = html.unescape(BeautifulSoup(p.get('title', {}).get('rendered', ''), 'html.parser').get_text())
        link = p.get('link', '')
        if not title or not link:
            continue
        summary = _clean_summary(p.get('excerpt', {}).get('rendered', ''))
        media = (p.get('_embedded', {}) or {}).get('wp:featuredmedia') or []
        image_url = media[0].get('source_url') if media else None
        items.append({'title': title, 'url': link, 'summary': summary, 'image_url': image_url})
    return items


# source key -> config. Sources with `feed` + `parser` are RSS (see module
# docstring); israelnationalnews and yeshivaworld instead have `fetch(client,
# count)` since they're scraped/REST, not RSS, and paginate by count rather
# than returning a fixed-size feed. `og_image_fallback`: True for sources
# whose data carries no usable image, so run_scraper fetches the individual
# article page's og:image instead -- none currently need this (all three
# embed a real image directly), it's kept as a safety net.
SOURCES = {
    'israelnationalnews': {
        'fetch': _fetch_israelnationalnews,
        'credit': 'Israel National News',
        'og_image_fallback': False,  # real image comes straight off the homepage
    },
    'yeshivaworld': {
        'fetch': _fetch_yeshivaworld,
        'credit': 'The Yeshiva World',
        'og_image_fallback': False,  # featured image comes back with the post itself
    },
    'dansdeals': {
        'feed': 'https://www.dansdeals.com/feed/',
        'parser': _parse_dansdeals,
        'credit': 'DansDeals',
        'og_image_fallback': False,  # already gets a real image from the RSS description
    },
}


def _extract_og_image(html_text):
    tag = BeautifulSoup(html_text, 'html.parser').find('meta', property='og:image')
    content = tag.get('content') if tag else None
    return content.strip() if content else None


def _fetch_og_image(client, article_url):
    """Fetch an article page and pull its og:image. Returns None on any
    failure -- a missing image must never block the post itself."""
    try:
        resp = client.get(article_url)
        resp.raise_for_status()
    except httpx.HTTPError:
        return None
    return _extract_og_image(resp.text)


def _download_and_store_image(client, image_url):
    """Download an image from an external URL and upload it to Supabase
    Storage (mirrors ai_content.py's _generate_image_filename, but the bytes
    come from a GET instead of DALL-E). Returns the stored filename, or None
    on any failure -- an image is a nice-to-have and must never sink the post."""
    if not image_url:
        return None
    try:
        resp = client.get(image_url, timeout=IMAGE_FETCH_TIMEOUT)
        resp.raise_for_status()
    except httpx.HTTPError:
        return None

    content_type = resp.headers.get('content-type', '').split(';')[0].strip().lower()
    ext = IMAGE_CONTENT_TYPES.get(content_type)
    if not ext:
        guessed, _ = mimetypes.guess_type(image_url)
        ext = IMAGE_CONTENT_TYPES.get(guessed or '')
    if not ext:
        return None  # not a recognizable image type -- skip rather than upload garbage

    data = resp.content
    if not data or len(data) > MAX_IMAGE_BYTES:
        return None

    fname = f'{uuid.uuid4()}.{ext}'
    fd, tmp_path = tempfile.mkstemp(suffix=f'.{ext}')
    try:
        with os.fdopen(fd, 'wb') as fh:
            fh.write(data)
        _get_bucket().upload(fname, tmp_path, {'content-type': content_type or f'image/{ext}'})
    except Exception:  # noqa: BLE001 -- image upload is optional, never sink the post
        return None
    finally:
        os.remove(tmp_path)
    return fname


def _resolve_image(client, source, art):
    """Figure out the best image URL for one article, then download+store it.
    Returns a Picture-ready filename, or None. All three sources embed a real
    image directly now, so the og:image fallback fetch is just a safety net
    for the rare item that's missing one."""
    image_url = art.get('image_url')
    cfg = SOURCES[source]
    if not image_url and cfg.get('og_image_fallback'):
        image_url = _fetch_og_image(client, art['url'])
    return _download_and_store_image(client, image_url)


def _get_news_category():
    """Get-or-create the single shared 'News' Generalc category."""
    cat = Generalc.query.filter_by(name=NEWS_CATEGORY_NAME).first()
    if cat is None:
        cat = Generalc(name=NEWS_CATEGORY_NAME)
        db.session.add(cat)
        db.session.commit()
    return cat


def _truncate_caption(title):
    if len(title) <= CAPTION_MAX:
        return title
    return title[:CAPTION_MAX - 3].rstrip() + '...'


@scraper_api.route('/<source>', methods=['POST'])
@super_admin_required
def run_scraper(current_user, source):
    if source not in SOURCES:
        return jsonify({
            'message': f"Unknown source '{source}'. "
                       f"Expected one of: {', '.join(SOURCES)}"
        }), 400

    # Robots gate -- refuse rather than crawl a path a site disallows.
    if source in ROBOTS_BLOCKED:
        return jsonify({
            'source': source,
            'message': 'This source is disallowed by robots.txt; scraper is gated off.'
        }), 403

    body = request.get_json(silent=True) or {}
    try:
        count = int(body.get('count', DEFAULT_COUNT))
    except (TypeError, ValueError):
        count = DEFAULT_COUNT
    count = max(1, min(count, MAX_COUNT))

    cfg = SOURCES[source]

    # One request to list articles (RSS feed, or the wp-json endpoint for
    # yeshivaworld); the client stays open afterward since sources with
    # og_image_fallback need it again per-article for an image.
    try:
        with httpx.Client(headers={'User-Agent': USER_AGENT},
                          timeout=25, follow_redirects=True) as client:
            if 'fetch' in cfg:
                articles = cfg['fetch'](client, count)
            else:
                resp = client.get(cfg['feed'])
                resp.raise_for_status()
                articles = cfg['parser'](resp.text)

            news_cat = _get_news_category()

            added = 0
            checked = 0
            duplicate_streak = 0
            stopped_reason = 'no_more_articles'

            for art in articles:
                checked += 1
                link = art['url']

                # Url.name is String(300); a truncated link would be broken, so skip
                # the (very rare) over-long one rather than store garbage.
                if len(link) > URL_MAX:
                    continue

                existing = ScrapedArticle.query.filter_by(source=source, url=link).first()
                if existing is not None:
                    duplicate_streak += 1
                    if duplicate_streak >= DUPLICATE_STREAK_LIMIT:
                        stopped_reason = 'duplicate_limit'
                        break
                    continue

                duplicate_streak = 0

                shtick = Shtick(
                    caption=_truncate_caption(art['title']),
                    credit=cfg['credit'],
                    specific_category=NEWS_CATEGORY_NAME,
                    user_id=current_user.public_id,
                    generalc_id=news_cat.id,
                )
                # approved_to_publish left at its default (None) -> lands in the
                # pending-approval queue.
                db.session.add(shtick)
                db.session.flush()  # assign shtick.id

                if news_cat not in shtick.categories:
                    shtick.categories.append(news_cat)

                if art['summary']:
                    db.session.add(Content(stuff=art['summary'], shtick_id=shtick.id))
                db.session.add(Url(name=link, shtick_id=shtick.id))
                db.session.add(ScrapedArticle(
                    source=source, url=link, title=art['title'][:300], shtick_id=shtick.id
                ))

                picture_name = _resolve_image(client, source, art)
                if picture_name:
                    db.session.add(Picture(name=picture_name, shtick_id=shtick.id))

                db.session.commit()

                added += 1
                if added >= count:
                    stopped_reason = 'count_reached'
                    break
    except (httpx.HTTPError, ValueError) as e:
        # ValueError covers resp.json() failing on a malformed wp-json response.
        return jsonify({
            'source': source,
            'message': f'Failed to fetch source feed: {e}'
        }), 502

    return jsonify({
        'source': source,
        'added': added,
        'checked': checked,
        'stopped_reason': stopped_reason,
    })
