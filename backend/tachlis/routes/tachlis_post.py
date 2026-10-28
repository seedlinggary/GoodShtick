import json
import os
import re
from datetime import datetime, timedelta

from flask import Blueprint, jsonify, request
from sqlalchemy.orm import selectinload

from config import db
from security import token_required, token_optional, admin_required, super_admin_required
from backend.tachlis.modals.tachlis_post import TachlisPost, POST_TYPES, POST_STATUSES, EXPIRES_DAYS
from backend.tachlis.schemas.tachlis import make_tachlis_post_schema
from backend.user.modals.user import User
from backend.alerts.routes.alert import maybe_send_digests

tachlis_api = Blueprint('tachlis_api', __name__, url_prefix='/tachlis')

TACHLIS_SITE_URL = os.environ.get('TACHLIS_SITE_URL', 'https://www.gutmoney.com')

PAGE_SIZE = 20
TITLE_MAX = 150
BODY_MAX = 8000
CONTACT_MAX = 300
LOCATION_MAX = 120
COMPENSATION_MAX = 120
CATEGORY_MAX = 60


def _feed_options():
    return [selectinload(TachlisPost.user)]


def _admin_options():
    return [selectinload(TachlisPost.user), selectinload(TachlisPost.approver)]


def _validate_post_fields(body, partial=False):
    """Shared create/edit validation. Returns (errors_response_or_None, cleaned_fields)
    -- matches estates.py's _validate_listing_body convention: the error
    response carries no status of its own (`, None`, not `, 400`), because
    `return jsonify(...), 400` here would make THIS tuple itself the whole
    (error, fields) pair the caller destructures -- splitting 400 into
    `fields` instead of attaching it to the response, which silently made
    every validation failure answer 200 OK. The caller re-attaches the
    real status via `return error, 400`."""
    fields = {}

    if not partial or 'post_type' in body:
        post_type = (body.get('post_type') or '').strip().lower()
        if not post_type:
            return jsonify({'message': 'post_type is required'}), None
        if post_type not in POST_TYPES:
            return jsonify({'message': f'post_type must be one of: {", ".join(POST_TYPES)}'}), None
        fields['post_type'] = post_type

    if not partial or 'title' in body:
        title = (body.get('title') or '').strip()
        if not title:
            return jsonify({'message': 'Title is required'}), None
        if len(title) > TITLE_MAX:
            return jsonify({'message': f'Title must be {TITLE_MAX} characters or fewer'}), None
        fields['title'] = title

    if not partial or 'body' in body:
        text = (body.get('body') or '').strip()
        if not text:
            return jsonify({'message': 'Body is required'}), None
        if len(text) > BODY_MAX:
            return jsonify({'message': f'Body must be {BODY_MAX} characters or fewer'}), None
        fields['body'] = text

    if not partial or 'contact' in body:
        contact = (body.get('contact') or '').strip()
        if not contact:
            return jsonify({'message': 'Contact info is required'}), None
        if len(contact) > CONTACT_MAX:
            return jsonify({'message': f'Contact must be {CONTACT_MAX} characters or fewer'}), None
        fields['contact'] = contact

    if 'location' in body:
        location = (body.get('location') or '').strip()
        if len(location) > LOCATION_MAX:
            return jsonify({'message': f'Location must be {LOCATION_MAX} characters or fewer'}), None
        fields['location'] = location or None

    if 'compensation' in body:
        compensation = (body.get('compensation') or '').strip()
        if len(compensation) > COMPENSATION_MAX:
            return jsonify({'message': f'Compensation must be {COMPENSATION_MAX} characters or fewer'}), None
        fields['compensation'] = compensation or None

    if 'category' in body:
        category = (body.get('category') or '').strip()
        if len(category) > CATEGORY_MAX:
            return jsonify({'message': f'Category must be {CATEGORY_MAX} characters or fewer'}), None
        fields['category'] = category or None

    if 'remote' in body:
        val = body.get('remote')
        fields['remote'] = None if val is None else bool(val)

    if 'source_posted_at' in body:
        raw = body.get('source_posted_at')
        if raw:
            try:
                fields['source_posted_at'] = datetime.fromisoformat(raw)
            except (TypeError, ValueError):
                return jsonify({'message': 'source_posted_at must be an ISO 8601 datetime'}), None
        else:
            fields['source_posted_at'] = None

    return None, fields


