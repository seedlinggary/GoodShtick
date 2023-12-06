from flask import Blueprint, jsonify, request
from config import db
from security import token_required
from backend.shtick.modals.shtick import Shtick
from backend.shtick.modals.like import Like
from backend.shtick.modals.content import Content
from backend.shtick.modals.url import Url
from backend.shtick.schemas.shtick import shtick_schema,shticks_schema
import jwt
from backend.user.modals.user import User
from config import application

shtick_api = Blueprint('shtick_api', __name__,url_prefix='/shtick')



# @shtick_api.route('', methods=['GET'])
# def get_all_shtick():
#     all_shticks = Shtick.query.all()
#     result = shticks_schema.dump(all_shticks)

#     return jsonify(result)

@shtick_api.route('/unapproved', methods=['GET'])
@token_required
def get_unapproved(current_user):
    if current_user.is_boss:
        all_shticks = Shtick.query.filter_by(approved_to_publish=False).all()
        result = shticks_schema.dump(all_shticks)

        return jsonify(result)
    return jsonify(None)

@shtick_api.route('/unapproved', methods=['POST'])
@token_required
def make_approved(current_user):
    if current_user.is_boss:
        new_shtick = Shtick.query.get(request.json['shtick_id'])
        if request.json['delete'] is False:
            new_shtick.approved_to_publish = True
        elif request.json['delete']:
            new_shtick.approved_to_publish = False
        db.session.commit()

        return jsonify('done')
    return jsonify(None)

@shtick_api.route('/<generalc_id>/<limit>', methods=['GET'])
def get_all_approved_shtick(generalc_id, limit):
    limit = int(limit) * 10
    if generalc_id == '0' or generalc_id == 'liked' :
        if 'x-access-token' in request.headers:
            token = request.headers['x-access-token']
        # if not token:
        #     return jsonify({"messgae": "token missing"}), 401
        try:
            data = jwt.decode(token, application.config.get('SECRET_KEY'), algorithms="HS256")
            current_user =User.query.filter_by(public_id = data['public_id']).first()
        except:

            return jsonify({"messgae": "token is invalid"}), 401

        if current_user.is_boss and generalc_id == '0':
            all_shticks = Shtick.query.filter_by(approved_to_publish=None).all()
            result = shticks_schema.dump(all_shticks)
            return jsonify(result)
        all_likes = Like.query.filter_by(user_id=current_user.public_id).all()
        all_shticks =[]
        for like in all_likes:
            all_shticks.append(Shtick.query.get(like.shtick_id))
        result = shticks_schema.dump(all_shticks)
        return jsonify(result)
        

    if generalc_id == 'all':
        my_messages = Shtick.query.filter_by(approved_to_publish=True).order_by(Shtick.pub_date.desc()).limit(limit).all()
    else:
        my_messages = Shtick.query.filter_by(approved_to_publish=True).order_by(Shtick.pub_date.desc()).filter_by(generalc_id=generalc_id).limit(limit).all()
    result = shticks_schema.dump(my_messages)
    # all_friends = Friend.query.filter_by(request_id=current_user.public_id)
    # these_friends = Friend.query.filter_by(receive_id=current_user.public_id)
    # my_friends = [current_user.public_id]
    # for friend in all_friends:
    #     my_friends.append(friend.receive.public_id)
    # for friend in these_friends:
    #     my_friends.append(friend.request.public_id)
    return jsonify(result)
    messages_to_send = []
    for message in result:
        # if message['user']['public_id'] in my_friends:
        messages_to_send.append(message)
        if len(messages_to_send) >= limit:
            break
    return jsonify(messages_to_send)


@shtick_api.route('', methods=['POST'])
@token_required
def add_user(current_user):
    new_shtick = Shtick(caption =request.json['caption'],credit =request.json['credit'],specific_category =request.json['specific_category'],user_id =current_user.public_id,generalc_id=request.json['category_id'])
    if current_user.is_boss:
        new_shtick.approved_to_publish = True
    db.session.add(new_shtick)
    db.session.commit()
    if request.json['content']:
        new_content = Content(stuff=request.json['content'],shtick_id=new_shtick.id)
    if request.json['url']:
        new_content = Url(name=request.json['url'],shtick_id=new_shtick.id)
    db.session.add(new_content)
    db.session.commit()

    return shtick_schema.jsonify(new_shtick)



