"""AI content generation for the SuperAdmin dashboard.

Generates short-form posts via the OpenAI API and drops them into the existing
pending-approval queue (Shtick.approved_to_publish left as None) for a human
admin to review before they go live. Super-admin only.

Blueprint:  ai_content_api   (url_prefix='/content-pipeline/ai')
Registered centrally in application.py — do NOT register here.
"""

import base64
import difflib
import json
import logging
import os
import re
import tempfile
import uuid

import httpx
from flask import Blueprint, jsonify, request

from config import db
from security import super_admin_required
from backend.shtick.modals.shtick import Shtick
from backend.shtick.modals.content import Content
from backend.shtick.modals.picture import Picture
from backend.shtick.modals.generalc import Generalc
from backend.content_pipeline.routes.scraper import _download_and_store_image
from upload import _get_bucket

logger = logging.getLogger(__name__)

ai_content_api = Blueprint('ai_content_api', __name__, url_prefix='/content-pipeline/ai')

# DB field limits (see backend/shtick/modals/shtick.py) — hard caps so inserts
# never truncate/fail. We ask the model to stay under these, then belt-and-braces
# truncate on our side too.
CAPTION_MAX = 120   # Shtick.caption (post title)
CREDIT_MAX = 125    # Shtick.credit (source attribution)

MAX_COUNT = 50      # sanity cap on a single batch

# ── Duplicate prevention ──────────────────────────────────────────────────
# GPT models strongly converge on the same "classic" jokes/quotes for a
# generic prompt (e.g. every "Dad Jokes" run kept getting the same
# scarecrow/egg jokes) unless explicitly told what's already been used.
# Two layers: (1) the prompt itself lists recent titles from this category to
# steer the model away from repeating them, (2) a hard similarity check
# rejects and retries anything that slips through anyway -- applies to every
# category, not just the ones this was first noticed on.
DEDUP_LOOKBACK = 150         # how many past posts in this category to check against
DEDUP_PROMPT_SAMPLE = 20     # how many recent titles to show the model as "avoid these"
DEDUP_SIMILARITY_THRESHOLD = 0.72
MAX_DEDUP_ATTEMPTS = 4       # regenerate this many times before giving up on one slot


def _normalize_for_dedup(text):
    return re.sub(r'[^a-z0-9\s]', '', (text or '').lower()).strip()


def _is_near_duplicate(title, body, known_normalized):
    candidate = _normalize_for_dedup(f'{title} {body}')
    return any(
        difflib.SequenceMatcher(None, candidate, known).ratio() >= DEDUP_SIMILARITY_THRESHOLD
        for known in known_normalized
    )


def _existing_category_content(category_id):
    """(titles, normalized-title+body strings) for every post ever generated
    in this category (any approval state -- a duplicate is a duplicate
    whether the earlier one was approved, rejected, or still pending)."""
    rows = (
        Shtick.query
        .filter_by(generalc_id=category_id)
        .order_by(Shtick.pub_date.desc())
        .limit(DEDUP_LOOKBACK)
        .all()
    )
    titles = [s.caption for s in rows if s.caption]
    normalized = [
        _normalize_for_dedup(f'{s.caption} {s.content.stuff if s.content else ""}')
        for s in rows
    ]
    return titles, normalized


def _is_jewish_category(category_name):
    """Shared by the text prompt and the image prompt so the two can never
    drift apart -- only the site's specifically Jewish/religious categories
    (name contains "jewish" or "religious") get Jewish theming."""
    lower = (category_name or '').strip().lower()
    return 'jewish' in lower or 'religious' in lower