def _slugify(name):
    """Matches backend/estates/modals/estates.py's own slugify() exactly --
    kept local rather than importing across blueprints for one tiny helper,
    same call so area slugs resolve identically either site."""
    import re
    import unicodedata
    normalized = unicodedata.normalize('NFKD', name).encode('ascii', 'ignore').decode('ascii')
    slug = re.sub(r'[^a-z0-9]+', '-', normalized.lower()).strip('-')
    return slug or 'area'


def _resolve_location(location_slug):
    """Same slug->exact-name resolution as estates.py's _resolve_area, over
    TachlisPost.location (the one area field this model has, no separate
    neighborhood/city split)."""
    now = datetime.utcnow()
    active = (TachlisPost.approved_to_publish.is_(True),
              db.or_(TachlisPost.expires_at.is_(None), TachlisPost.expires_at > now))
    locations = (db.session.query(TachlisPost.location)
                 .filter(TachlisPost.location.isnot(None), TachlisPost.location != '', *active)
                 .distinct().all())
    for (loc,) in locations:
        if _slugify(loc) == location_slug:
            return loc
    return None


@tachlis_api.route('/areas', methods=['GET'])
def list_areas():
    """Every active job location with its own post count -- feeds the
    sitemap (good-shtick/api/sitemap.js)."""
    now = datetime.utcnow()
    counts = dict(
        db.session.query(TachlisPost.location, db.func.count(TachlisPost.id))
        .filter(TachlisPost.approved_to_publish.is_(True),
                db.or_(TachlisPost.expires_at.is_(None), TachlisPost.expires_at > now),
                TachlisPost.location.isnot(None), TachlisPost.location != '')
        .group_by(TachlisPost.location).all())
    areas = [{'area': loc, 'area_slug': _slugify(loc), 'count': c} for loc, c in counts.items()]
    return jsonify({'areas': areas})


@tachlis_api.route('/areas/<location_slug>', methods=['GET'])
def area_page(location_slug):
    """Powers one "jobs in <location>" landing page per area -- live count
    and the newest 20 posts, grouped by category client-side. Stage 2 of
    gut_next_level_agent.md ("Neighborhood and city pages")."""
    name = _resolve_location(location_slug)
    if not name:
        return jsonify({'message': 'Area not found'}), 404

    now = datetime.utcnow()
    base_filter = db.and_(
        TachlisPost.location == name, TachlisPost.approved_to_publish.is_(True),
        db.or_(TachlisPost.expires_at.is_(None), TachlisPost.expires_at > now))

    count = TachlisPost.query.filter(base_filter).count()
    by_type = dict(
        db.session.query(TachlisPost.post_type, db.func.count(TachlisPost.id))
        .filter(base_filter).group_by(TachlisPost.post_type).all())
    posts = (TachlisPost.query.options(*_feed_options())
             .filter(base_filter)
             .order_by(db.func.coalesce(TachlisPost.source_posted_at, TachlisPost.pub_date).desc())
             .limit(20).all())

    schema = make_tachlis_post_schema(None, many=True, card=True)
    return jsonify({
        'area': name, 'area_slug': location_slug,
        'count': count, 'by_type': by_type,
        'posts': schema.dump(posts),
    })


class FilterError(ValueError):
    """Raised by _apply_post_filters on bad input -- the live route turns
    this into its existing 400 response; the alert digest job (see
    backend/alerts/routes/alert.py) catches it per-alert so one bad/stale
    saved search can't break the whole run."""


