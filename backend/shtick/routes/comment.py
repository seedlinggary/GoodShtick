from flask import Blueprint, jsonify, request
from config import db
from security import token_required, admin_required
from backend.shtick.modals.comment import Comment
from backend.shtick.modals.shtick import Shtick
from backend.shtick.schemas.shtick import comment_schema, comments_schema
from backend.notifications.helpers import notify

comment_api = Blueprint('comment_api', __name__, url_prefix='/comment')


@comment_api.route('/<int:shtick_id>', methods=['GET'])
def get_comments(shtick_id):
    comments = Comment.query.filter_by(shtick_id=shtick_id).order_by(Comment.pub_date.asc()).all()
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
