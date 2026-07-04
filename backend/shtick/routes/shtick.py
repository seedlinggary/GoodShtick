import os
import base64
from flask import Blueprint, jsonify, request
from sqlalchemy.orm import selectinload
from config import db, cache
from security import token_required, admin_required
from backend.shtick.modals.shtick import Shtick
from backend.shtick.modals.like import Like
from backend.shtick.modals.content import Content
from backend.shtick.modals.url import Url
from backend.shtick.modals.picture import Picture
from backend.shtick.modals.generalc import Generalc
from backend.shtick.schemas.shtick import shtick_schema, shticks_schema, shticks_feed_schema
import jwt
from backend.user.modals.user import User
from config import application
from upload import upload_file, download_images

def _feed_options():
    """Eager-load options for the public feed. Called at request time, not import time."""
    return [
        selectinload(Shtick.user),
        selectinload(Shtick.categories),
        selectinload(Shtick.likes),
        selectinload(Shtick.content),
        selectinload(Shtick.url),
        selectinload(Shtick.picture),
    ]

shtick_api = Blueprint('shtick_api', __name__, url_prefix='/shtick')


@shtick_api.route('/unapproved', methods=['GET'])
@admin_required
def get_unapproved(_current_user):
    pending = Shtick.query.filter_by(approved_to_publish=None).order_by(Shtick.pub_date.desc()).all()
    return jsonify(shticks_schema.dump(pending))


@shtick_api.route('/unapproved', methods=['POST'])
@admin_required
def make_approved(current_user):
    body = request.get_json()
    shtick = db.session.get(Shtick, body.get('shtick_id'))
    if not shtick:
        return jsonify({'message': 'Shtick not found'}), 404
    approve = not body.get('delete', False)
    shtick.approved_to_publish = approve
    if approve:
        shtick.approved_by = current_user.public_id
    db.session.commit()
    return jsonify({'message': 'done'})


def _approved_shticks_for_download(generalc_id, limit):
    """Fetch approved shticks for the image download helper."""
    if generalc_id == 'all':
        return (Shtick.query
                .options(selectinload(Shtick.picture))
                .filter_by(approved_to_publish=True)
                .order_by(Shtick.pub_date.desc())
                .limit(limit).all())
    return (Shtick.query
            .options(selectinload(Shtick.picture))
            .filter_by(approved_to_publish=True, generalc_id=generalc_id)
            .order_by(Shtick.pub_date.desc())
            .limit(limit).all())


@shtick_api.route('/download/<generalc_id>/<int:page>', methods=['GET'])
def get_all_approved_shtick_downloads(generalc_id, page):
    limit = page * 10
    my_messages = _approved_shticks_for_download(generalc_id, limit)

    image_names = [s.picture.name for s in my_messages if s.picture]
    try:
        download_images(image_names)
    except Exception:
        return jsonify({})

    image_folder = '/tmp/downloadimages'

    if not os.path.exists(image_folder):
        return jsonify({})

    images_data = {}
    for filename in os.listdir(image_folder):
        full_path = os.path.join(image_folder, filename)
        if os.path.isfile(full_path):
            with open(full_path, 'rb') as f:
                images_data[filename] = base64.b64encode(f.read()).decode('utf-8')

    return jsonify(images_data)


@shtick_api.route('/<int:shtick_id>/view', methods=['POST'])
def record_view(shtick_id):
    """Atomically increment view_count. No auth required — called from the public feed."""
    from sqlalchemy import update
    db.session.execute(
        update(Shtick)
        .where(Shtick.id == shtick_id)
        .where(Shtick.approved_to_publish.is_(True))  # only count views on live posts
        .values(view_count=Shtick.view_count + 1)
    )
    db.session.commit()
    return jsonify({'ok': True})


@shtick_api.route('/<generalc_id>/<int:page>', methods=['GET'])
def get_all_approved_shtick(generalc_id, page):
    limit = page * 10

    # Auth-gated modes bypass the cache (personal data)
    if generalc_id in ('0', 'liked'):
        token = request.headers.get('x-access-token')
        if not token:
            return jsonify({'message': 'Token is invalid or missing'}), 401
        try:
            data = jwt.decode(token, application.config['SECRET_KEY'], algorithms=['HS256'])
            current_user = User.query.filter_by(public_id=data['public_id']).first()
            if not current_user:
                return jsonify({'message': 'Token is invalid or missing'}), 401
        except jwt.InvalidTokenError:
            return jsonify({'message': 'Token is invalid or missing'}), 401

        if generalc_id == '0' and current_user.is_boss:
            shticks = (Shtick.query
                       .options(*_feed_options())
                       .filter_by(approved_to_publish=None)
                       .order_by(Shtick.pub_date.desc()).all())
            return jsonify(shticks_feed_schema.dump(shticks))

        liked_ids = [like.shtick_id for like in
                     Like.query.filter_by(user_id=current_user.public_id).all()]
        if not liked_ids:
            return jsonify([])
        shticks = (Shtick.query
                   .options(*_feed_options())
                   .filter(Shtick.id.in_(liked_ids))
                   .order_by(Shtick.pub_date.desc()).all())
        return jsonify(shticks_feed_schema.dump(shticks))

    # Public feed — cache by category + page
    cache_key = f'feed:{generalc_id}:{limit}'
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    if generalc_id == 'all':
        shticks = (Shtick.query
                   .options(*_feed_options())
                   .filter_by(approved_to_publish=True)
                   .order_by(Shtick.pub_date.desc())
                   .limit(limit).all())
    else:
        shticks = (Shtick.query
                   .options(*_feed_options())
                   .filter_by(approved_to_publish=True, generalc_id=generalc_id)
                   .order_by(Shtick.pub_date.desc())
                   .limit(limit).all())

    response = jsonify(shticks_feed_schema.dump(shticks))
    cache.set(cache_key, response, timeout=60)
    return response


@shtick_api.route('', methods=['POST'])
@token_required
def create_shtick(current_user):
    body = request.get_json()
    if not body or not body.get('caption') or not body.get('category_id'):
        return jsonify({'message': 'Caption and category are required'}), 400

    # Support single category_id or list of category_ids
    category_ids = body.get('category_ids', [])
    primary_id = body.get('category_id')
    if primary_id and primary_id not in category_ids:
        category_ids = [primary_id] + [c for c in category_ids if c != primary_id]

    new_shtick = Shtick(
        caption=body['caption'],
        credit=body.get('credit', ''),
        specific_category=body.get('specific_category', ''),
        user_id=current_user.public_id,
        generalc_id=primary_id
    )

    if current_user.is_boss:
        new_shtick.approved_to_publish = True
        new_shtick.approved_by = current_user.public_id

    db.session.add(new_shtick)
    db.session.flush()  # get new_shtick.id without full commit

    # Attach all categories to the many-to-many table
    for cat_id in category_ids:
        cat = db.session.get(Generalc, cat_id)
        if cat and cat not in new_shtick.categories:
            new_shtick.categories.append(cat)

    content = body.get('content')
    url = body.get('url')
    picture = body.get('picture')

    if content:
        db.session.add(Content(stuff=content, shtick_id=new_shtick.id))
    if url:
        db.session.add(Url(name=url, shtick_id=new_shtick.id))
    if picture:
        db.session.add(Picture(name=picture, shtick_id=new_shtick.id))

    db.session.commit()
    return jsonify(shtick_schema.dump(new_shtick)), 201


@shtick_api.route('/upload', methods=['POST'])
@token_required
def add_upload(_current_user):
    filename = upload_file(request)
    if not filename:
        return jsonify({'message': 'Upload failed'}), 400
    return jsonify(filename)