def _system_prompt(category_name, avoid_titles=None):
    """Build the instruction prompt for one post in the given category.

    Works generically for any category name an admin may have created; the
    three ORIGINAL Jewish-themed categories get Jewish-specific steering.
    Everything else (any other category an admin creates later, e.g. "Dad
    Jokes") gets a fully neutral, non-religious instruction -- the Jewish
    framing must be opt-in per category, not a blanket identity applied to
    every generation regardless of what the category is actually about (this
    used to bleed "Jewish-themed" into completely unrelated categories, e.g.
    "Dad Jokes" coming back as rabbi/matzo jokes instead of regular puns).

    `avoid_titles`: recent titles already used in this category (this batch
    and past runs) -- GPT strongly converges on the same "classic" jokes/
    quotes for a generic prompt otherwise, so telling it what's already been
    used is the first line of defense against duplicates (a hard similarity
    check on the actual output is the second, in the caller).
    """
    name = (category_name or '').strip()
    lower = name.lower()
    is_jewish_category = _is_jewish_category(name)

    if is_jewish_category and 'funny' in lower:
        identity = "You are a content writer for 'Gut Shtick', a wholesome Jewish content website."
        theme = (
            "a short, genuinely funny and good-natured joke or anecdote with a "
            "Jewish-religious angle. Keep it warm and clever, never mean-spirited "
            "or offensive."
        )
    elif is_jewish_category and ('feel good' in lower or 'feel-good' in lower):
        identity = "You are a content writer for 'Gut Shtick', a wholesome Jewish content website."
        theme = (
            "a short, uplifting and heartwarming story or teaching rooted in "
            "Jewish religious tradition that leaves the reader encouraged."
        )
    elif is_jewish_category and 'wisdom' in lower:
        identity = "You are a content writer for 'Gut Shtick', a wholesome Jewish content website."
        theme = (
            "a meaningful, thought-provoking quote or short teaching of Jewish "
            "religious wisdom."
        )
    elif 'how to' in lower or 'how-to' in lower:
        # The generic branch below's "family-friendly" identity line (meant as
        # "appropriate for all ages") was apparently enough on its own, paired
        # with an open-ended category name, to steer this toward family/
        # parenting/holiday-planning topics almost every time -- give it a
        # concrete, varied topic domain and an explicit steer away from that
        # instead of leaving "How To" to guess what it means.
        identity = "You are a content writer for 'Gut Shtick', a general-audience content website."
        theme = (
            "a short, practical how-to guide that teaches the reader to MAKE, "
            "BUILD, FIX, or DO something concrete -- a real skill, task, or "
            "project. Pick ONE specific topic from a genuinely wide range: "
            "cooking/baking, a home or car repair, a DIY or craft project, a "
            "money or budgeting trick, a tech or productivity tip, a fitness "
            "or outdoor skill, a gardening task, an organizing/cleaning "
            "method, or a useful everyday life skill. Do NOT default to "
            "family, parenting, holiday, or event-planning topics -- those "
            "should be rare, not the norm. Most posts should be a skill "
            "anyone could use regardless of family situation."
        )
    else:
        identity = "You are a content writer for 'Gut Shtick', a wholesome, family-friendly content website."
        theme = (
            f"a short piece of tasteful, high-quality content that fits the "
            f"category \"{name}\". Write general-audience content that matches "
            f"exactly what the category name says -- do NOT add a religious, "
            f"Jewish, or any other cultural/thematic spin unless the category "
            f"name itself explicitly calls for one."
        )

    avoid_block = ''
    if avoid_titles:
        listed = "\n".join(f'  - "{t}"' for t in avoid_titles)
        avoid_block = (
            "\n\nIMPORTANT: The following titles/premises have ALREADY been used in this "
            "category -- do not repeat any of them, and do not generate a close variant or "
            "reword of any of them (e.g. the same joke/quote with a different setup). Come up "
            f"with something genuinely different:\n{listed}\n"
        )

    return (
        identity + " Generate " + theme + avoid_block + "\n\n"
        "Respond ONLY with a single JSON object with exactly these keys:\n"
        '  "title": a short catchy title, at most 110 characters.\n'
        '  "body": the full text of the post (the joke / story / quote / teaching).\n'
        '  "source": a good-faith source attribution — e.g. "Talmud, Tractate '
        "Berachot\", \"Pirkei Avot 2:4\", \"Rabbi Nachman of Breslov\", or "
        "\"Traditional teaching\" for Jewish-themed categories; for anything else "
        "use whatever fits (e.g. \"Original\", \"Classic joke\") or \"Traditional\" "
        "if nothing more specific applies. This field must NEVER be empty; "
        "always provide something.\n\n"
        "Do not wrap the JSON in markdown fences. Return valid JSON only."
    )


