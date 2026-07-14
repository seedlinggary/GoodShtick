from datetime import datetime

from flask import Blueprint, jsonify, request
from sqlalchemy.orm import selectinload

from config import db
from security import token_required, token_optional, super_admin_required
from backend.hock.modals.hock_post import HockPost
from backend.hock.modals.hock_comment import HockComment
from backend.hock.modals.hock_like import HockCommentLike
from backend.hock.schemas.hock import make_comment_schema
from backend.notifications.helpers import notify

hock_comment_api = Blueprint('hock_comment_api', __name__, url_prefix='/hock')


@hock_comment_api.route('/posts/<int:post_id>/comments', methods=['GET'])
@token_optional
def get_comments(current_user, post_id):
    """Top-level comments for a post, each with its nested reply subtree.
    (The post-detail endpoint already embeds this; kept for standalone use.)"""
    if not db.session.get(HockPost, post_id):
        return jsonify({'message': 'Post not found'}), 404
    query = (HockComment.query
             .options(
                 selectinload(HockComment.user),
                 selectinload(HockComment.likes),
                 # One level of eager-loaded replies covers the common
                 # case (top-level comment + direct replies) without an
                 # N+1 per reply; a reply-to-a-reply beyond that still
                 # lazy-loads -- SQLAlchemy has no clean way to eager-load
                 # a self-referential relationship to arbitrary depth.
                 selectinload(HockComment.replies).selectinload(HockComment.user),
                 selectinload(HockComment.replies).selectinload(HockComment.likes),
             )
             .filter_by(hock_post_id=post_id, parent_comment_id=None))
    if not (current_user and current_user.is_boss):
        query = query.filter_by(approved_to_publish=True)
    top_level = query.order_by(HockComment.pub_date.asc()).all()
    schema = make_comment_schema(current_user, many=True)
    return jsonify(schema.dump(top_level))


@hock_comment_api.route('/comments', methods=['POST'])
@token_required
def add_comment(current_user):
    body = request.get_json() or {}
    text = (body.get('text') or '').strip()
    post_id = body.get('hock_post_id')
    if not text or not post_id:
        return jsonify({'message': 'text and hock_post_id are required'}), 400

    post = db.session.get(HockPost, post_id)
    if not post:
        return jsonify({'message': 'Post not found'}), 404

    parent_id = body.get('parent_comment_id')
    parent = None
    if parent_id:
        parent = db.session.get(HockComment, parent_id)
        if not parent or parent.hock_post_id != post.id:
            # A reply must attach to a comment that lives on this same post.
            return jsonify({'message': 'Parent comment does not belong to this post'}), 400

    comment = HockComment(
        text=text,
        hock_post_id=post.id,
        user_id=current_user.public_id,
        parent_comment_id=parent_id or None,
    )
    db.session.add(comment)

    # Notify the parent comment's author when replying to a comment, otherwise
    # the post's author. notify() no-ops on self-notification.
    if parent:
        notify(
            parent.user_id,
            f'{current_user.profile_name} replied to your comment on "{post.title[:40]}"',
            type='hock_comment',
            actor_id=current_user.public_id,
            link=f'/hock/post/{post.id}',
        )
    else:
        notify(
            post.user_id,
            f'{current_user.profile_name} commented on your Hock post "{post.title[:40]}"',
            type='hock_comment',
            actor_id=current_user.public_id,
            link=f'/hock/post/{post.id}',
        )

    db.session.commit()
    schema = make_comment_schema(current_user, many=False)
    return jsonify(schema.dump(comment)), 201


@hock_comment_api.route('/comments/<int:comment_id>', methods=['PATCH'])
@token_required
def edit_comment(current_user, comment_id):
    comment = db.session.get(HockComment, comment_id)
    if not comment:
        return jsonify({'message': 'Comment not found'}), 404
    if comment.user_id != current_user.public_id:
        return jsonify({'message': 'Not authorized'}), 403

    body = request.get_json() or {}
    new_text = (body.get('text') or '').strip()
    if not new_text:
        return jsonify({'message': 'Comment cannot be empty'}), 400
    comment.text = new_text
    comment.edited_at = datetime.utcnow()
    db.session.commit()
    schema = make_comment_schema(current_user, many=False)
    return jsonify(schema.dump(comment))


@hock_comment_api.route('/comments/<int:comment_id>', methods=['DELETE'])
@token_required
def delete_comment(current_user, comment_id):
    comment = db.session.get(HockComment, comment_id)
    if not comment:
        return jsonify({'message': 'Comment not found'}), 404
    if comment.user_id != current_user.public_id and not current_user.is_boss:
        return jsonify({'message': 'Not authorized'}), 403
    # Cascade-deletes the whole reply subtree via the model's cascade config.
    # The frontend confirms before firing this when a comment has replies.
    db.session.delete(comment)
    db.session.commit()
    return jsonify({'message': 'Deleted'})


@hock_comment_api.route('/comments/<int:comment_id>/like', methods=['POST'])
@token_required
def toggle_comment_like(current_user, comment_id):
    comment = db.session.get(HockComment, comment_id)
    if not comment:
        return jsonify({'message': 'Comment not found'}), 404

    existing = HockCommentLike.query.filter_by(
        hock_comment_id=comment_id, user_id=current_user.public_id).first()
    if existing:
        db.session.delete(existing)
        db.session.commit()
        count = HockCommentLike.query.filter_by(hock_comment_id=comment_id).count()
        return jsonify({'liked': False, 'like_count': count})

    db.session.add(HockCommentLike(hock_comment_id=comment_id, user_id=current_user.public_id))
    notify(
        comment.user_id,
        f'{current_user.profile_name} liked your comment',
        type='hock_like',
        actor_id=current_user.public_id,
        link=f'/hock/post/{comment.hock_post_id}',
    )
    db.session.commit()
    count = HockCommentLike.query.filter_by(hock_comment_id=comment_id).count()
    return jsonify({'liked': True, 'like_count': count}), 201


@hock_comment_api.route('/admin/comments', methods=['GET'])
@super_admin_required
def admin_all_comments(current_user):
    comments = (HockComment.query
                .options(selectinload(HockComment.user))
                .order_by(HockComment.pub_date.desc())
                .limit(200).all())
    schema = make_comment_schema(current_user, many=True)
    return jsonify(schema.dump(comments))


@hock_comment_api.route('/admin/comments/<int:comment_id>/unapprove', methods=['POST'])
@super_admin_required
def unapprove_comment(_current_user, comment_id):
    """Hide a Hock comment from public view without deleting it."""
    comment = db.session.get(HockComment, comment_id)
    if not comment:
        return jsonify({'message': 'Not found'}), 404
    comment.approved_to_publish = False
    db.session.commit()
    return jsonify({'message': 'unapproved'})


@hock_comment_api.route('/admin/comments/<int:comment_id>/approve', methods=['POST'])
@super_admin_required
def approve_comment(_current_user, comment_id):
    """Restore a hidden Hock comment to public view."""
    comment = db.session.get(HockComment, comment_id)
    if not comment:
        return jsonify({'message': 'Not found'}), 404
    comment.approved_to_publish = True
    db.session.commit()
    return jsonify({'message': 'approved'})
