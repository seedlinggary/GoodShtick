import os
import secrets

from flask import Blueprint, jsonify, request
from sqlalchemy import func
from sqlalchemy.orm import selectinload

from config import db
from security import token_required, token_optional, admin_required, super_admin_required
from upload import upload_file
from backend.torah.modals.torah import (
    TorahPost, TorahPostPhoto, TorahPostLike,
    POST_TYPES, CATEGORIES, MAX_PHOTOS, slugify, extract_youtube_id,
)
from backend.torah.schemas.torah import TorahPostCardSchema, make_post_schema

torah_post_api = Blueprint('torah_post_api', __name__, url_prefix='/torah')

PAGE_SIZE = 24
TITLE_MAX = 150
BODY_MAX = 8000
GUEST_EMAIL_MAX = 150
GUEST_PHONE_MAX = 40
MAIN_SITE_URL = os.environ.get('MAIN_SITE_URL', 'https://www.gutshtick.com')


def _feed_options():
    return [selectinload(TorahPost.photos), selectinload(TorahPost.likes)]


def _can_manage(post, user):
    if not user:
        return False
    if user.is_boss:
        return True
    return post.created_by == user.public_id


def _unique_slug(title):
    base = slugify(title)
    rows = {row[0] for row in db.session.query(TorahPost.slug).filter(TorahPost.slug.like(f'{base}%')).all()}
    if base not in rows:
        return base
    n = 2
    while f'{base}-{n}' in rows:
        n += 1
    return f'{base}-{n}'


def _validate_body(body, partial=False):
    fields = {}

    if not partial or 'post_type' in body:
        post_type = (body.get('post_type') or '').strip().lower()
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

    if 'body_text' in body:
        text = (body.get('body_text') or '').strip()
        if len(text) > BODY_MAX:
            return jsonify({'message': f'Text must be {BODY_MAX} characters or fewer'}), None
        fields['body_text'] = text or None

    if 'youtube_url' in body:
        raw = (body.get('youtube_url') or '').strip()
        if raw:
            video_id = extract_youtube_id(raw)
            if not video_id:
                return jsonify({'message': "Could not find a YouTube video id in that URL"}), None
            fields['youtube_video_id'] = video_id
        else:
            fields['youtube_video_id'] = None

    if 'category' in body:
        category = (body.get('category') or 'other').strip().lower()
        if category not in CATEGORIES:
            return jsonify({'message': f'category must be one of: {", ".join(CATEGORIES)}'}), None
        fields['category'] = category

    return None, fields


@torah_post_api.route('/categories', methods=['GET'])
def list_categories():
    return jsonify({'post_types': list(POST_TYPES), 'categories': list(CATEGORIES), 'max_photos': MAX_PHOTOS})


@torah_post_api.route('/stats', methods=['GET'])
def torah_stats():
    approved = TorahPost.approved_to_publish.is_(True)
    total = TorahPost.query.filter(approved).count()
    by_category = dict(db.session.query(TorahPost.category, func.count(TorahPost.id)).filter(approved).group_by(TorahPost.category).all())
    contributors = db.session.query(func.count(func.distinct(TorahPost.created_by))).filter(TorahPost.created_by.isnot(None), approved).scalar() or 0
    return jsonify({'posts': total, 'contributors': contributors, 'by_category': by_category})


@torah_post_api.route('/posts', methods=['GET'])
@token_optional
def list_posts(current_user):
    post_type = (request.args.get('post_type') or '').strip().lower()
    category = (request.args.get('category') or '').strip().lower()
    q = (request.args.get('q') or '').strip()
    sort = (request.args.get('sort') or 'random').strip().lower()
    try:
        page = max(1, int(request.args.get('page', 1)))
    except (TypeError, ValueError):
        page = 1

    query = TorahPost.query.options(*_feed_options()).filter(TorahPost.approved_to_publish.is_(True))
    if post_type:
        if post_type not in POST_TYPES:
            return jsonify({'message': f'post_type must be one of: {", ".join(POST_TYPES)}'}), 400
        query = query.filter(TorahPost.post_type == post_type)
    if category:
        if category not in CATEGORIES:
            return jsonify({'message': f'category must be one of: {", ".join(CATEGORIES)}'}), 400
        query = query.filter(TorahPost.category == category)
    if q:
        like = f'%{q}%'
        query = query.filter(db.or_(TorahPost.title.ilike(like), TorahPost.body_text.ilike(like)))

    total = query.count()
    if sort == 'newest':
        query = query.order_by(TorahPost.pub_date.desc())
    elif sort == 'alpha':
        query = query.order_by(TorahPost.title.asc())
    else:
        query = query.order_by(func.random())

    rows = query.limit(PAGE_SIZE + 1).offset((page - 1) * PAGE_SIZE).all()
    has_more = len(rows) > PAGE_SIZE
    posts = rows[:PAGE_SIZE]

    return jsonify({'posts': TorahPostCardSchema(many=True).dump(posts), 'page': page, 'has_more': has_more, 'total': total})


