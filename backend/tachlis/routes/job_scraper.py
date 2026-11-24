"""Daily job-board auto-import for Gut Money's Tachlis job board.

Four free sources, mirroring backend/content_pipeline/routes/scraper.py's
shape (one blueprint, a SOURCES config, a shared dedup-and-create loop with
a duplicate-streak early-stop) -- see that file's own docstring for the
house conventions this follows. Live-verified 2026-11-24:

  * arbeitnow (arbeitnow.com/api/job-board-api) -- free, keyless JSON.
    Has its own `remote` boolean; kept when remote, or when its free-text
    `location` mentions Israel.
  * remoteok (remoteok.com/api) -- free, keyless JSON array (index 0 is a
    legal/attribution notice, not a job). Every posting is remote by
    definition. Their terms require a visible credit + the apply link
    pointing at their own page -- both satisfied by using their `url` as
    `contact` and a trailing credit line in `body`.
  * jobicy (jobicy.com/api/v2/remote-jobs) -- free, keyless JSON (the
    user's own suggested RSS feed has this JSON twin). Same remote-only +
    credit-required shape as remoteok.
  * alljobs (alljobs.co.il) -- Israel's largest board, no public API, but
    its robots.txt-published sitemap (`JobsActual_PC_0.xml`..`_7.xml`,
    ~40,000 active postings) lists every live job's own page with a real
    `lastmod`, and that page embeds a standard schema.org `JobPosting`
    JSON-LD block -- the same structured markup AllJobs feeds Google for
    Jobs, far more stable to parse than hand-picked HTML classes.

All four of remoteok/jobicy/arbeitnow/alljobs's "US-only" postings are
filtered out where detectable (simple deny-list on the visible text) since
the user explicitly wants only jobs actually doable from Israel.

Every created post is auto-published (approved_to_publish=True) under the
existing bot account already used for other automated content on this
site (see BOT_EMAIL below) -- a deliberate choice (confirmed with the
user), unlike the news scraper's pending-queue default, since reviewing a
real daily volume of job listings one by one would defeat the point.
"""
import html
import json
import os
from collections import Counter
import re
from datetime import datetime, timedelta

import httpx
from bs4 import BeautifulSoup
from flask import Blueprint, jsonify, request

from config import db
from security import super_admin_required, cron_secret_required
from backend.user.modals.user import User
from backend.tachlis.modals.tachlis_post import TachlisPost, EXPIRES_DAYS
from backend.tachlis.modals.scraped_job import ScrapedJob
from backend.tachlis.routes.tachlis_post import _geocode, TITLE_MAX, BODY_MAX, CONTACT_MAX, LOCATION_MAX, CATEGORY_MAX
from backend.tachlis.emails import send_job_scraper_summary_email

job_scraper_api = Blueprint('job_scraper_api', __name__, url_prefix='/tachlis/scrape')

USER_AGENT = 'GutShtickBot/1.0 (+https://gutshtick.com; job board bot)'

# Who gets the daily "N new jobs added" stats email after cron/run-all.
# Overridable via env in case the recipient ever changes.
JOB_SCRAPER_STATS_EMAIL = os.environ.get('JOB_SCRAPER_STATS_EMAIL', 'gary.s.schwartz617@gmail.com')

# The same bot account already used elsewhere on this site for automated
# content (confirmed live: is_boss=True) -- see create_post's own comment
# in tachlis_post.py for the exact mechanism this piggybacks on
# (`if current_user.is_boss: post.approved_to_publish = True`). Overridable
# via env in case that account's email ever changes.
BOT_EMAIL = os.environ.get('JOB_SCRAPER_BOT_EMAIL', 'gutnews.bot.08ed4ee2@gutshtick.com')

DEFAULT_COUNT = 25
MAX_COUNT = 100
DUPLICATE_STREAK_LIMIT = 8

