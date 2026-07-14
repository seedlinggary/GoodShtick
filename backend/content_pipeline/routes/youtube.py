"""YouTube channel monitoring for the SuperAdmin dashboard.

A super-admin tracks a list of YouTube channels; a "check" walks each channel's
recent uploads and drops any brand-new video into the existing pending-approval
queue (Shtick.approved_to_publish left as None) as an embed-ready YouTube post
for a human admin to review before it goes live. Super-admin only.

Blueprint:  youtube_api   (url_prefix='/content-pipeline/youtube')
Registered centrally in application.py — do NOT register here.

Calls the YouTube Data API v3 REST endpoints directly via httpx (no SDK). The
API key is read lazily from the environment (YOUTUBE_API_KEY); the pure-DB
channel add/list/remove routes work without it, and only /check requires it.
If the key is missing, /check returns a clean 503 instead of crashing.
"""

import logging
import os
import re
from datetime import datetime
from urllib.parse import urlparse, unquote

import httpx
from flask import Blueprint, jsonify, request
from sqlalchemy.exc import IntegrityError

from config import db
from security import super_admin_required
from backend.shtick.modals.shtick import Shtick
from backend.shtick.modals.content import Content
from backend.shtick.modals.url import Url
from backend.shtick.modals.generalc import Generalc
from backend.content_pipeline.modals.youtube_channel import (
    YoutubeChannel,
    YoutubeVideoPost,
)

logger = logging.getLogger(__name__)

youtube_api = Blueprint('youtube_api', __name__, url_prefix='/content-pipeline/youtube')

# DB field limits (see backend/shtick/modals/shtick.py) — hard caps so inserts
# never truncate/fail at the DB layer; we truncate on our side to match.
CAPTION_MAX = 120   # Shtick.caption (post title = video title)
CREDIT_MAX = 125    # Shtick.credit (attribution = channel display name)
CONTENT_MAX = 1000  # keep the description snippet brief in Content.stuff

YT_API_BASE = 'https://www.googleapis.com/youtube/v3'
HTTP_TIMEOUT = 15.0             # seconds per outbound API call
UPLOADS_FETCH = 10             # how many recent uploads to pull per channel
FIRST_CHECK_CAP = 5           # on a channel's first-ever check, only post the 5
                              # most recent uploads so a big back-catalog never
                              # floods the pending queue. Subsequent checks are
                              # naturally bounded by UPLOADS_FETCH (10).

# A channel ID is "UC" + 22 url-safe base64 chars.
_CHANNEL_ID_RE = re.compile(r'^UC[0-9A-Za-z_-]{22}$')


class YoutubeApiError(Exception):
    """A YouTube Data API failure with a user-facing message and HTTP status
    to relay back to the caller (invalid key, quota exceeded, not found …)."""

    def __init__(self, message, status=502):
        super().__init__(message)
        self.message = message
        self.status = status


# ---------------------------------------------------------------------------
# YouTube Data API helpers (httpx, key passed as the `key` query param)
# ---------------------------------------------------------------------------

def _yt_get(client, path, params, api_key):
    """GET a v3 endpoint and return parsed JSON, raising YoutubeApiError with a
    friendly message on any failure (network, non-200, or API error body)."""
    params = dict(params)
    params['key'] = api_key
    try:
        resp = client.get(f'{YT_API_BASE}/{path}', params=params)
    except httpx.RequestError as exc:
        raise YoutubeApiError(f'Could not reach YouTube: {exc}', status=502)

    if resp.status_code == 200:
        return resp.json()

    # Try to surface YouTube's structured error reason.
    reason = None
    message = None
    try:
        err = resp.json().get('error', {})
        message = err.get('message')
        errors = err.get('errors') or []
        if errors:
            reason = errors[0].get('reason')
    except Exception:  # noqa: BLE001 — non-JSON error body
        pass

    if resp.status_code == 403:
        if reason in ('quotaExceeded', 'dailyLimitExceeded', 'rateLimitExceeded'):
            raise YoutubeApiError(
                'YouTube API quota exceeded — try again later.', status=429)
        raise YoutubeApiError(
            message or 'YouTube API key is invalid or lacks access to the '
            'YouTube Data API.', status=403)
    if resp.status_code == 400:
        raise YoutubeApiError(
            message or 'Bad request to YouTube (check the key / input).',
            status=400)
    if resp.status_code == 404:
        raise YoutubeApiError(message or 'Channel or resource not found.',
                              status=404)
    raise YoutubeApiError(
        message or f'YouTube API error (HTTP {resp.status_code}).', status=502)


