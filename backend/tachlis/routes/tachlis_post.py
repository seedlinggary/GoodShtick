from datetime import datetime, timedelta

from flask import Blueprint, jsonify, request
from sqlalchemy.orm import selectinload

from config import db
from security import token_required, token_optional, admin_required, super_admin_required
from backend.tachlis.modals.tachlis_post import TachlisPost, POST_TYPES
from backend.tachlis.schemas.tachlis import make_tachlis_post_schema
from backend.user.modals.user import User

tachlis_api = Blueprint('tachlis_api', __name__, url_prefix='/tachlis')

PAGE_SIZE = 20
TITLE_MAX = 150
BODY_MAX = 8000
CONTACT_MAX = 300
LOCATION_MAX = 120
COMPENSATION_MAX = 120
EXPIRES_DAYS = 60


def _feed_options():
    return [selectinload(TachlisPost.user)]


def _admin_options():
    return [selectinload(TachlisPost.user), selectinload(TachlisPost.approver)]


def _validate_post_fields(body, partial=False):
    """Shared create/edit validation. Returns (errors_response_or_None, cleaned_fields)."""
    fields = {}

    if not partial or 'post_type' in body:
        post_type = (body.get('post_type') or '').strip().lower()
        if not post_type:
            return jsonify({'message': 'post_type is required'}), 400
        if post_type not in POST_TYPES:
            return jsonify({'message': f'post_type must be one of: {", ".join(POST_TYPES)}'}), 400
        fields['post_type'] = post_type

    if not partial or 'title' in body:
        title = (body.get('title') or '').strip()
        if not title:
            return jsonify({'message': 'Title is required'}), 400
        if len(title) > TITLE_MAX:
            return jsonify({'message': f'Title must be {TITLE_MAX} characters or fewer'}), 400
        fields['title'] = title

    if not partial or 'body' in body:
        text = (body.get('body') or '').strip()
        if not text:
            return jsonify({'message': 'Body is required'}), 400
        if len(text) > BODY_MAX:
            return jsonify({'message': f'Body must be {BODY_MAX} characters or fewer'}), 400
        fields['body'] = text

    if not partial or 'contact' in body:
        contact = (body.get('contact') or '').strip()
        if not contact:
            return jsonify({'message': 'Contact info is required'}), 400
        if len(contact) > CONTACT_MAX:
            return jsonify({'message': f'Contact must be {CONTACT_MAX} characters or fewer'}), 400
        fields['contact'] = contact

    if 'location' in body:
        location = (body.get('location') or '').strip()
        if len(location) > LOCATION_MAX:
            return jsonify({'message': f'Location must be {LOCATION_MAX} characters or fewer'}), 400
        fields['location'] = location or None

    if 'compensation' in body:
        compensation = (body.get('compensation') or '').strip()
        if len(compensation) > COMPENSATION_MAX:
            return jsonify({'message': f'Compensation must be {COMPENSATION_MAX} characters or fewer'}), 400
        fields['compensation'] = compensation or None

    return None, fields


@tachlis_api.route('/posts', methods=['GET'])
@token_optional
def list_posts(current_user):
    """Public board listing. Approved only, excludes expired, most-recent-first.
    ?type=job|resume|service filters; ?page=1.. paginates; ?q=search-term filters
    by title/body/location/compensation/contact/author name or an exact id."""
    post_type = (request.args.get('type') or '').strip().lower()
    q = (request.args.get('q') or '').strip()
    try:
        page = max(1, int(request.args.get('page', 1)))
    except (TypeError, ValueError):
        page = 1

    now = datetime.utcnow()
    query = (TachlisPost.query
             .options(*_feed_options())
             .filter(TachlisPost.approved_to_publish.is_(True))
             .filter(db.or_(TachlisPost.expires_at.is_(None), TachlisPost.expires_at > now)))

    if post_type:
        if post_type not in POST_TYPES:
            return jsonify({'message': f'type must be one of: {", ".join(POST_TYPES)}'}), 400
        query = query.filter(TachlisPost.post_type == post_type)

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

    rows = (query
            .order_by(TachlisPost.pub_date.desc())
            .limit(PAGE_SIZE + 1)
            .offset((page - 1) * PAGE_SIZE)
            .all())
    has_more = len(rows) > PAGE_SIZE
    posts = rows[:PAGE_SIZE]

    schema = make_tachlis_post_schema(current_user, many=True, card=True)
    return jsonify({'posts': schema.dump(posts), 'page': page, 'has_more': has_more})


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

    schema = make_tachlis_post_schema(current_user, many=False, card=False)
    return jsonify(schema.dump(post))


@tachlis_api.route('/posts', methods=['POST'])
@token_required
def create_post(current_user):
    body = request.get_json() or {}
    error, fields = _validate_post_fields(body, partial=False)
    if error:
        return error

    post = TachlisPost(
        post_type=fields['post_type'],
        title=fields['title'],
        body=fields['body'],
        contact=fields['contact'],
        user_id=current_user.public_id,
        location=fields.get('location'),
        compensation=fields.get('compensation'),
        expires_at=datetime.utcnow() + timedelta(days=EXPIRES_DAYS),
    )
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
        return error

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