# A remote posting restricted to one specific country/region isn't doable
# from Israel regardless of being "remote" -- confirmed live this needs to
# catch more than just the US: real postings came back geo-tagged "US Only"
# and "Canada Only" alike. "<region> only" is an unambiguous hard
# restriction phrase regardless of which source produces it or which
# region it names, so it's matched generically rather than against a fixed
# list of countries -- "israel/anywhere/worldwide/global" are the only
# "only"s that should ever pass. Scoped to the short geo/location LABEL
# only (e.g. "US Only", "Israel", "Worldwide") -- a full job description
# routinely contains innocuous "only" phrases ("full-time only", "serious
# applicants only") that have nothing to do with geography, so this regex
# must never be run against title/description text.
_ALLOWED_ONLY_TERMS = ('israel', 'anywhere', 'worldwide', 'global', 'international')
_ONLY_RESTRICTION_RE = re.compile(r'\b([a-z][a-z .]{1,24}?)\s+only\b', re.I)
# Longer-form restriction phrasing, specific enough to safely check against
# the full title+description blob too (unlike the bare word "only" above).
_RESTRICTED_PHRASES = (
    'citizens only', 'residents only',
    'must be based in the us', 'must be located in the us',
    'based in the united states', 'within the united states only',
)


def _geo_label_restricted(geo_text):
    """True if a short geo/location label (NOT a full description) names a
    specific place other than Israel/Anywhere/Worldwide and says "only"."""
    if not geo_text:
        return False
    m = _ONLY_RESTRICTION_RE.search(geo_text.lower())
    return bool(m and m.group(1).strip() not in _ALLOWED_ONLY_TERMS)


def _is_us_restricted(geo_text, *wider_texts):
    if _geo_label_restricted(geo_text):
        return True
    blob = ' '.join(t for t in wider_texts if t).lower()
    return any(term in blob for term in _RESTRICTED_PHRASES)


def _clean_html(raw):
    """RSS/API description fields are often HTML -- same approach as
    content_pipeline/routes/scraper.py's _clean_summary, just without that
    function's short SUMMARY_MAX cap (a job's body is meant to be the real
    description, not a teaser)."""
    if not raw:
        return ''
    text = html.unescape(raw)
    if '<' in text and '>' in text:
        text = BeautifulSoup(text, 'html.parser').get_text('\n', strip=True)
    return re.sub(r'[ \t]+', ' ', text).strip()


def _truncate(text, limit):
    if not text:
        return text
    return text if len(text) <= limit else text[:limit - 1].rstrip() + '…'


def _with_credit(body, credit, url):
    """Appends a short attribution line -- required by RemoteOK/Jobicy's
    own terms, and kept for every source for consistent transparency about
    where a listing actually came from. Truncates the body first so the
    credit line itself never gets cut off by BODY_MAX."""
    footer = f'\n\n— via {credit}: {url}'
    return _truncate(body, BODY_MAX - len(footer)) + footer


def _remote_location_text(raw_location):
    """A remote job's `location` (company HQ / region restriction) isn't
    where the job itself is -- formatting it as "Remote (<text>)" reads
    honestly to a person AND is safe for geocoding: tachlis_post.py's
    _geocode() already strips a trailing "(...)" qualifier before checking
    its vague-term list, so this correctly resolves to no geocode attempt
    (as a fully remote posting should) while still showing the original
    region to a reader."""
    raw_location = (raw_location or '').strip()
    return f'Remote ({raw_location})' if raw_location else 'Remote'


# ── arbeitnow ────────────────────────────────────────────────────────────
ARBEITNOW_URL = 'https://www.arbeitnow.com/api/job-board-api'


def _fetch_arbeitnow(client, count):
    resp = client.get(ARBEITNOW_URL)
    resp.raise_for_status()
    jobs = resp.json().get('data') or []

    items = []
    excluded_restricted = 0
    for j in jobs:
        url = j.get('url')
        title = j.get('title')
        if not url or not title:
            continue
        is_remote = bool(j.get('remote'))
        location = (j.get('location') or '').strip()
        if not is_remote and 'israel' not in location.lower():
            continue  # on-site and not in Israel -- out of scope
        if _is_us_restricted(location, title, j.get('description')):
            excluded_restricted += 1
            continue

        body = _clean_html(j.get('description'))
        company = j.get('company_name')
        if company:
            body = f'Company: {company}\n\n{body}'
        created_at = j.get('created_at')
        items.append({
            'url': url,
            'title': title,
            'body': _with_credit(body, 'Arbeitnow', url),
            'contact': url,
            'location': _remote_location_text(location) if is_remote else location,
            'remote': is_remote,
            'category': (j.get('tags') or j.get('job_types') or [None])[0],
            'compensation': None,
            'source_posted_at': datetime.utcfromtimestamp(created_at) if created_at else None,
        })
    return items, excluded_restricted


# ── remoteok ─────────────────────────────────────────────────────────────
REMOTEOK_URL = 'https://remoteok.com/api'


