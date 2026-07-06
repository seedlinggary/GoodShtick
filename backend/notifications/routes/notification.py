from flask import Blueprint, jsonify
from config import db
from security import token_required
from backend.notifications.modals.notification import Notification
from backend.notifications.schemas.notification import notification_schema, notifications_schema

notification_api = Blueprint('notification_api', __name__, url_prefix='/notifications')


@notification_api.route('', methods=['GET'])
@token_required
def get_notifications(current_user):
    rows = (Notification.query
            .filter_by(user_id=current_user.public_id)
            .order_by(Notification.pub_date.desc())
            .limit(50).all())
    return jsonify(notifications_schema.dump(rows))


@notification_api.route('/unread-count', methods=['GET'])
@token_required
def get_unread_count(current_user):
    count = Notification.query.filter_by(user_id=current_user.public_id, is_read=False).count()
    return jsonify({'count': count})


@notification_api.route('/<int:notification_id>/read', methods=['POST'])
@token_required
def mark_read(current_user, notification_id):
    n = db.session.get(Notification, notification_id)
    if not n or n.user_id != current_user.public_id:
        return jsonify({'message': 'Notification not found'}), 404
    n.is_read = True
    db.session.commit()
    return jsonify(notification_schema.dump(n))


@notification_api.route('/read-all', methods=['POST'])
@token_required
def mark_all_read(current_user):
    (Notification.query
     .filter_by(user_id=current_user.public_id, is_read=False)
     .update({'is_read': True}))
    db.session.commit()
    return jsonify({'message': 'ok'})