def _apply_post_filters(query, args):
    """Builds the exact same filtered query from `args` (a dict-like
    supporting .get(), e.g. request.args or a MultiDict rebuilt from an
    Alert's stored querystring) that /tachlis/posts itself uses -- the ONE
    place "what counts as a match" is defined, so a saved alert and the
    live board can never quietly drift apart. Does not touch
    approval/expiry/sort/pagination -- callers add those themselves."""
    post_type = (args.get('type') or '').strip().lower()
    q = (args.get('q') or '').strip()
    location = (args.get('location') or '').strip()
    category = (args.get('category') or '').strip()
    remote_only = args.get('remote') == '1'
    has_pay = args.get('has_pay') == '1'

    if post_type:
        if post_type not in POST_TYPES:
            raise FilterError(f'type must be one of: {", ".join(POST_TYPES)}')
        query = query.filter(TachlisPost.post_type == post_type)

    if location:
        query = query.filter(TachlisPost.location.ilike(location))

    if category:
        query = query.filter(TachlisPost.category.ilike(category))

    if remote_only:
        query = query.filter(TachlisPost.remote.is_(True))

    if has_pay:
        query = query.filter(TachlisPost.compensation.isnot(None), TachlisPost.compensation != '')

    if q:
        like = f'%{q}%'
        filters = [
            TachlisPost.title.ilike(like), TachlisPost.body.ilike(like),
            TachlisPost.location.ilike(like), TachlisPost.compensation.ilike(like),
            TachlisPost.contact.ilike(like), User.profile_name.ilike(like),
        ]
        if q.isdigit():
            filters.append(TachlisPost.id == int(q))
        query = query.join(TachlisPost.user).filter(db.or_(*filters))

    return query


@tachlis_api.route('/posts', methods=['GET'])
@token_optional
def list_posts(current_user):
    """Public board listing. Approved only, excludes expired.
    ?type=job|resume|service filters; ?page=1.. paginates; ?q=search-term filters
    by title/body/location/compensation/contact/author name or an exact id;
    ?location=exact-value filters to one of the distinct values /tachlis/locations
    returns; ?category=exact-value filters to one of the distinct values
    /tachlis/categories returns; ?remote=1 filters to remote-only jobs;
    ?has_pay=1 filters to posts with a compensation value set;
    ?sort=newest|oldest controls order (default newest)."""
    # Opportunistic fallback for the alert digest job -- see
    # backend/alerts/routes/alert.py's module docstring. Cheap (a
    # random-number check that's a no-op almost every call) and never
    # blocks this request.
    maybe_send_digests()

    sort = (request.args.get('sort') or 'newest').strip().lower()
    try:
        page = max(1, int(request.args.get('page', 1)))
    except (TypeError, ValueError):
        page = 1

    now = datetime.utcnow()
    query = (TachlisPost.query
             .options(*_feed_options())
             .filter(TachlisPost.approved_to_publish.is_(True))
             .filter(db.or_(TachlisPost.expires_at.is_(None), TachlisPost.expires_at > now)))
    try:
        query = _apply_post_filters(query, request.args)
    except FilterError as e:
        return jsonify({'message': str(e)}), 400

    # The time it actually went up in its source WhatsApp group when known
    # (Tab's daily imports), falling back to pub_date for on-site posts or
    # older imports from before source_posted_at existed -- see
    # TachlisPost.source_posted_at.
    newest_key = db.func.coalesce(TachlisPost.source_posted_at, TachlisPost.pub_date)
    order = newest_key.asc() if sort == 'oldest' else newest_key.desc()
    rows = (query
            .order_by(order)
            .limit(PAGE_SIZE + 1)
            .offset((page - 1) * PAGE_SIZE)
            .all())
    has_more = len(rows) > PAGE_SIZE
    posts = rows[:PAGE_SIZE]

    schema = make_tachlis_post_schema(current_user, many=True, card=True)
    return jsonify({'posts': schema.dump(posts), 'page': page, 'has_more': has_more})


@tachlis_api.route('/my/posts', methods=['GET'])
@token_required
def my_posts(current_user):
    """Stage 5's poster dashboard -- everything the current user has
    posted, including expired/filled ones, same "keep it visible to its
    own owner" reasoning as Estates' own /estates/my/listings."""
    rows = (TachlisPost.query.options(*_feed_options())
            .filter_by(user_id=current_user.public_id)
            .order_by(TachlisPost.pub_date.desc()).all())
    return jsonify({'posts': make_tachlis_post_schema(current_user, many=True).dump(rows)})


@tachlis_api.route('/talent', methods=['GET'])
def list_talent():
    """Stage 5's "open to work" card -- public browse of members who've
    opted in AND set a contact they're fine with employers seeing. Never
    exposes the account's own login email -- only what's in cv_contact,
    which the member fills in themselves (see User.cv_contact)."""
    rows = (User.query
            .filter(User.open_to_work.is_(True))
            .filter(User.cv_contact.isnot(None), User.cv_contact != '')
            .order_by(User.last_login.desc().nullslast())
            .limit(100).all())
    return jsonify({'talent': [{
        'public_id': u.public_id,
        'profile_name': u.profile_name,
        'line_of_work': u.line_of_work,
        'cv_summary': u.cv_summary,
        'cv_contact': u.cv_contact,
    } for u in rows]})