def _fetch_remoteok(client, count):
    resp = client.get(REMOTEOK_URL)
    resp.raise_for_status()
    jobs = resp.json() or []
    jobs = jobs[1:]  # index 0 is RemoteOK's own legal/attribution notice, not a job

    items = []
    excluded_restricted = 0
    for j in jobs:
        url = j.get('url') or j.get('apply_url')
        title = j.get('position')
        if not url or not title:
            continue
        location = (j.get('location') or '').strip()
        description = j.get('description')
        if _is_us_restricted(location, title, description):
            excluded_restricted += 1
            continue

        body = _clean_html(description)
        company = j.get('company')
        if company:
            body = f'Company: {company}\n\n{body}'
        date_str = j.get('date')
        source_posted_at = None
        if date_str:
            try:
                source_posted_at = datetime.fromisoformat(date_str.replace('Z', '+00:00')).replace(tzinfo=None)
            except ValueError:
                pass
        salary_min, salary_max = j.get('salary_min'), j.get('salary_max')
        compensation = f'${salary_min:,.0f}–${salary_max:,.0f}' if salary_min and salary_max else None
        items.append({
            'url': url,
            'title': title,
            'body': _with_credit(body, 'Remote OK', url),
            'contact': url,
            'location': _remote_location_text(location),
            'remote': True,
            'category': (j.get('tags') or [None])[0],
            'compensation': compensation,
            'source_posted_at': source_posted_at,
        })
    return items, excluded_restricted


# ── jobicy ───────────────────────────────────────────────────────────────
JOBICY_URL = 'https://jobicy.com/api/v2/remote-jobs'


def _fetch_jobicy(client, count):
    items = []
    excluded_restricted = 0
    cursor = None
    # Jobicy's own `geo` filter was confirmed unreliable for narrowing to
    # Israel specifically (returns broad EMEA/APAC/Anywhere results), so
    # this pulls broadly and relies on the same US-only deny-list filter
    # every other remote source uses instead of trusting their geo tag.
    for _ in range(4):  # a handful of pages is plenty for one daily run
        params = {'count': 50}
        if cursor:
            params['cursor'] = cursor
        resp = client.get(JOBICY_URL, params=params)
        resp.raise_for_status()
        data = resp.json()
        jobs = data.get('jobs') or []

        for j in jobs:
            url = j.get('url')
            title = j.get('jobTitle')
            if not url or not title:
                continue
            geo = (j.get('jobGeo') or '').strip()
            excerpt = j.get('jobDescription') or j.get('jobExcerpt') or ''
            if _is_us_restricted(geo, title, excerpt):
                excluded_restricted += 1
                continue

            body = _clean_html(excerpt)
            company = j.get('companyName')
            if company:
                body = f'Company: {company}\n\n{body}'
            industries = j.get('jobIndustry') or []
            items.append({
                'url': url,
                'title': title,
                'body': _with_credit(body, 'Jobicy', url),
                'contact': url,
                'location': _remote_location_text(geo),
                'remote': True,
                'category': industries[0] if industries else None,
                'compensation': j.get('jobSalary'),
                'source_posted_at': None,
            })
            if len(items) >= count + DUPLICATE_STREAK_LIMIT + 10:
                return items, excluded_restricted  # plenty of candidates for the caller's dedup loop

        if not data.get('hasMore'):
            break
        cursor = data.get('nextCursor')
        if not cursor:
            break
    return items, excluded_restricted


# ── alljobs ──────────────────────────────────────────────────────────────
ALLJOBS_SITEMAP_INDEX = 'https://www.alljobs.co.il/sitemap/sitemap.xml'
_ALLJOBS_SHARD_RE = re.compile(r'JobsActual_PC_\d+\.xml')
_ALLJOBS_JOBID_RE = re.compile(r'[?&]JobID=(\d+)')


def _alljobs_candidate_urls(client):
    """Every active job's own page URL + lastmod, newest first -- same
    sitemap-shards-sorted-by-lastmod approach as content_pipeline/routes/
    scraper.py's _pzdeals_latest_sitemap_urls, for the same reason: new
    postings can land on any shard, so the index is re-read fresh every
    run rather than trusting a pinned shard number to still be the newest
    one."""
    resp = client.get(ALLJOBS_SITEMAP_INDEX)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, 'xml')
    shard_urls = [loc.get_text(strip=True) for loc in soup.find_all('loc')
                  if _ALLJOBS_SHARD_RE.search(loc.get_text(strip=True))]

    candidates = []
    for shard_url in shard_urls:
        shard_resp = client.get(shard_url)
        shard_resp.raise_for_status()
        shard_soup = BeautifulSoup(shard_resp.text, 'xml')
        for url_tag in shard_soup.find_all('url'):
            loc = url_tag.find('loc')
            lastmod = url_tag.find('lastmod')
            if loc is None:
                continue
            candidates.append((loc.get_text(strip=True), lastmod.get_text(strip=True) if lastmod else ''))

    candidates.sort(key=lambda c: c[1], reverse=True)
    return candidates