def _generate_one(client, category_name, avoid_titles=None):
    """Call the chat API for one post and return (title, body, source).

    Raises on API error; raises ValueError on unparseable/empty output so the
    caller can count it as a failure and continue the batch.
    """
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": _system_prompt(category_name, avoid_titles)},
            {"role": "user", "content": f"Generate one post for the category: {category_name}"},
        ],
        response_format={"type": "json_object"},
        temperature=1.0,
        max_tokens=600,
    )
    raw = (resp.choices[0].message.content or '').strip()
    data = json.loads(raw)  # JSON mode guarantees valid JSON, but guard anyway

    title = (data.get('title') or '').strip()
    body = (data.get('body') or '').strip()
    source = (data.get('source') or '').strip()

    if not title or not body:
        raise ValueError('Model returned empty title or body')
    if not source:
        source = 'Traditional teaching'

    return title[:CAPTION_MAX], body, source[:CREDIT_MAX]


PEXELS_SEARCH_URL = 'https://api.pexels.com/v1/search'


def _get_pexels_api_key():
    key = os.environ.get('PEXELS_API_KEY')
    return key.strip() if key else None


def _search_pexels_photo_url(http_client, query):
    """One real photo matching `query` via Pexels' free API (no cost, no
    per-request billing, ~no rate-limit concerns at this volume). Returns a
    direct image URL, or None on a missing key / no results / any failure --
    an image is always optional, never worth sinking a post over."""
    api_key = _get_pexels_api_key()
    if not api_key:
        return None
    try:
        resp = http_client.get(
            PEXELS_SEARCH_URL,
            headers={'Authorization': api_key},
            params={'query': query, 'per_page': 1},
            timeout=15,
        )
        resp.raise_for_status()
        photos = (resp.json() or {}).get('photos') or []
        if not photos:
            return None
        src = photos[0].get('src') or {}
        return src.get('large') or src.get('original')
    except Exception as exc:  # noqa: BLE001 -- image is optional, log and skip
        logger.warning('Pexels search failed for %r: %s', query, exc)
        return None


def _generate_image_filename(openai_client, http_client, title, category_name):
    """Get an image for the post, upload it to Supabase, return the stored
    filename. Returns None on any failure — an image is a nice-to-have and
    must never sink the whole post.

    Tries a real photo from Pexels first for anything that isn't Jewish-
    themed (a search on the post's own title) -- a real, specific photograph
    reads as far less "generic" than another AI illustration for something
    like "How To" or "Fun Facts", and it's free. Only falls back to AI
    generation (gpt-image-1) if Pexels has no key configured, finds nothing
    for that title, or the source category IS Jewish-themed (where a
    generated illustration can actually match the content better than
    whatever stock photography happens to exist for it).
    """
    if not _is_jewish_category(category_name):
        photo_url = _search_pexels_photo_url(http_client, title)
        if photo_url:
            stored = _download_and_store_image(http_client, photo_url)
            if stored:
                return stored
        # Falls through to AI generation below if Pexels had no key, no
        # match, or the download/upload failed.

    try:
        # This used to say "wholesome Jewish post" unconditionally for every
        # category -- unlike _system_prompt's text generation, it had no
        # is_jewish_category gate at all, so a "How To" (or "Dad Jokes",
        # "Tech", etc.) post's illustration was still steered toward
        # Jewish/family imagery regardless of what the post was actually
        # about. Mirrors _system_prompt's same check now.
        if _is_jewish_category(category_name):
            subject = "a wholesome Jewish post"
        else:
            subject = f'a wholesome, general-audience post in the category "{category_name}"'
        prompt = (
            f"A tasteful, warm, respectful illustration for {subject} "
            f"titled '{title}'. Beautiful, uplifting, appropriate for all "
            f"ages, and visually matching what the title is actually about "
            f"-- do not add religious or Jewish imagery unless the post "
            f"itself is Jewish-themed. No text, no words, no letters in "
            f"the image."
        )
        img = openai_client.images.generate(
            model="gpt-image-1",
            prompt=prompt,
            size="1024x1024",
            n=1,
        )
        img_bytes = base64.b64decode(img.data[0].b64_json)

        fname = f'{uuid.uuid4()}.png'
        # Mirror upload_file()'s write-to-temp-then-upload flow, but cross-platform
        # (upload_file hardcodes /tmp) and for raw bytes rather than a Flask upload.
        # Still force /tmp when it exists (Vercel/Linux) rather than trusting
        # auto-detection, same reasoning as scraper.py's _download_and_store_image.
        tmp_dir = '/tmp' if os.path.isdir('/tmp') else None
        fd, tmp_path = tempfile.mkstemp(suffix='.png', dir=tmp_dir)
        try:
            with os.fdopen(fd, 'wb') as fh:
                fh.write(img_bytes)
            _get_bucket().upload(
                fname, tmp_path, {"content-type": "image/png"}
            )
        finally:
            os.remove(tmp_path)
        return fname
    except Exception as exc:  # noqa: BLE001 — image is optional, log and skip
        logger.warning('AI image generation/upload failed: %s', exc)
        return None