def _channel_by_id(client, api_key, channel_id, parts='snippet'):
    """Fetch a channel resource by its UC id. Returns the item dict or None."""
    data = _yt_get(client, 'channels',
                   {'part': parts, 'id': channel_id}, api_key)
    items = data.get('items') or []
    return items[0] if items else None


def _channel_by_handle(client, api_key, handle):
    """Resolve a @handle to a channel item via forHandle. The API is picky about
    the leading '@', so try the bare handle first, then with '@'. Returns the
    item dict or None."""
    bare = handle.lstrip('@')
    for candidate in (bare, f'@{bare}'):
        data = _yt_get(client, 'channels',
                       {'part': 'id,snippet', 'forHandle': candidate}, api_key)
        items = data.get('items') or []
        if items:
            return items[0]
    return None


def _channel_by_search(client, api_key, query):
    """Last-resort resolution for /c/CustomName and /user/LegacyName forms and
    free-text names: search for a channel and take the top hit. Returns
    (channel_id, display_name) or None."""
    data = _yt_get(client, 'search',
                   {'part': 'snippet', 'type': 'channel', 'q': query,
                    'maxResults': 1}, api_key)
    items = data.get('items') or []
    if not items:
        return None
    top = items[0]
    cid = (top.get('id') or {}).get('channelId')
    name = (top.get('snippet') or {}).get('title')
    if not cid:
        return None
    return cid, name


def _resolve_channel(client, api_key, raw):
    """Resolve arbitrary admin input (channel URL, @handle, /c/ or /user/ URL,
    or a raw UC… id) to (channel_id, display_name). Raises YoutubeApiError if it
    can't be resolved."""
    raw = (raw or '').strip()
    if not raw:
        raise YoutubeApiError('No channel input provided.', status=400)

    handle = None          # a @handle or bare handle to try via forHandle
    direct_id = None       # a UC… id we already have
    search_term = None     # a custom/legacy name to resolve via search

    looks_like_url = raw.startswith('http') or 'youtube.com' in raw or 'youtu.be' in raw
    if looks_like_url:
        # Normalise to a parseable URL so urlparse gives us a clean path.
        url = raw if raw.startswith('http') else 'https://' + raw.lstrip('/')
        parsed = urlparse(url)
        # Path segments, unquoted (custom names may be percent-encoded).
        segments = [unquote(s) for s in parsed.path.split('/') if s]

        if not segments:
            raise YoutubeApiError('Could not find a channel in that URL.',
                                  status=400)

        first = segments[0]
        if first == 'channel' and len(segments) >= 2:
            direct_id = segments[1]
        elif first == 'user' and len(segments) >= 2:
            # Legacy username — forUsername is deprecated/unreliable; use search.
            search_term = segments[1]
        elif first == 'c' and len(segments) >= 2:
            search_term = segments[1]
        elif first.startswith('@'):
            handle = first
        else:
            # e.g. youtube.com/SomeName — treat as a handle, fall back to search.
            handle = first
    else:
        # Not a URL: bare @handle, raw UC id, or a plain name.
        if raw.startswith('@'):
            handle = raw
        elif _CHANNEL_ID_RE.match(raw):
            direct_id = raw
        else:
            # Could be a handle typed without '@', or a channel name.
            handle = raw

    # --- direct UC id ---
    if direct_id:
        if not _CHANNEL_ID_RE.match(direct_id):
            raise YoutubeApiError(f'"{direct_id}" is not a valid channel id.',
                                  status=400)
        item = _channel_by_id(client, api_key, direct_id)
        if not item:
            raise YoutubeApiError('No channel found for that id.', status=404)
        name = (item.get('snippet') or {}).get('title')
        return direct_id, name

    # --- @handle (with search fallback) ---
    if handle:
        item = _channel_by_handle(client, api_key, handle)
        if item:
            cid = item.get('id')
            # forHandle returns id as a bare string under 'id'
            if isinstance(cid, dict):
                cid = cid.get('channelId')
            name = (item.get('snippet') or {}).get('title')
            if cid:
                return cid, name
        # Fall back to search using the handle text.
        found = _channel_by_search(client, api_key, handle.lstrip('@'))
        if found:
            return found
        raise YoutubeApiError(
            f'Could not resolve "{raw}" to a YouTube channel.', status=404)

    # --- /c/ or /user/ name via search ---
    if search_term:
        found = _channel_by_search(client, api_key, search_term)
        if found:
            return found
        raise YoutubeApiError(
            f'Could not resolve "{raw}" to a YouTube channel.', status=404)

    raise YoutubeApiError(f'Could not understand "{raw}".', status=400)