def _parse_alljobs_job_posting(html_text):
    """Pulls the schema.org JobPosting JSON-LD block out of an AllJobs job
    page -- the same structured markup the site feeds Google for Jobs, far
    more stable than hand-picked HTML classes. Returns the parsed dict, or
    None if the page has no such block (a removed/expired posting)."""
    soup = BeautifulSoup(html_text, 'html.parser')
    for tag in soup.find_all('script', attrs={'type': 'application/ld+json'}):
        try:
            data = json.loads(tag.string or '')
        except (ValueError, TypeError):
            continue
        if data.get('@type') == 'JobPosting':
            return data
    return None


def _fetch_alljobs(client, count):
    candidates = _alljobs_candidate_urls(client)

    # Drop anything already scraped before spending a request on its own
    # page -- a single query for the whole candidate batch rather than one
    # per URL.
    urls = [c[0] for c in candidates]
    already = {row.url for row in ScrapedJob.query.filter_by(source='alljobs')
               .filter(ScrapedJob.url.in_(urls)).all()} if urls else set()

    items = []
    now = datetime.utcnow()
    for url, _lastmod in candidates:
        if url in already:
            continue
        try:
            resp = client.get(url)
            resp.raise_for_status()
        except httpx.HTTPError:
            continue
        posting = _parse_alljobs_job_posting(resp.text)
        if not posting:
            continue

        valid_through = posting.get('validThrough')
        if valid_through:
            try:
                if datetime.fromisoformat(valid_through).replace(tzinfo=None) < now:
                    continue  # sitemap lagging reality -- already expired
            except ValueError:
                pass

        title = posting.get('title')
        description = posting.get('description')
        if not title or not description:
            continue

        address = posting.get('jobLocation', {}).get('address')
        if isinstance(address, list):
            address = address[0] if address else {}
        address = address or {}
        location = (address.get('addressLocality') or '').strip() or None

        company = (posting.get('hiringOrganization') or {}).get('name')
        body = description if not company else f'Company: {company}\n\n{description}'

        date_posted = posting.get('datePosted')
        source_posted_at = None
        if date_posted:
            try:
                source_posted_at = datetime.fromisoformat(date_posted).replace(tzinfo=None)
            except ValueError:
                pass

        items.append({
            'url': url,
            'title': title,
            'body': _with_credit(body, 'AllJobs', url),
            'contact': url,
            'location': location,
            'remote': posting.get('jobLocationType') == 'TELECOMMUTE',
            'category': posting.get('industry'),
            'compensation': None,
            'source_posted_at': source_posted_at,
        })
        if len(items) >= count:
            break
    return items, 0  # no geo-restriction filter applies here -- every result is already in Israel


SOURCES = {
    'arbeitnow': {'fetch': _fetch_arbeitnow, 'credit': 'Arbeitnow'},
    'remoteok': {'fetch': _fetch_remoteok, 'credit': 'Remote OK'},
    'jobicy': {'fetch': _fetch_jobicy, 'credit': 'Jobicy'},
    'alljobs': {'fetch': _fetch_alljobs, 'credit': 'AllJobs'},
}


def _get_bot_user():
    user = User.query.filter_by(email=BOT_EMAIL).first()
    if not user:
        raise RuntimeError(f'Job scraper bot account not found: {BOT_EMAIL}')
    return user


def _create_job_post(item, bot_user):
    location = item.get('location')
    lat, lng = _geocode(location) if location else (None, None)
    post = TachlisPost(
        post_type='job',
        title=_truncate(item['title'], TITLE_MAX),
        body=_truncate(item['body'], BODY_MAX),
        contact=_truncate(item['contact'], CONTACT_MAX),
        user_id=bot_user.public_id,
        location=_truncate(location, LOCATION_MAX) if location else None,
        compensation=item.get('compensation'),
        category=_truncate(item.get('category'), CATEGORY_MAX) if item.get('category') else None,
        remote=item.get('remote'),
        source_posted_at=item.get('source_posted_at'),
        expires_at=datetime.utcnow() + timedelta(days=EXPIRES_DAYS['job']),
        lat=lat, lng=lng,
    )
    post.approved_to_publish = True
    post.approved_by = bot_user.public_id
    db.session.add(post)
    db.session.flush()  # assign post.id
    return post


