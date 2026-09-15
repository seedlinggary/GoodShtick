from flask import Blueprint, jsonify, request
from sqlalchemy.orm import selectinload

from config import db
from security import token_required, token_optional, admin_required
from backend.business.modals.business import Business
from backend.business.modals.business_comment import BusinessComment
from backend.business.schemas.business import make_comment_schema

business_comment_api = Blueprint('business_comment_api', __name__, url_prefix='/business')

PAGE_SIZE = 20
BODY_MAX = 1000


@business_comment_api.route('/businesses/<int:business_id>/comments', methods=['GET'])
@token_optional
def list_comments(current_user, business_id):
    try:
        page = max(1, int(request.args.get('page', 1)))
    except (TypeError, ValueError):
        page = 1
    rows = (BusinessComment.query
            .options(selectinload(BusinessComment.user))
            .filter_by(business_id=business_id, approved_to_publish=True)
            .order_by(BusinessComment.pub_date.desc())
            .limit(PAGE_SIZE + 1).offset((page - 1) * PAGE_SIZE).all())
    has_more = len(rows) > PAGE_SIZE
    schema = make_comment_schema(current_user, many=True)
    return jsonify({'comments': schema.dump(rows[:PAGE_SIZE]), 'page': page, 'has_more': has_more})


@business_comment_api.route('/businesses/<int:business_id>/comments', methods=['POST'])
@token_required
def create_comment(current_user, business_id):
    business = db.session.get(Business, business_id)
    if not business:
        return jsonify({'message': 'Business not found'}), 404

    body = (request.get_json() or {}).get('body', '')
    body = body.strip()
    if not body:
        return jsonify({'message': 'Comment cannot be empty'}), 400
    if len(body) > BODY_MAX:
        return jsonify({'message': f'Comment must be {BODY_MAX} characters or fewer'}), 400

    comment = BusinessComment(business_id=business_id, user_id=current_user.public_id, body=body)
    db.session.add(comment)
    db.session.commit()
    schema = make_comment_schema(current_user, many=False)
    return jsonify(schema.dump(comment)), 201


@business_comment_api.route('/comments/<int:comment_id>', methods=['DELETE'])
@token_required
def delete_comment(current_user, comment_id):
    comment = db.session.get(BusinessComment, comment_id)
    if not comment:
        return jsonify({'message': 'Comment not found'}), 404
    if comment.user_id != current_user.public_id and not current_user.is_boss:
        return jsonify({'message': 'Not authorized'}), 403
    db.session.delete(comment)
    db.session.commit()
    return jsonify({'message': 'Deleted'})


@business_comment_api.route('/admin/comments/<int:comment_id>/unapprove', methods=['POST'])
@admin_required
def unapprove_comment(_current_user, comment_id):
    comment = db.session.get(BusinessComment, comment_id)
    if not comment:
        return jsonify({'message': 'Not found'}), 404
    comment.approved_to_publish = False
    db.session.commit()
    return jsonify({'message': 'unapproved'})


@business_comment_api.route('/admin/comments/<int:comment_id>/approve', methods=['POST'])
@admin_required
def approve_comment(_current_user, comment_id):
    comment = db.session.get(BusinessComment, comment_id)
    if not comment:
        return jsonify({'message': 'Not found'}), 404
    comment.approved_to_publish = True
    db.session.commit()
    return jsonify({'message': 'approved'})
