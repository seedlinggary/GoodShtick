from flask import Blueprint, jsonify, request
from config import db
from security import token_required
from backend.shtick.modals.like import Like
from backend.shtick.modals.like import Like
from backend.shtick.modals.content import Content
from backend.shtick.modals.url import Url
from backend.shtick.schemas.like import like_schema,likes_schema
import jwt
from backend.user.modals.user import User
from config import application

like_api = Blueprint('like_api', __name__,url_prefix='/like')


@like_api.route('/', methods=['GET'])
@token_required
def get_unapproved(current_user):
    if current_user.is_boss:
        all_likes = Like.query.filter_by(approved_to_publish=False).all()
        result = likes_schema.dump(all_likes)

        return jsonify(result)
    return jsonify(None)

@like_api.route('/action', methods=['POST'])
@token_required
def like_shtick(current_user):
    print('hiiii')
    rtrn_answer = jsonify(None)
    if request.json['like_id']:
        Like.query.filter_by(id=request.json['like_id']).delete()
        rtrn_answer = jsonify('deleted')
        db.session.commit()
    else:
        new_like = Like(user_id=current_user.public_id,shtick_id=request.json['shtick_id'])
        db.session.add(new_like)
        db.session.commit()
        rtrn_answer =like_schema.jsonify(new_like)
    

    return rtrn_answer