def _uploads_playlist_id(client, api_key, channel_id):
    """Return the channel's 'uploads' playlist id, or None if unavailable."""
    item = _channel_by_id(client, api_key, channel_id, parts='contentDetails')
    if not item:
        return None
    related = (item.get('contentDetails') or {}).get('relatedPlaylists') or {}
    return related.get('uploads')


def _recent_uploads(client, api_key, uploads_playlist_id):
    """Return recent uploads (newest first) as a list of dicts:
    {video_id, title, description, published_at}."""
    data = _yt_get(client, 'playlistItems',
                   {'part': 'snippet,contentDetails',
                    'playlistId': uploads_playlist_id,
                    'maxResults': UPLOADS_FETCH}, api_key)
    out = []
    for it in data.get('items') or []:
        snippet = it.get('snippet') or {}
        details = it.get('contentDetails') or {}
        vid = details.get('videoId') or (snippet.get('resourceId') or {}).get('videoId')
        if not vid:
            continue
        out.append({
            'video_id': vid,
            'title': snippet.get('title') or '',
            'description': snippet.get('description') or '',
            'published_at': snippet.get('publishedAt') or '',
        })
    return out


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _get_api_key():
    key = os.environ.get('YOUTUBE_API_KEY')
    return key.strip() if key else None


DEFAULT_CATEGORY_NAME = 'Videos'


def _default_category():
    """Pick a default category for auto-created posts. Prefers the 'Videos'
    category (a meaningful fit for YouTube uploads) over just grabbing
    whatever has the lowest id -- that used to land every video under
    whichever category happened to be seeded first ('Funny'), regardless of
    actual content. Falls back to lowest-id if 'Videos' doesn't exist, and to
    None if the site has no categories yet at all -- video posts still land
    in the pending queue and the 'all' feed even without a category."""
    return (Generalc.query.filter_by(name=DEFAULT_CATEGORY_NAME).first()
            or Generalc.query.order_by(Generalc.id.asc()).first())


def _channel_dict(ch):
    return {
        'id': ch.id,
        'channel_id': ch.channel_id,
        'display_name': ch.display_name,
        'added_at': ch.added_at.isoformat() if ch.added_at else None,
        'last_checked_at': ch.last_checked_at.isoformat() if ch.last_checked_at else None,
        'active': ch.active,
    }