def _run_source(source, count):
    cfg = SOURCES[source]
    added = 0
    checked = 0
    duplicate_streak = 0
    stopped_reason = 'no_more_jobs'
    remote_count = 0
    onsite_count = 0
    category_counts = Counter()
    location_counts = Counter()
    bot_user = _get_bot_user()

    with httpx.Client(headers={'User-Agent': USER_AGENT}, timeout=25, follow_redirects=True) as client:
        items, excluded_restricted = cfg['fetch'](client, count)

        for item in items:
            checked += 1
            url = item['url']
            if len(url) > 500:
                continue  # ScrapedJob.url / TachlisPost.contact column limits

            existing = ScrapedJob.query.filter_by(source=source, url=url).first()
            if existing is not None:
                duplicate_streak += 1
                if duplicate_streak >= DUPLICATE_STREAK_LIMIT:
                    stopped_reason = 'duplicate_limit'
                    break
                continue
            duplicate_streak = 0

            post = _create_job_post(item, bot_user)
            db.session.add(ScrapedJob(source=source, url=url, title=item['title'][:300], tachlis_post_id=post.id))
            db.session.commit()

            added += 1
            if item.get('remote'):
                remote_count += 1
            else:
                onsite_count += 1
            if item.get('category'):
                category_counts[item['category']] += 1
            if item.get('location'):
                location_counts[item['location']] += 1
            if added >= count:
                stopped_reason = 'count_reached'
                break

    return {
        'source': source, 'added': added, 'checked': checked, 'stopped_reason': stopped_reason,
        'excluded_restricted': excluded_restricted,
        'remote_count': remote_count, 'onsite_count': onsite_count,
        'category_counts': category_counts, 'location_counts': location_counts,
    }


@job_scraper_api.route('/<source>', methods=['POST'])
@super_admin_required
def run_job_scraper(current_user, source):
    if source not in SOURCES:
        return jsonify({'message': f"Unknown source '{source}'. Expected one of: {', '.join(SOURCES)}"}), 400

    body = request.get_json(silent=True) or {}
    try:
        count = int(body.get('count', DEFAULT_COUNT))
    except (TypeError, ValueError):
        count = DEFAULT_COUNT
    count = max(1, min(count, MAX_COUNT))

    try:
        result = _run_source(source, count)
    except (httpx.HTTPError, ValueError) as e:
        return jsonify({'source': source, 'message': f'Failed to fetch source: {e}'}), 502
    except RuntimeError as e:
        return jsonify({'source': source, 'message': str(e)}), 500
    return jsonify(result)


def _run_all(count):
    """Runs every source, each independently inside its own try/except --
    one source's failure (a dead API, a changed sitemap path) must never
    block the others. Shared by the daily cron endpoint and the
    admin-triggered "run all" button, so both see identical stats and both
    get the same summary email."""
    results = {}
    for source in SOURCES:
        try:
            results[source] = _run_source(source, count)
        except Exception as e:  # noqa: BLE001 -- a scraper bug must never sink the whole run
            db.session.rollback()
            results[source] = {'source': source, 'error': str(e)}

    if JOB_SCRAPER_STATS_EMAIL:
        try:
            send_job_scraper_summary_email(JOB_SCRAPER_STATS_EMAIL, results)
        except Exception:
            pass  # a stats-email failure must never surface as a failed run

    return results


@job_scraper_api.route('/run-all', methods=['POST'])
@super_admin_required
def run_all_admin(current_user):
    """Manual "run everything now" from the admin panel -- same aggregation
    (and the same summary email) as the daily cron, just triggered by a
    super admin on demand instead of on a schedule."""
    body = request.get_json(silent=True) or {}
    try:
        count = int(body.get('count', DEFAULT_COUNT))
    except (TypeError, ValueError):
        count = DEFAULT_COUNT
    count = max(1, min(count, MAX_COUNT))
    return jsonify(_run_all(count))


@job_scraper_api.route('/cron/run-all', methods=['POST'])
@cron_secret_required
def run_all_cron():
    """Hit daily by .github/workflows/jobs-scraper-cron.yml."""
    return jsonify(_run_all(DEFAULT_COUNT))