_EMAIL_RE = re.compile(r'^[^\s@]+@[^\s@]+\.[^\s@]+$')


@tachlis_api.route('/posts/<int:post_id>/apply', methods=['POST'])
@token_required
def apply_to_post(current_user, post_id):
    """Stage 5's "one-tap apply" -- sends the applicant's name/email/CV
    summary to the employer's own contact when it's an email address (via
    Resend, same sender as every other email this project sends). A
    phone/WhatsApp/link contact can't be emailed server-side, so the
    response instead hands the frontend a pre-filled message to open that
    same contact method with -- still one tap, just through whichever
    channel the poster actually gave."""
    post = db.session.get(TachlisPost, post_id)
    if not post or post.post_type != 'job':
        return jsonify({'message': 'This post is not accepting applications'}), 404
    if post.is_expired or post.status != 'active':
        return jsonify({'message': 'This job post is no longer active'}), 400

    body = request.get_json(silent=True) or {}
    note = (body.get('note') or '').strip()[:1000]
    applicant_name = current_user.profile_name or f'{current_user.first_name} {current_user.last_name}'.strip()
    contact = (post.contact or '').strip()

    if _EMAIL_RE.match(contact):
        from backend.alerts import emails
        try:
            emails.send_job_application_email(
                contact, post.title, applicant_name, current_user.email,
                current_user.cv_summary or '', note,
            )
        except Exception as exc:
            return jsonify({'message': f'Could not send your application: {exc}'}), 502
        return jsonify({'sent': True, 'method': 'email'})

    message = f'Hi, I\'m applying for "{post.title}" on GUT Money\'s Job Board.' + (f' {note}' if note else '')
    return jsonify({'sent': False, 'method': 'manual', 'contact': contact, 'message': message})


@tachlis_api.route('/locations', methods=['GET'])
def list_locations():
    """Distinct, non-empty locations among approved/non-expired posts, for the
    board's location filter dropdown -- small board, cheap to compute fresh
    on every call rather than caching."""
    now = datetime.utcnow()
    rows = (db.session.query(TachlisPost.location)
            .filter(TachlisPost.approved_to_publish.is_(True))
            .filter(db.or_(TachlisPost.expires_at.is_(None), TachlisPost.expires_at > now))
            .filter(TachlisPost.location.isnot(None), TachlisPost.location != '')
            .distinct()
            .all())
    locations = sorted({loc for (loc,) in rows}, key=str.lower)
    return jsonify({'locations': locations})


@tachlis_api.route('/categories', methods=['GET'])
def list_categories():
    """Distinct, non-empty categories among approved/non-expired posts, for
    the board's category filter dropdown -- same pattern as /tachlis/locations."""
    now = datetime.utcnow()
    rows = (db.session.query(TachlisPost.category)
            .filter(TachlisPost.approved_to_publish.is_(True))
            .filter(db.or_(TachlisPost.expires_at.is_(None), TachlisPost.expires_at > now))
            .filter(TachlisPost.category.isnot(None), TachlisPost.category != '')
            .distinct()
            .all())
    categories = sorted({c for (c,) in rows}, key=str.lower)
    return jsonify({'categories': categories})


@tachlis_api.route('/posts/<int:post_id>', methods=['GET'])
@token_optional
def get_post(current_user, post_id):
    """Single post. Visible if approved, or to its own author, or to an admin."""
    post = (TachlisPost.query
            .options(*_feed_options())
            .filter_by(id=post_id)
            .first())
    if not post:
        return jsonify({'message': 'Post not found'}), 404

    is_owner = current_user and post.user_id == current_user.public_id
    is_admin_viewer = current_user and current_user.is_boss
    if post.approved_to_publish is not True and not is_owner and not is_admin_viewer:
        return jsonify({'message': 'Post not found'}), 404

    post.views_count = (post.views_count or 0) + 1
    db.session.commit()

    schema = make_tachlis_post_schema(current_user, many=False, card=False)
    return jsonify(schema.dump(post))


def _can_manage_post(post, user):
    return bool(user and (post.user_id == user.public_id or user.is_boss))