def _post_video(channel, video, current_user, category):
    """Create a pending Shtick (+Content +Url) and the dedup YoutubeVideoPost row
    for one video. Returns the new Shtick id, or None if it was a duplicate that
    slipped past the pre-check (unique constraint on video_id). Commits its own
    work so one bad video never rolls back earlier posts in the batch."""
    video_id = video['video_id']
    watch_url = f'https://www.youtube.com/watch?v={video_id}'  # matches ShowURL embed regex
    title = (video['title'] or 'Untitled video')[:CAPTION_MAX]
    credit = (channel.display_name or channel.channel_id)[:CREDIT_MAX]
    body = (video['description'] or video['title'] or '').strip()[:CONTENT_MAX]

    try:
        new_shtick = Shtick(
            caption=title,
            credit=credit,
            specific_category=None,
            user_id=current_user.public_id,
            generalc_id=category.id if category else None,
        )
        # approved_to_publish intentionally left as its default (None) so the
        # post lands in the pending-approval queue for human review.
        db.session.add(new_shtick)
        db.session.flush()  # need new_shtick.id for the child rows

        if category and category not in new_shtick.categories:
            new_shtick.categories.append(category)

        if body:
            db.session.add(Content(stuff=body, shtick_id=new_shtick.id))
        db.session.add(Url(name=watch_url, shtick_id=new_shtick.id))
        db.session.add(YoutubeVideoPost(
            channel_id=channel.channel_id,
            video_id=video_id,
            shtick_id=new_shtick.id,
        ))
        db.session.commit()
        return new_shtick.id
    except IntegrityError:
        # Another concurrent check (or a race) already posted this video — the
        # unique constraint on video_id caught it. Skip cleanly.
        db.session.rollback()
        logger.info('Video %s already posted (unique constraint) — skipping', video_id)
        return None


def _check_channel(client, api_key, channel, current_user, category):
    """Check one channel for new uploads and post them. Returns the count of
    newly posted videos. Raises YoutubeApiError on API failure."""
    uploads = _uploads_playlist_id(client, api_key, channel.channel_id)
    if not uploads:
        raise YoutubeApiError(
            f'Could not find uploads for channel {channel.channel_id}.',
            status=404)

    videos = _recent_uploads(client, api_key, uploads)  # newest first
    channel.last_checked_at = datetime.utcnow()

    if not videos:
        db.session.commit()  # persist last_checked_at even with nothing new
        return 0

    first_ever = channel.last_video_id is None

    # Walk newest-first, collecting videos we haven't posted yet. Stop early once
    # we hit the fast-path cache (last_video_id) — everything older was already
    # handled on a previous check.
    new_videos = []
    for v in videos:
        if v['video_id'] == channel.last_video_id:
            break
        # Authoritative dedup: skip anything already recorded.
        exists = YoutubeVideoPost.query.filter_by(video_id=v['video_id']).first()
        if exists:
            continue
        new_videos.append(v)

    if first_ever:
        new_videos = new_videos[:FIRST_CHECK_CAP]

    # Always advance the fast-path cache to the channel's most recent upload so
    # the next check can short-circuit, even if the cap skipped some videos.
    newest_id = videos[0]['video_id']

    # Create oldest-first so the newest video gets the latest pub_date (top of
    # the feed once approved).
    posted = 0
    for v in reversed(new_videos):
        if _post_video(channel, v, current_user, category) is not None:
            posted += 1

    # Update the cache/timestamp on the channel. Re-fetch is unnecessary; the
    # channel object is still attached. Commit after the per-video commits.
    channel.last_video_id = newest_id
    channel.last_checked_at = datetime.utcnow()
    db.session.commit()
    return posted


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@youtube_api.route('/channels', methods=['GET'])
@super_admin_required
def list_channels(_current_user):
    """List tracked (active) channels. Soft-removed channels are hidden here but
    their YoutubeVideoPost dedup history is preserved."""
    channels = (YoutubeChannel.query
                .filter_by(active=True)
                .order_by(YoutubeChannel.added_at.desc())
                .all())
    return jsonify([_channel_dict(c) for c in channels])


