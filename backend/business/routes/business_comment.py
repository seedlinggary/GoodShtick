import os

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
GUEST_EMAIL_MAX = 150
GUEST_PHONE_MAX = 40
BUSINESS_SITE_URL = os.environ.get('BUSINESS_SITE_URL', 'https://www.goodshtickbusiness.com')


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


@business_comment_api.route('/businesses/<int:business_id>/comments/guest', methods=['POST'])
def create_guest_comment(business_id):
    """Same as create_comment, minus the login requirement -- lands pending
    (approved_to_publish=None) instead of visible immediately."""
    business = db.session.get(Business, business_id)
    if not business:
        return jsonify({'message': 'Business not found'}), 404

    req = request.get_json() or {}
    body = (req.get('body') or '').strip()
    if not body:
        return jsonify({'message': 'Comment cannot be empty'}), 400
    if len(body) > BODY_MAX:
        return jsonify({'message': f'Comment must be {BODY_MAX} characters or fewer'}), 400

    guest_email = (req.get('guest_email') or '').strip()[:GUEST_EMAIL_MAX]
    guest_phone = (req.get('guest_phone') or '').strip()[:GUEST_PHONE_MAX]
    if not (guest_email or guest_phone):
        return jsonify({'message': 'At least one of guest_email or guest_phone is required'}), 400

    from backend.guest.modals.guest_throttle import check_and_record_guest_submission
    if not check_and_record_guest_submission(request):
        return jsonify({'message': 'Too many submissions from this network today -- please try again tomorrow.'}), 429

    import secrets
    comment = BusinessComment(
        business_id=business_id, user_id=None, body=body, approved_to_publish=None,
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
                f'{BUSINESS_SITE_URL}/guest/business-comment/{comment.guest_manage_token}',
            )
        except Exception:
            pass  # an email failure should never break the actual submission

    schema = make_comment_schema(None, many=False)
    data = schema.dump(comment)
    data['guest_manage_token'] = comment.guest_manage_token
    return jsonify(data), 201


@business_comment_api.route('/comments/guest/<token>', methods=['GET'])
def get_guest_comment(token):
    comment = BusinessComment.query.filter_by(guest_manage_token=token).first()
    if not comment:
        return jsonify({'message': 'Comment not found'}), 404
    schema = make_comment_schema(None, many=False)
    return jsonify(schema.dump(comment))


@business_comment_api.route('/comments/guest/<token>', methods=['DELETE'])
def delete_guest_comment(token):
    comment = BusinessComment.query.filter_by(guest_manage_token=token).first()
    if not comment:
        return jsonify({'message': 'Comment not found'}), 404
    db.session.delete(comment)
    db.session.commit()
    return jsonify({'message': 'Deleted'})


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
