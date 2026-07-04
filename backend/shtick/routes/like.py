from flask import Blueprint, jsonify, request
from config import db
from security import token_required
from backend.shtick.modals.like import Like
from backend.shtick.schemas.like import like_schema, likes_schema

like_api = Blueprint('like_api', __name__, url_prefix='/like')


@like_api.route('/', methods=['GET'])
@token_required
def get_all_likes(current_user):
    if not current_user.is_boss:
        return jsonify({'message': 'Not authorized'}), 403
    all_likes = Like.query.all()
    return jsonify(likes_schema.dump(all_likes))


@like_api.route('/action', methods=['POST'])
@token_required
def like_shtick(current_user):
    body = request.get_json()
    if not body:
        return jsonify({'message': 'Request body required'}), 400

    like_id = body.get('like_id')
    if like_id:
        rows = Like.query.filter_by(id=like_id, user_id=current_user.public_id).delete()
        db.session.commit()
        if rows == 0:
            return jsonify({'message': 'Like not found'}), 404
        return jsonify('deleted')

    shtick_id = body.get('shtick_id')
    if not shtick_id:
        return jsonify({'message': 'shtick_id is required'}), 400

    existing = Like.query.filter_by(user_id=current_user.public_id, shtick_id=shtick_id).first()
    if existing:
        return jsonify(like_schema.dump(existing))

    new_like = Like(user_id=current_user.public_id, shtick_id=shtick_id)
    db.session.add(new_like)
    db.session.commit()
    return jsonify(like_schema.dump(new_like)), 201
