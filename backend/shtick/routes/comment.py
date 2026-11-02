import os

from flask import Blueprint, jsonify, request
from config import db
from security import token_required, token_optional, admin_required
from backend.shtick.modals.comment import Comment
from backend.shtick.modals.shtick import Shtick
from backend.shtick.schemas.shtick import comment_schema, comments_schema
from backend.notifications.helpers import notify

comment_api = Blueprint('comment_api', __name__, url_prefix='/comment')

GUEST_EMAIL_MAX = 150
GUEST_PHONE_MAX = 40
MAIN_SITE_URL = os.environ.get('MAIN_SITE_URL', 'https://www.gutshtick.com')


@comment_api.route('/<int:shtick_id>', methods=['GET'])
@token_optional
def get_comments(current_user, shtick_id):
    query = Comment.query.filter_by(shtick_id=shtick_id)
    if not (current_user and current_user.is_boss):
        query = query.filter_by(approved_to_publish=True)
    comments = query.order_by(Comment.pub_date.asc()).all()
    return jsonify(comments_schema.dump(comments))


@comment_api.route('', methods=['POST'])
@token_required
def add_comment(current_user):
    body = request.get_json()
    if not body or not body.get('text') or not body.get('shtick_id'):
        return jsonify({'message': 'text and shtick_id are required'}), 400
    shtick = db.session.get(Shtick, body['shtick_id'])
    if not shtick or not shtick.approved_to_publish:
        return jsonify({'message': 'Shtick not found'}), 404
    comment = Comment(
        text=body['text'].strip(),
        shtick_id=body['shtick_id'],
        user_id=current_user.public_id
    )
    db.session.add(comment)

    notify(
        shtick.user_id,
        f'{current_user.profile_name} commented on your post "{shtick.caption[:40]}"',
        type='comment',
        actor_id=current_user.public_id,
        link='/',
    )

    db.session.commit()
    return jsonify(comment_schema.dump(comment)), 201


@comment_api.route('/guest', methods=['POST'])
def create_guest_comment():
    """Same as add_comment, minus the login requirement -- lands pending
    (approved_to_publish=None) instead of visible immediately. No
    notification fires here since the comment isn't live yet; it only
    reaches the post's author once an admin approves it."""
    body = request.get_json() or {}
    text = (body.get('text') or '').strip()
    shtick_id = body.get('shtick_id')
    if not text or not shtick_id:
        return jsonify({'message': 'text and shtick_id are required'}), 400
    shtick = db.session.get(Shtick, shtick_id)
    if not shtick or not shtick.approved_to_publish:
        return jsonify({'message': 'Shtick not found'}), 404

    guest_email = (body.get('guest_email') or '').strip()[:GUEST_EMAIL_MAX]
    guest_phone = (body.get('guest_phone') or '').strip()[:GUEST_PHONE_MAX]
    if not (guest_email or guest_phone):
        return jsonify({'message': 'At least one of guest_email or guest_phone is required'}), 400

    from backend.guest.modals.guest_throttle import check_and_record_guest_submission
    if not check_and_record_guest_submission(request):
        return jsonify({'message': 'Too many submissions from this network today -- please try again tomorrow.'}), 429

    import secrets
    comment = Comment(
        text=text, shtick_id=shtick_id, user_id=None, approved_to_publish=None,
        guest_email=guest_email or None, guest_phone=guest_phone or None,
        guest_manage_token=secrets.token_urlsafe(32),
    )
    db.session.add(comment)
    db.session.commit()

    if guest_email:
        try:
            from backend.alerts import emails
            emails.send_guest_submission_email(
                guest_email, 'your comment', 'your comment',
                f'{MAIN_SITE_URL}/guest/comment/{comment.guest_manage_token}',
            )
        except Exception:
            pass  # an email failure should never break the actual submission

    data = comment_schema.dump(comment)
    data['guest_manage_token'] = comment.guest_manage_token
    return jsonify(data), 201


@comment_api.route('/guest/<token>', methods=['GET'])
def get_guest_comment(token):
    comment = Comment.query.filter_by(guest_manage_token=token).first()
    if not comment:
        return jsonify({'message': 'Comment not found'}), 404
    return jsonify(comment_schema.dump(comment))


@comment_api.route('/guest/<token>', methods=['DELETE'])
def delete_guest_comment(token):
    comment = Comment.query.filter_by(guest_manage_token=token).first()
    if not comment:
        return jsonify({'message': 'Comment not found'}), 404
    db.session.delete(comment)
    db.session.commit()
    return jsonify({'message': 'Deleted'})


@comment_api.route('/<int:comment_id>', methods=['DELETE'])
@token_required
def delete_comment(current_user, comment_id):
    comment = db.session.get(Comment, comment_id)
    if not comment:
        return jsonify({'message': 'Comment not found'}), 404
    if comment.user_id != current_user.public_id and not current_user.is_boss:
        return jsonify({'message': 'Not authorized'}), 403
    db.session.delete(comment)
    db.session.commit()
    return jsonify({'message': 'Deleted'})


@comment_api.route('/admin/pending', methods=['GET'])
@admin_required
def get_pending_comments(_current_user):
    """New -- fills a gap the existing /admin/comments (admin.py) doesn't
    cover: that one returns the latest 200 comments regardless of
    approval state, not filtered to pending. Approve/reject for a Comment
    still goes through the existing /admin/comments/<id>/approve and
    /unapprove routes in backend/user/routes/admin.py -- not duplicated
    here."""
    pending = Comment.query.filter_by(approved_to_publish=None).order_by(Comment.pub_date.asc()).all()
    return jsonify(comments_schema.dump(pending))