@ai_content_api.route('/categories', methods=['GET'])
@super_admin_required
def list_categories(_current_user):
    """Thin passthrough of categories for the dropdown. (The public GET /generalc
    also works; this is provided for convenience and stays super-admin scoped.)"""
    cats = Generalc.query.order_by(Generalc.name.asc()).all()
    return jsonify([{'id': c.id, 'name': c.name} for c in cats])


@ai_content_api.route('/generate', methods=['POST'])
@super_admin_required
def generate(current_user):
    body = request.get_json(silent=True) or {}

    category_id = body.get('category_id')
    if not category_id:
        return jsonify({'message': 'category_id is required'}), 400

    category = db.session.get(Generalc, category_id)
    if not category:
        return jsonify({'message': 'Category not found'}), 404

    try:
        count = int(body.get('count', 20))
    except (TypeError, ValueError):
        return jsonify({'message': 'count must be a number'}), 400
    if count < 1:
        return jsonify({'message': 'count must be at least 1'}), 400
    count = min(count, MAX_COUNT)

    include_image = bool(body.get('include_image', False))

    if not os.environ.get('OPENAI_API_KEY'):
        return jsonify({'message': 'OpenAI API key is not configured on the server'}), 500

    # Imported lazily so the module still imports even if the openai package or
    # key is missing in some environment — only /generate actually needs it.
    from openai import OpenAI
    client = OpenAI()

    created = 0
    failed = 0
    duplicates_skipped = 0

    # Seed with everything already generated for this category (any approval
    # state) so a fresh run doesn't repeat a joke/quote from a previous batch,
    # not just within this one.
    known_titles, known_normalized = _existing_category_content(category.id)

    # One shared client for every Pexels search + image download in this
    # batch, instead of opening a fresh connection per post.
    with httpx.Client(timeout=20) as http_client:
        for i in range(count):
            title = text = source = None
            for attempt in range(MAX_DEDUP_ATTEMPTS):
                try:
                    candidate_title, candidate_text, candidate_source = _generate_one(
                        client, category.name, avoid_titles=known_titles[:DEDUP_PROMPT_SAMPLE]
                    )
                except Exception as exc:  # noqa: BLE001 — one bad post shouldn't kill the batch
                    logger.warning('AI post generation failed (%d/%d, attempt %d): %s',
                                    i + 1, count, attempt + 1, exc)
                    continue
                if _is_near_duplicate(candidate_title, candidate_text, known_normalized):
                    logger.info('Discarding near-duplicate AI post (%d/%d, attempt %d): %s',
                                i + 1, count, attempt + 1, candidate_title)
                    duplicates_skipped += 1
                    continue
                title, text, source = candidate_title, candidate_text, candidate_source
                break

            if title is None:
                failed += 1
                continue

            # Track it immediately so later slots in *this* batch also avoid it,
            # not just posts from before the batch started.
            known_titles.insert(0, title)
            known_normalized.append(_normalize_for_dedup(f'{title} {text}'))

            try:
                picture_name = None
                if include_image:
                    picture_name = _generate_image_filename(client, http_client, title, category.name)

                new_shtick = Shtick(
                    caption=title,
                    credit=source,
                    specific_category=None,
                    user_id=current_user.public_id,
                    generalc_id=category.id,
                )
                # approved_to_publish intentionally left as its default (None) so the
                # post lands in the pending-approval queue.
                db.session.add(new_shtick)
                db.session.flush()  # need new_shtick.id for the child rows

                if category not in new_shtick.categories:
                    new_shtick.categories.append(category)

                db.session.add(Content(stuff=text, shtick_id=new_shtick.id))
                if picture_name:
                    db.session.add(Picture(name=picture_name, shtick_id=new_shtick.id))

                db.session.commit()  # commit per-post so a later failure never rolls back earlier work
                created += 1
            except Exception as exc:  # noqa: BLE001
                db.session.rollback()
                failed += 1
                logger.warning('Persisting AI post failed (%d/%d): %s', i + 1, count, exc)
                continue

    return jsonify({
        'created': created,
        'failed': failed,
        'duplicates_skipped': duplicates_skipped,
        'category': category.name,
    })