@torah_post_api.route('/posts/<identifier>', methods=['GET'])
@token_optional
def get_post(current_user, identifier):
    query = TorahPost.query.options(*_feed_options())
    post = query.filter_by(id=int(identifier)).first() if identifier.isdigit() else query.filter_by(slug=identifier).first()
    if not post:
        return jsonify({'message': 'Post not found'}), 404

    if post.approved_to_publish is not True and not _can_manage(post, current_user):
        return jsonify({'message': 'Post not found'}), 404

    post.views_count = (post.views_count or 0) + 1
    db.session.commit()
    return jsonify(make_post_schema(current_user).dump(post))


@torah_post_api.route('/posts/<identifier>/seo', methods=['GET'])
def get_post_seo(identifier):
    """Same lookup as get_post, for the SEO meta-injection proxy (see
    good-shtick/api/render.js) -- split out so a search crawler or link
    unfurl hitting every post page doesn't inflate views_count alongside
    genuine reader visits."""
    query = TorahPost.query.options(*_feed_options())
    post = query.filter_by(id=int(identifier)).first() if identifier.isdigit() else query.filter_by(slug=identifier).first()
    if not post or post.approved_to_publish is not True:
        return jsonify({'message': 'Post not found'}), 404
    return jsonify(TorahPostCardSchema().dump(post))


@torah_post_api.route('/posts/sitemap-data', methods=['GET'])
def posts_sitemap_data():
    """Minimal {slug, updated} rows for every approved post -- same
    lean-query pattern as the other sites' own sitemap_data()."""
    rows = (db.session.query(TorahPost.slug, TorahPost.pub_date)
            .filter(TorahPost.approved_to_publish.is_(True)).all())
    return jsonify({
        'posts': [{'slug': slug, 'updated': pub_date.isoformat() if pub_date else None} for slug, pub_date in rows],
    })


@torah_post_api.route('/posts', methods=['POST'])
@token_required
def create_post(current_user):
    body = request.get_json() or {}
    error, fields = _validate_body(body, partial=False)
    if error:
        return error, 400

    photos = body.get('photos')
    if photos is not None and (not isinstance(photos, list) or len(photos) > MAX_PHOTOS):
        return jsonify({'message': f'photos must be a list of at most {MAX_PHOTOS} filenames'}), 400

    post = TorahPost(
        slug=_unique_slug(fields['title']), created_by=current_user.public_id,
        approved_to_publish=True, **fields,
    )
    db.session.add(post)
    db.session.flush()
    for i, filename in enumerate((photos or [])[:MAX_PHOTOS]):
        if filename:
            db.session.add(TorahPostPhoto(post_id=post.id, filename=filename, position=i))
    db.session.commit()
    return jsonify(make_post_schema(current_user).dump(post)), 201


@torah_post_api.route('/posts/<int:post_id>', methods=['PATCH'])
@token_required
def edit_post(current_user, post_id):
    post = db.session.get(TorahPost, post_id)
    if not post:
        return jsonify({'message': 'Post not found'}), 404
    if not _can_manage(post, current_user):
        return jsonify({'message': 'Not authorized'}), 403

    body = request.get_json() or {}
    error, fields = _validate_body(body, partial=True)
    if error:
        return error, 400
    for key, value in fields.items():
        setattr(post, key, value)

    if 'photos' in body:
        photos = body.get('photos')
        if photos is not None and (not isinstance(photos, list) or len(photos) > MAX_PHOTOS):
            return jsonify({'message': f'photos must be a list of at most {MAX_PHOTOS} filenames'}), 400
        for photo in list(post.photos):
            db.session.delete(photo)
        db.session.flush()
        for i, filename in enumerate(photos or []):
            if filename:
                db.session.add(TorahPostPhoto(post_id=post.id, filename=filename, position=i))

    db.session.commit()
    return jsonify(make_post_schema(current_user).dump(post))


