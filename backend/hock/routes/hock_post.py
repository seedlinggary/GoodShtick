from datetime import datetime

from flask import Blueprint, jsonify, request
from sqlalchemy.orm import selectinload

from config import db
from security import token_required, token_optional, super_admin_required
from backend.hock.modals.hock_post import HockPost
from backend.hock.modals.hock_comment import HockComment
from backend.hock.modals.hock_like import HockPostLike
from backend.hock.schemas.hock import make_post_schema
from backend.notifications.helpers import notify
from backend.user.modals.user import User
from upload import upload_file

hock_post_api = Blueprint('hock_post_api', __name__, url_prefix='/hock')

PAGE_SIZE = 10
TITLE_MAX = 200


def _feed_options():
    """Eager-load author + likes + comments so counting them is one query each,
    not N+1 across the page."""
    return [
        selectinload(HockPost.user),
        selectinload(HockPost.likes),
        selectinload(HockPost.comments),
    ]


def _hot_score(post, now):
    likes = len(post.likes)
    comments = len(post.comments)
    hours = max(0.0, (now - (post.pub_date or now)).total_seconds() / 3600.0)
    return (likes + comments * 0.5) / ((hours + 2) ** 1.5)


def _apply_search(query, q):
    """Matches title/body, the author's display name, or an exact id."""
    like = f'%{q}%'
    filters = [HockPost.title.ilike(like), HockPost.body.ilike(like), User.profile_name.ilike(like)]
    if q.isdigit():
        filters.append(HockPost.id == int(q))
    return query.join(HockPost.user).filter(db.or_(*filters))


@hock_post_api.route('/posts', methods=['GET'])
@token_optional
def list_posts(current_user):
    """Paginated feed. ?sort=new|top|hot & ?page=1.. & ?q=search-term — returns
    {posts, page, has_more}. `new` paginates at the DB; `top`/`hot` need global
    ordering by engagement so they load the set and rank in Python (fine at v1
    scale — O(n), not quadratic; noted for later if the table grows large)."""
    sort = (request.args.get('sort') or 'new').lower()
    q = (request.args.get('q') or '').strip()
    try:
        page = max(1, int(request.args.get('page', 1)))
    except (TypeError, ValueError):
        page = 1

    ctx_user = current_user  # None when logged out — liked_by_me stays False

    if sort == 'new':
        base = HockPost.query.options(*_feed_options()).filter(HockPost.approved_to_publish.is_(True))
        if q:
            base = _apply_search(base, q)
        # Fetch one extra to know whether another page exists.
        rows = (base
                .order_by(HockPost.pub_date.desc())
                .limit(PAGE_SIZE + 1)
                .offset((page - 1) * PAGE_SIZE)
                .all())
        has_more = len(rows) > PAGE_SIZE
        posts = rows[:PAGE_SIZE]
    else:
        base = HockPost.query.options(*_feed_options()).filter(HockPost.approved_to_publish.is_(True))
        if q:
            base = _apply_search(base, q)
        all_posts = base.all()
        now = datetime.utcnow()
        if sort == 'top':
            all_posts.sort(key=lambda p: (len(p.likes), p.pub_date or now), reverse=True)
        else:  # hot (default fallback for anything unrecognised)
            all_posts.sort(key=lambda p: _hot_score(p, now), reverse=True)
        start = (page - 1) * PAGE_SIZE
        posts = all_posts[start:start + PAGE_SIZE]
        has_more = len(all_posts) > start + PAGE_SIZE

    schema = make_post_schema(ctx_user, many=True, card=True)
    return jsonify({'posts': schema.dump(posts), 'page': page, 'has_more': has_more})


@hock_post_api.route('/posts/<int:post_id>', methods=['GET'])
@token_optional
def get_post(current_user, post_id):
    """Single post with the full nested comment tree.

    Comments come back as a tree: top-level comments each carry a `replies`
    array, recursing to arbitrary depth (built by HockPostSchema.get_comments).
    """
    post = (HockPost.query
            .options(
                selectinload(HockPost.user),
                selectinload(HockPost.likes),
                # Comments come back as a flat collection and get built into a
                # tree in Python (HockPostSchema.get_comments/get_replies), so
                # eager-loading each comment's own user+likes here covers
                # every depth of the tree in one shot -- without this, every
                # comment AND every nested reply cost a separate query each.
                selectinload(HockPost.comments).selectinload(HockComment.user),
                selectinload(HockPost.comments).selectinload(HockComment.likes),
            )
            .filter_by(id=post_id)
            .first())
    if not post:
        return jsonify({'message': 'Post not found'}), 404

    is_owner = current_user and post.user_id == current_user.public_id
    is_admin_viewer = current_user and current_user.is_boss
    if not post.approved_to_publish and not is_owner and not is_admin_viewer:
        return jsonify({'message': 'Post not found'}), 404

    schema = make_post_schema(current_user, many=False, card=False)
    return jsonify(schema.dump(post))