@tachlis_api.route('/posts/<int:post_id>/renew', methods=['POST'])
@token_required
def renew_post(current_user, post_id):
    """Stage 5's poster dashboard "renew" -- a fresh full lifetime from now
    (see TachlisPost.renew)."""
    post = db.session.get(TachlisPost, post_id)
    if not post:
        return jsonify({'message': 'Post not found'}), 404
    if not _can_manage_post(post, current_user):
        return jsonify({'message': 'Not authorized'}), 403
    post.renew()
    db.session.commit()
    return jsonify(make_tachlis_post_schema(current_user).dump(post))


@tachlis_api.route('/posts/<int:post_id>/status', methods=['PATCH'])
@token_required
def set_post_status(current_user, post_id):
    """Stage 5's poster dashboard "mark filled" -- same reasoning as
    Estates' own set_listing_status: a non-'active' status also expires
    the post immediately, reusing list_posts' existing expiry exclusion."""
    post = db.session.get(TachlisPost, post_id)
    if not post:
        return jsonify({'message': 'Post not found'}), 404
    if not _can_manage_post(post, current_user):
        return jsonify({'message': 'Not authorized'}), 403
    body = request.get_json(silent=True) or {}
    status = body.get('status')
    if status not in POST_STATUSES:
        return jsonify({'message': f'status must be one of: {", ".join(POST_STATUSES)}'}), 400
    post.status = status
    if status != 'active':
        post.expires_at = datetime.utcnow()
    db.session.commit()
    return jsonify(make_tachlis_post_schema(current_user).dump(post))


@tachlis_api.route('/posts/<int:post_id>/contact-tap', methods=['POST'])
def track_post_contact_tap(post_id):
    """Fire-and-forget beacon, same reasoning as Estates' track_contact_tap."""
    post = db.session.get(TachlisPost, post_id)
    if post:
        post.contact_taps = (post.contact_taps or 0) + 1
        db.session.commit()
    return jsonify({'ok': True})


STILL_AVAILABLE_AGE_DAYS = 14
STILL_AVAILABLE_HIDE_AFTER_DAYS = 4


def check_still_available():
    """Stage 5's "Still available?" check, job posts only (a resume isn't
    "unavailable" the same way an opening is -- it keeps its normal 90-day
    expiry without this extra nagging layer). OFF by default; only ever
    called from the explicit cron endpoint once a super admin turns it on
    -- see AlertDigestSchedule.still_available_check_enabled and Estates'
    own check_still_available() for the identical two-pass shape."""
    now = datetime.utcnow()
    candidates = (TachlisPost.query
                  .filter(TachlisPost.post_type == 'job')
                  .filter(TachlisPost.status == 'active')
                  .filter(db.or_(TachlisPost.expires_at.is_(None), TachlisPost.expires_at > now))
                  .filter(TachlisPost.still_available_confirmed_at.is_(None))
                  .all())

    import secrets
    from backend.alerts import emails

    asked = 0
    hidden = 0
    for post in candidates:
        poster_email = post.user.email if post.user else None
        if not poster_email:
            continue

        if post.still_available_reminder_sent_at is None:
            age_days = (now - (post.source_posted_at or post.pub_date)).days
            if age_days < STILL_AVAILABLE_AGE_DAYS:
                continue
            if not post.still_available_token:
                post.still_available_token = secrets.token_urlsafe(32)
            try:
                emails.send_still_available_email(
                    poster_email, post.title,
                    f'{TACHLIS_SITE_URL}/still-available/confirm/{post.still_available_token}',
                    'Gut Money',
                )
            except Exception:
                continue
            post.still_available_reminder_sent_at = now
            asked += 1
        else:
            wait_days = (now - post.still_available_reminder_sent_at).days
            if wait_days < STILL_AVAILABLE_HIDE_AFTER_DAYS:
                continue
            post.expires_at = now
            hidden += 1

    db.session.commit()
    return {'candidates': len(candidates), 'reminders_sent': asked, 'hidden': hidden}


@tachlis_api.route('/still-available/confirm/<token>', methods=['GET'])
def confirm_still_available(token):
    post = TachlisPost.query.filter_by(still_available_token=token).first()
    if not post:
        return jsonify({'message': 'This link is invalid or has already been used.'}), 404
    post.still_available_confirmed_at = datetime.utcnow()
    post.still_available_reminder_sent_at = None
    db.session.commit()
    return jsonify({'message': 'Confirmed -- thanks!', 'title': post.title})