@torah_post_api.route('/posts/<int:post_id>', methods=['DELETE'])
@token_required
def delete_post(current_user, post_id):
    post = db.session.get(TorahPost, post_id)
    if not post:
        return jsonify({'message': 'Post not found'}), 404
    if not _can_manage(post, current_user):
        return jsonify({'message': 'Not authorized'}), 403
    db.session.delete(post)
    db.session.commit()
    return jsonify({'message': 'Deleted'})


# ── Guest (no-account) post routes ──────────────────────────────────────────
# "Post without an account" -- anyone can share a dvar Torah with just an
# email or phone; it lands pending (approved_to_publish=None, excluded from
# list_posts/get_post above) until approved, and the guest manages it
# afterward via a private emailed magic link (guest_manage_token) -- same
# token-lookup-is-the-auth shape as every other domain's guest routes.

@torah_post_api.route('/posts/guest', methods=['POST'])
def create_guest_post():
    body = request.get_json() or {}
    error, fields = _validate_body(body, partial=False)
    if error:
        return error, 400

    photos = body.get('photos')
    if photos is not None and (not isinstance(photos, list) or len(photos) > MAX_PHOTOS):
        return jsonify({'message': f'photos must be a list of at most {MAX_PHOTOS} filenames'}), 400

    guest_email = (body.get('guest_email') or '').strip()[:GUEST_EMAIL_MAX]
    guest_phone = (body.get('guest_phone') or '').strip()[:GUEST_PHONE_MAX]
    if not (guest_email or guest_phone):
        return jsonify({'message': 'At least one of guest_email or guest_phone is required'}), 400

    from backend.guest.modals.guest_throttle import check_and_record_guest_submission
    if not check_and_record_guest_submission(request):
        return jsonify({'message': 'Too many submissions from this network today -- please try again tomorrow.'}), 429

    post = TorahPost(
        slug=_unique_slug(fields['title']), created_by=None,
        approved_to_publish=None,
        guest_email=guest_email or None,
        guest_phone=guest_phone or None,
        guest_manage_token=secrets.token_urlsafe(32),
        **fields,
    )
    db.session.add(post)
    db.session.flush()
    for i, filename in enumerate((photos or [])[:MAX_PHOTOS]):
        if filename:
            db.session.add(TorahPostPhoto(post_id=post.id, filename=filename, position=i))
    db.session.commit()

    if guest_email:
        try:
            from backend.alerts import emails
            emails.send_guest_submission_email(
                guest_email, 'your Torah post', post.title,
                f'{MAIN_SITE_URL}/guest/torah/{post.guest_manage_token}',
            )
        except Exception:
            pass  # an email failure should never break the actual submission

    schema = make_post_schema(None)
    # guest_manage_token is never on the schema itself (would leak into any
    # public/admin dump that reuses it) -- added back only on this one
    # create response, which only the submitter ever sees.
    data = schema.dump(post)
    data['guest_manage_token'] = post.guest_manage_token
    return jsonify(data), 201


@torah_post_api.route('/posts/guest/<token>', methods=['GET'])
def get_guest_post(token):
    post = TorahPost.query.options(*_feed_options()).filter_by(guest_manage_token=token).first()
    if not post:
        return jsonify({'message': 'Post not found'}), 404
    return jsonify(make_post_schema(None).dump(post))