@youtube_api.route('/channels', methods=['POST'])
@super_admin_required
def add_channel(current_user):
    """Add a channel by URL / @handle / raw UC id. Resolves it to a channel id +
    display name via the API. Gracefully handles an already-tracked channel."""
    api_key = _get_api_key()
    if not api_key:
        return jsonify({'error': 'YOUTUBE_API_KEY not configured'}), 503

    body = request.get_json(silent=True) or {}
    raw = (body.get('input') or '').strip()
    if not raw:
        return jsonify({'message': 'Please provide a channel URL, handle, or id.'}), 400

    try:
        with httpx.Client(timeout=HTTP_TIMEOUT) as client:
            channel_id, display_name = _resolve_channel(client, api_key, raw)
    except YoutubeApiError as exc:
        return jsonify({'error': exc.message}), exc.status

    # Already tracked? (unique constraint on channel_id) — reactivate if it was
    # soft-removed, otherwise report it's already there. No duplicate row.
    existing = YoutubeChannel.query.filter_by(channel_id=channel_id).first()
    if existing:
        if not existing.active:
            existing.active = True
            if display_name:
                existing.display_name = display_name
            db.session.commit()
            return jsonify({'message': 'Channel re-added.',
                            'channel': _channel_dict(existing)}), 200
        return jsonify({'message': 'Channel is already tracked.',
                        'channel': _channel_dict(existing)}), 200

    channel = YoutubeChannel(
        channel_id=channel_id,
        display_name=display_name,
        added_by=current_user.public_id,
    )
    db.session.add(channel)
    try:
        db.session.commit()
    except IntegrityError:
        # Race: inserted between the check above and commit. Fetch and return it.
        db.session.rollback()
        existing = YoutubeChannel.query.filter_by(channel_id=channel_id).first()
        if existing and not existing.active:
            existing.active = True
            db.session.commit()
        return jsonify({'message': 'Channel is already tracked.',
                        'channel': _channel_dict(existing) if existing else None}), 200

    return jsonify({'message': 'Channel added.',
                    'channel': _channel_dict(channel)}), 201


@youtube_api.route('/channels/<int:channel_id>', methods=['DELETE'])
@super_admin_required
def remove_channel(_current_user, channel_id):
    """Soft-remove a channel (active=False). Soft delete (rather than a hard
    row delete) preserves the YoutubeVideoPost dedup history that FK-references
    this channel, so re-adding the same channel later won't repost old videos."""
    channel = db.session.get(YoutubeChannel, channel_id)
    if not channel:
        return jsonify({'message': 'Channel not found.'}), 404
    channel.active = False
    db.session.commit()
    return jsonify({'message': 'Channel removed.'})


@youtube_api.route('/channels/<int:channel_id>/check', methods=['POST'])
@super_admin_required
def check_one(current_user, channel_id):
    """Check a single tracked channel for new uploads."""
    api_key = _get_api_key()
    if not api_key:
        return jsonify({'error': 'YOUTUBE_API_KEY not configured'}), 503

    channel = db.session.get(YoutubeChannel, channel_id)
    if not channel:
        return jsonify({'message': 'Channel not found.'}), 404

    category = _default_category()
    try:
        with httpx.Client(timeout=HTTP_TIMEOUT) as client:
            count = _check_channel(client, api_key, channel, current_user, category)
    except YoutubeApiError as exc:
        db.session.rollback()
        return jsonify({'error': exc.message}), exc.status

    return jsonify({
        'total_new_videos': count,
        'channels': [{'channel': channel.display_name or channel.channel_id,
                      'channel_db_id': channel.id,
                      'new_videos': count}],
    })


@youtube_api.route('/check', methods=['POST'])
@super_admin_required
def check_all(current_user):
    """Check every active tracked channel for new uploads and post them to the
    pending queue. Returns a per-channel summary and an overall total."""
    api_key = _get_api_key()
    if not api_key:
        return jsonify({'error': 'YOUTUBE_API_KEY not configured'}), 503

    channels = YoutubeChannel.query.filter_by(active=True).all()
    category = _default_category()

    results = []
    total = 0
    with httpx.Client(timeout=HTTP_TIMEOUT) as client:
        for channel in channels:
            entry = {'channel': channel.display_name or channel.channel_id,
                     'channel_db_id': channel.id}
            try:
                count = _check_channel(client, api_key, channel, current_user, category)
                entry['new_videos'] = count
                total += count
            except YoutubeApiError as exc:
                # One channel's API failure shouldn't sink the whole run.
                db.session.rollback()
                entry['new_videos'] = 0
                entry['error'] = exc.message
                logger.warning('Channel %s check failed: %s',
                               channel.channel_id, exc.message)
            results.append(entry)

    return jsonify({'total_new_videos': total, 'channels': results})