@tachlis_api.route('/posts/sitemap-data', methods=['GET'])
def sitemap_data():
    """Minimal {id, updated} rows for every approved, non-expired post --
    same lean-query pattern as business.py's own sitemap_data(), feeds
    good-shtick/api/sitemap.js. Expired listings are excluded the same way
    the live listing feed excludes them (see list_posts above)."""
    now = datetime.utcnow()
    rows = (db.session.query(TachlisPost.id, TachlisPost.pub_date)
            .filter(TachlisPost.approved_to_publish.is_(True))
            .filter(db.or_(TachlisPost.expires_at.is_(None), TachlisPost.expires_at > now)).all())
    return jsonify({
        'posts': [{'id': pid, 'updated': pub_date.isoformat() if pub_date else None} for pid, pub_date in rows],
    })


PARSE_DRAFT_MAX_CHARS = 4000
PARSE_DRAFT_MIN_CHARS = 20


def _post_draft_system_prompt():
    return (
        "You turn a free-text job/resume post (often copy-pasted from a WhatsApp group, "
        "in Hebrew or English, sometimes both mixed) into a structured draft for a job board. "
        "Respond ONLY with a single JSON object with exactly these keys:\n"
        "- is_real_post: true only if the text actually describes a real job opening or a real "
        "person's own job search (concrete enough to post). If the text is too short, random, "
        "unrelated, or you're not confident it's genuine, set this to false and leave every "
        "other field null/empty -- NEVER invent a plausible-sounding job/resume from text that "
        "doesn't actually describe one, even if asked for an example.\n"
        "- post_type: \"job\" if this is an employer/recruiter post offering work, \"resume\" if this is "
        "a job-seeker describing their own availability/skills.\n"
        "- title: a short, job-board-style title (e.g. \"Part-time bookkeeper, Beit Shemesh\"), under 150 characters.\n"
        "- body: the rest of the post's useful detail, cleaned up into readable prose.\n"
        "- location: a city/area if mentioned, else null.\n"
        "- compensation: pay/rate/salary as written if mentioned, else null.\n"
        "- category: a short job field/category (e.g. \"Tech\", \"Healthcare\", \"Education\", \"Sales\"), best guess from context.\n"
        "- remote: true if explicitly remote/work-from-home, false if explicitly on-site, null if unclear.\n"
        "- contact: whatever contact info (phone/email/WhatsApp/link) is given, as written, else empty string.\n\n"
        "Never invent information that isn't in the text -- use null/empty for anything not actually stated. "
        "Do not wrap the JSON in markdown fences. Return valid JSON only."
    )


@tachlis_api.route('/posts/parse-draft', methods=['POST'])
@token_required
def parse_post_draft(_current_user):
    """Stage 5's "post in 60 seconds, or forward it" -- turns a pasted
    WhatsApp post into a pre-filled draft for Tachlis.js's CreatePostForm,
    which the member reviews/edits before ever actually publishing (this
    endpoint never creates a post itself)."""
    body = request.get_json(silent=True) or {}
    text = (body.get('text') or '').strip()
    if len(text) < PARSE_DRAFT_MIN_CHARS:
        return jsonify({'message': 'Paste some more detail -- that\'s too short to read as a real post.'}), 400
    text = text[:PARSE_DRAFT_MAX_CHARS]

    if not os.environ.get('OPENAI_API_KEY'):
        return jsonify({'message': 'This feature is not configured on the server yet.'}), 500

    from openai import OpenAI
    client = OpenAI()
    try:
        resp = client.chat.completions.create(
            model='gpt-4o-mini',
            messages=[
                {'role': 'system', 'content': _post_draft_system_prompt()},
                {'role': 'user', 'content': text},
            ],
            response_format={'type': 'json_object'},
            temperature=0.2,
            max_tokens=700,
        )
        data = json.loads((resp.choices[0].message.content or '').strip())
    except Exception:
        return jsonify({'message': "Couldn't read that post -- try pasting it again, or fill in the form by hand."}), 502

    if not data.get('is_real_post'):
        return jsonify({'message': "That doesn't read like a real job/resume post -- try pasting more detail, or fill in the form by hand."}), 422

    if data.get('post_type') not in POST_TYPES:
        data['post_type'] = 'job'
    data.pop('is_real_post', None)
    return jsonify(data)