@torah_post_api.route('/posts/guest/<token>', methods=['PATCH'])
def edit_guest_post(token):
    post = TorahPost.query.filter_by(guest_manage_token=token).first()
    if not post:
        return jsonify({'message': 'Post not found'}), 404

    body = request.get_json() or {}
    error, fields = _validate_body(body, partial=True)
    if error:
        return error, 400
    for key, value in fields.items():
        setattr(post, key, value)

    if 'photos' in body:
        photos = body.get('photos')
        if photos is not None and (not isinstance(photos, list) or len(photos) > MAX_PHOTOS):
            return jsonify({'message': f'photos must be a list of at most {MAX_PHOTOS} filenames'}), 400
        for photo in list(post.photos):
            db.session.delete(photo)
        db.session.flush()
        for i, filename in enumerate(photos or []):
            if filename:
                db.session.add(TorahPostPhoto(post_id=post.id, filename=filename, position=i))

    db.session.commit()
    return jsonify(make_post_schema(None).dump(post))


@torah_post_api.route('/posts/guest/<token>', methods=['DELETE'])
def delete_guest_post(token):
    post = TorahPost.query.filter_by(guest_manage_token=token).first()
    if not post:
        return jsonify({'message': 'Post not found'}), 404
    db.session.delete(post)
    db.session.commit()
    return jsonify({'message': 'Deleted'})


@torah_post_api.route('/posts/<int:post_id>/like', methods=['POST'])
@token_required
def like_post(current_user, post_id):
    post = db.session.get(TorahPost, post_id)
    if not post:
        return jsonify({'message': 'Post not found'}), 404
    existing = TorahPostLike.query.filter_by(post_id=post_id, user_id=current_user.public_id).first()
    if not existing:
        db.session.add(TorahPostLike(post_id=post_id, user_id=current_user.public_id))
        db.session.commit()
    return jsonify({'liked': True})


@torah_post_api.route('/posts/<int:post_id>/like', methods=['DELETE'])
@token_required
def unlike_post(current_user, post_id):
    like = TorahPostLike.query.filter_by(post_id=post_id, user_id=current_user.public_id).first()
    if like:
        db.session.delete(like)
        db.session.commit()
    return jsonify({'liked': False})


@torah_post_api.route('/my/posts', methods=['GET'])
@token_required
def my_posts(current_user):
    rows = (TorahPost.query.options(*_feed_options())
            .filter_by(created_by=current_user.public_id)
            .order_by(TorahPost.pub_date.desc()).all())
    return jsonify({'posts': make_post_schema(current_user, many=True).dump(rows)})


@torah_post_api.route('/upload', methods=['POST'])
@token_required
def torah_upload(_current_user):
    """Reuses the shared Supabase upload pipeline -- same as /business/upload
    and /estates/upload."""
    filename = upload_file(request)
    if not filename:
        return jsonify({'message': 'Upload failed'}), 400
    return jsonify(filename)


# ── Admin moderation routes ─────────────────────────────────────────────────
# Brand new for Torah -- unlike most other content types, there was no
# existing approve/reject mechanism to piggyback on (every post simply went
# live immediately). Same reject_flag shape (one approve_url, POST body
# {reject: bool}) as the other domains that added a gate from scratch
# (Estates/Business/Marketplace/Community/Group Buy).

@torah_post_api.route('/admin/posts/pending', methods=['GET'])
@admin_required
def get_pending_posts(_current_user):
    pending = (TorahPost.query.options(*_feed_options())
               .filter_by(approved_to_publish=None)
               .order_by(TorahPost.pub_date.asc()).all())
    return jsonify(make_post_schema(None, many=True).dump(pending))


@torah_post_api.route('/admin/posts/<int:post_id>/approve', methods=['POST'])
@admin_required
def approve_post(_current_user, post_id):
    post = db.session.get(TorahPost, post_id)
    if not post:
        return jsonify({'message': 'Not found'}), 404
    body = request.get_json(silent=True) or {}
    approved = not body.get('reject', False)
    post.approved_to_publish = approved
    db.session.commit()
    return jsonify({'message': 'approved' if approved else 'rejected'})


@torah_post_api.route('/admin/posts/<int:post_id>/unapprove', methods=['POST'])
@super_admin_required
def unapprove_post(_current_user, post_id):
    """Revert an already-approved (or rejected) post back to the pending queue."""
    post = db.session.get(TorahPost, post_id)
    if not post:
        return jsonify({'message': 'Not found'}), 404
    post.approved_to_publish = None
    db.session.commit()
    return jsonify({'message': 'unapproved'})