@hock_post_api.route('/posts', methods=['POST'])
@token_required
def create_post(current_user):
    body = request.get_json() or {}
    title = (body.get('title') or '').strip()
    text = (body.get('body') or '').strip()
    if not title or not text:
        return jsonify({'message': 'Title and body are required'}), 400
    if len(title) > TITLE_MAX:
        return jsonify({'message': f'Title must be {TITLE_MAX} characters or fewer'}), 400

    post = HockPost(
        title=title,
        body=text,
        user_id=current_user.public_id,
        image=body.get('image') or None,
    )
    db.session.add(post)
    db.session.commit()
    schema = make_post_schema(current_user, many=False, card=True)
    return jsonify(schema.dump(post)), 201


@hock_post_api.route('/posts/<int:post_id>', methods=['PATCH'])
@token_required
def edit_post(current_user, post_id):
    post = db.session.get(HockPost, post_id)
    if not post:
        return jsonify({'message': 'Post not found'}), 404
    if post.user_id != current_user.public_id:
        return jsonify({'message': 'Not authorized'}), 403

    body = request.get_json() or {}
    if 'title' in body:
        new_title = (body.get('title') or '').strip()
        if not new_title:
            return jsonify({'message': 'Title cannot be empty'}), 400
        if len(new_title) > TITLE_MAX:
            return jsonify({'message': f'Title must be {TITLE_MAX} characters or fewer'}), 400
        post.title = new_title
    if 'body' in body:
        new_body = (body.get('body') or '').strip()
        if not new_body:
            return jsonify({'message': 'Body cannot be empty'}), 400
        post.body = new_body
    if 'image' in body:
        post.image = body.get('image') or None

    post.edited_at = datetime.utcnow()
    db.session.commit()
    schema = make_post_schema(current_user, many=False, card=False)
    return jsonify(schema.dump(post))


@hock_post_api.route('/posts/<int:post_id>', methods=['DELETE'])
@token_required
def delete_post(current_user, post_id):
    post = db.session.get(HockPost, post_id)
    if not post:
        return jsonify({'message': 'Post not found'}), 404
    if post.user_id != current_user.public_id and not current_user.is_boss:
        return jsonify({'message': 'Not authorized'}), 403
    # Comments + likes cascade-delete via the model's cascade='all, delete-orphan'.
    db.session.delete(post)
    db.session.commit()
    return jsonify({'message': 'Deleted'})


@hock_post_api.route('/posts/<int:post_id>/like', methods=['POST'])
@token_required
def toggle_post_like(current_user, post_id):
    post = db.session.get(HockPost, post_id)
    if not post:
        return jsonify({'message': 'Post not found'}), 404

    existing = HockPostLike.query.filter_by(
        hock_post_id=post_id, user_id=current_user.public_id).first()
    if existing:
        db.session.delete(existing)
        db.session.commit()
        count = HockPostLike.query.filter_by(hock_post_id=post_id).count()
        return jsonify({'liked': False, 'like_count': count})

    db.session.add(HockPostLike(hock_post_id=post_id, user_id=current_user.public_id))
    notify(
        post.user_id,
        f'{current_user.profile_name} liked your Hock post "{post.title[:40]}"',
        type='hock_like',
        actor_id=current_user.public_id,
        link=f'/hock/post/{post_id}',
    )
    db.session.commit()
    count = HockPostLike.query.filter_by(hock_post_id=post_id).count()
    return jsonify({'liked': True, 'like_count': count}), 201


@hock_post_api.route('/upload', methods=['POST'])
@token_required
def add_upload(_current_user):
    """Reuses the shared Supabase upload pipeline — same as /shtick/upload."""
    filename = upload_file(request)
    if not filename:
        return jsonify({'message': 'Upload failed'}), 400
    return jsonify(filename)


# ── Super-admin moderation ──────────────────────────────────────────────────
# Hock posts auto-publish on creation (no pre-publish queue) -- these routes
# only give super_admin a reversible takedown/restore switch.

@hock_post_api.route('/admin/posts', methods=['GET'])
@super_admin_required
def admin_list_posts(current_user):
    posts = (HockPost.query
             .options(*_feed_options())
             .order_by(HockPost.pub_date.desc())
             .limit(200).all())
    schema = make_post_schema(current_user, many=True, card=True)
    return jsonify(schema.dump(posts))


@hock_post_api.route('/admin/posts/<int:post_id>/unapprove', methods=['POST'])
@super_admin_required
def unapprove_post(current_user, post_id):
    post = db.session.get(HockPost, post_id)
    if not post:
        return jsonify({'message': 'Not found'}), 404
    post.approved_to_publish = False
    post.approved_by = current_user.public_id
    db.session.commit()
    return jsonify({'message': 'unapproved'})


@hock_post_api.route('/admin/posts/<int:post_id>/approve', methods=['POST'])
@super_admin_required
def approve_post(current_user, post_id):
    post = db.session.get(HockPost, post_id)
    if not post:
        return jsonify({'message': 'Not found'}), 404
    post.approved_to_publish = True
    post.approved_by = current_user.public_id
    db.session.commit()
    return jsonify({'message': 'approved'})