@tachlis_api.route('/posts', methods=['POST'])
@token_required
def create_post(current_user):
    body = request.get_json() or {}
    error, fields = _validate_post_fields(body, partial=False)
    if error:
        return error, 400

    post = TachlisPost(
        post_type=fields['post_type'],
        title=fields['title'],
        body=fields['body'],
        contact=fields['contact'],
        user_id=current_user.public_id,
        location=fields.get('location'),
        compensation=fields.get('compensation'),
        category=fields.get('category'),
        remote=fields.get('remote'),
        source_posted_at=fields.get('source_posted_at'),
        expires_at=datetime.utcnow() + timedelta(days=EXPIRES_DAYS[fields['post_type']]),
    )

    # Same bypass create_shtick already uses for admin/super_admin posters --
    # everyone else's post leaves approved_to_publish at its default (None,
    # pending) for the moderation queue below. This is what lets an
    # automated bot account (logged in as admin/super_admin) post listings
    # that go live immediately instead of waiting on manual approval.
    if current_user.is_boss:
        post.approved_to_publish = True
        post.approved_by = current_user.public_id

    db.session.add(post)
    db.session.commit()
    schema = make_tachlis_post_schema(current_user, many=False, card=False)
    return jsonify(schema.dump(post)), 201


@tachlis_api.route('/posts/<int:post_id>', methods=['PATCH'])
@token_required
def edit_post(current_user, post_id):
    post = db.session.get(TachlisPost, post_id)
    if not post:
        return jsonify({'message': 'Post not found'}), 404
    if post.user_id != current_user.public_id and not current_user.is_boss:
        return jsonify({'message': 'Not authorized'}), 403

    body = request.get_json() or {}
    error, fields = _validate_post_fields(body, partial=True)
    if error:
        return error, 400

    for key, value in fields.items():
        setattr(post, key, value)

    db.session.commit()
    schema = make_tachlis_post_schema(current_user, many=False, card=False)
    return jsonify(schema.dump(post))


@tachlis_api.route('/posts/<int:post_id>', methods=['DELETE'])
@token_required
def delete_post(current_user, post_id):
    post = db.session.get(TachlisPost, post_id)
    if not post:
        return jsonify({'message': 'Post not found'}), 404
    if post.user_id != current_user.public_id and not current_user.is_boss:
        return jsonify({'message': 'Not authorized'}), 403
    db.session.delete(post)
    db.session.commit()
    return jsonify({'message': 'Deleted'})


# ── Admin moderation routes ─────────────────────────────────────────────────

@tachlis_api.route('/admin/posts', methods=['GET'])
@admin_required
def admin_all_posts(_current_user):
    posts = (TachlisPost.query
             .options(*_admin_options())
             .order_by(TachlisPost.pub_date.desc())
             .limit(200).all())
    schema = make_tachlis_post_schema(_current_user, many=True, card=False)
    return jsonify(schema.dump(posts))


@tachlis_api.route('/admin/pending', methods=['GET'])
@admin_required
def get_pending(_current_user):
    pending = (TachlisPost.query
               .options(*_admin_options())
               .filter_by(approved_to_publish=None)
               .order_by(TachlisPost.pub_date.desc()).all())
    schema = make_tachlis_post_schema(_current_user, many=True, card=False)
    return jsonify(schema.dump(pending))


@tachlis_api.route('/admin/posts/<int:post_id>/approve', methods=['POST'])
@admin_required
def approve_post(current_user, post_id):
    body = request.get_json() or {}
    post = db.session.get(TachlisPost, post_id)
    if not post:
        return jsonify({'message': 'Not found'}), 404
    approved = not body.get('reject', False)
    post.approved_to_publish = approved
    post.approved_by = current_user.public_id
    db.session.commit()
    return jsonify({'message': 'approved' if approved else 'rejected'})


@tachlis_api.route('/admin/posts/<int:post_id>/unapprove', methods=['POST'])
@super_admin_required
def unapprove_post(_current_user, post_id):
    """Revert an already-approved (or rejected) post back to the pending queue."""
    post = db.session.get(TachlisPost, post_id)
    if not post:
        return jsonify({'message': 'Not found'}), 404
    post.approved_to_publish = None
    post.approved_by = None
    db.session.commit()
    return jsonify({'message': 'unapproved'})
