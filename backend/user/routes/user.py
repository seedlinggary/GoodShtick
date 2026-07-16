from datetime import datetime, timedelta

from flask import Blueprint, jsonify, request
from sqlalchemy import func
from sqlalchemy.orm import selectinload
from backend.user.modals.user import User
from backend.user.schemas.user import users_schema, user_schema
from backend.shtick.modals.shtick import Shtick
from backend.hock.modals.hock_post import HockPost
from backend.analytics.modals.visitor import VisitorSession, VisitorEvent
from config import db
from security import token_required
from werkzeug.security import generate_password_hash
import uuid

REGULAR_THRESHOLD_DAYS = 5

user_api = Blueprint('user_api', __name__, url_prefix='/user')

VALID_GENDERS = {'male', 'female', 'other'}


@user_api.route('/new_email', methods=['POST'])
def check_email():
    email = request.get_json()
    if not email or not isinstance(email, str):
        return jsonify({'message': 'Email is required'}), 400
    exists = User.query.filter_by(email=email).first() is not None
    return jsonify('exists' if exists else None)


@user_api.route('', methods=['GET'])
def get_users():
    all_users = User.query.all()
    return jsonify(users_schema.dump(all_users))


@user_api.route('', methods=['POST'])
def add_user():
    body = request.get_json()
    if not body:
        return jsonify({'message': 'Request body is required'}), 400
    required = ['first_name', 'last_name', 'email', 'profile_name', 'password']
    missing = [f for f in required if not body.get(f)]
    if missing:
        return jsonify({'message': f'Missing fields: {", ".join(missing)}'}), 400
    if User.query.filter_by(email=body['email']).first():
        return jsonify({'message': 'An account with this email already exists'}), 409
    if User.query.filter_by(profile_name=body['profile_name']).first():
        return jsonify({'message': 'That profile name is already taken'}), 409
    hashed_password = generate_password_hash(body['password'], method='pbkdf2:sha256')
    new_user = User(
        public_id=str(uuid.uuid4()),
        first_name=body['first_name'],
        last_name=body['last_name'],
        email=body['email'],
        profile_name=body['profile_name'],
        password=hashed_password
    )
    db.session.add(new_user)
    db.session.commit()
    return jsonify(user_schema.dump(new_user)), 201


@user_api.route('/profile', methods=['PUT'])
@token_required
def update_profile(current_user):
    """Self-service profile edit: name/email/profile_name plus the optional
    ad-targeting fields. Role is never editable here."""
    body = request.get_json() or {}

    if 'first_name' in body:
        first_name = (body['first_name'] or '').strip()
        if not first_name:
            return jsonify({'message': 'First name cannot be empty'}), 400
        current_user.first_name = first_name

    if 'last_name' in body:
        last_name = (body['last_name'] or '').strip()
        if not last_name:
            return jsonify({'message': 'Last name cannot be empty'}), 400
        current_user.last_name = last_name

    if 'profile_name' in body:
        profile_name = (body['profile_name'] or '').strip()
        if not profile_name:
            return jsonify({'message': 'Profile name cannot be empty'}), 400
        taken = User.query.filter(
            User.profile_name == profile_name, User.public_id != current_user.public_id
        ).first()
        if taken:
            return jsonify({'message': 'That profile name is already taken'}), 409
        current_user.profile_name = profile_name

    if 'email' in body:
        email = (body['email'] or '').strip()
        if not email:
            return jsonify({'message': 'Email cannot be empty'}), 400
        taken = User.query.filter(
            User.email == email, User.public_id != current_user.public_id
        ).first()
        if taken:
            return jsonify({'message': 'An account with this email already exists'}), 409
        current_user.email = email

    if 'birthdate' in body:
        raw = body['birthdate']
        if not raw:
            current_user.birthdate = None
        else:
            try:
                current_user.birthdate = datetime.strptime(raw, '%Y-%m-%d').date()
            except ValueError:
                return jsonify({'message': 'birthdate must be in YYYY-MM-DD format'}), 400

    if 'gender' in body:
        gender = (body['gender'] or '').lower() or None
        if gender and gender not in VALID_GENDERS:
            return jsonify({'message': f'Invalid gender. Must be one of: {", ".join(VALID_GENDERS)}'}), 400
        current_user.gender = gender

    if 'location_country' in body:
        current_user.location_country = body['location_country'] or None
    if 'location_city' in body:
        current_user.location_city = body['location_city'] or None

    db.session.commit()
    return jsonify(user_schema.dump(current_user))


@user_api.route('/me/activity', methods=['GET'])
@token_required
def my_activity(current_user):
    """Everything the logged-in user has posted/liked/commented across Feed,
    Hock, and Tachlis, plus their own profile -- self-service, any state
    (pending/approved/rejected/hidden) since it's their own content."""
    # Eager-load likes/comments in bulk (2 extra queries total) instead of
    # touching each post's lazy relationship one at a time -- this account
    # alone owns 190+ posts, so per-post lazy loads meant 400+ round trips
    # to the remote DB and the request would hang for tens of seconds.
    own_shticks = (Shtick.query
                   .filter_by(user_id=current_user.public_id)
                   .options(selectinload(Shtick.likes), selectinload(Shtick.comments))
                   .all())
    shticks = [{
        'id': s.id, 'caption': s.caption, 'approved_to_publish': s.approved_to_publish,
        'pub_date': str(s.pub_date), 'like_count': len(s.likes), 'comment_count': len(s.comments),
    } for s in own_shticks]

    own_hock_posts = (HockPost.query
                       .filter_by(user_id=current_user.public_id)
                       .options(selectinload(HockPost.likes), selectinload(HockPost.comments))
                       .all())
    hock_posts = [{
        'id': p.id, 'title': p.title, 'approved_to_publish': p.approved_to_publish,
        'pub_date': str(p.pub_date), 'like_count': len(p.likes), 'comment_count': len(p.comments),
    } for p in own_hock_posts]

    tachlis_posts = [{
        'id': t.id, 'title': t.title, 'post_type': t.post_type,
        'approved_to_publish': t.approved_to_publish, 'pub_date': str(t.pub_date),
    } for t in current_user.tachlis_posts]

    comments = (
        [{'id': c.id, 'text': c.text, 'source': 'feed', 'target_id': c.shtick_id,
          'approved_to_publish': c.approved_to_publish, 'pub_date': str(c.pub_date)}
         for c in current_user.comments]
        + [{'id': c.id, 'text': c.text, 'source': 'hock', 'target_id': c.hock_post_id,
            'approved_to_publish': c.approved_to_publish, 'pub_date': str(c.pub_date)}
           for c in current_user.hock_comments]
    )
    comments.sort(key=lambda c: c['pub_date'], reverse=True)

    likes = (
        [{'source': 'feed', 'target_id': l.shtick_id, 'pub_date': str(l.pub_date)}
         for l in current_user.likes]
        + [{'source': 'hock_post', 'target_id': l.hock_post_id, 'pub_date': str(l.pub_date)}
           for l in current_user.hock_post_likes]
        + [{'source': 'hock_comment', 'target_id': l.hock_comment_id, 'pub_date': str(l.pub_date)}
           for l in current_user.hock_comment_likes]
    )
    likes.sort(key=lambda l: l['pub_date'], reverse=True)

    return jsonify({
        'user': user_schema.dump(current_user),
        'shticks': shticks,
        'hock_posts': hock_posts,
        'tachlis_posts': tachlis_posts,
        'comments': comments,
        'likes': likes,
    })


@user_api.route('/me/streak', methods=['GET'])
@token_required
def my_streak(current_user):
    """The Profile punch card's data -- reuses the visitor-analytics tables
    built for /analytics/dashboard rather than a separate streak system.
    VisitorSession.user_id gets backfilled onto a visitor's session the
    moment they're logged in during a beacon (see
    backend/analytics/routes/visitor.py), so every distinct calendar day
    this user was ever active on the site is already sitting in
    VisitorEvent -- this just counts it."""
    anon_ids = [row.anonymous_id for row in
                VisitorSession.query.filter_by(user_id=current_user.public_id)
                .with_entities(VisitorSession.anonymous_id).distinct().all()]

    if not anon_ids:
        return jsonify({'distinct_days': 0, 'current_streak': 0, 'is_regular': False, 'recent_days': []})

    day_rows = (db.session.query(func.date(VisitorEvent.created_at))
                .filter(VisitorEvent.anonymous_id.in_(anon_ids))
                .distinct()
                .order_by(func.date(VisitorEvent.created_at).desc())
                .all())
    active_days = [d for (d,) in day_rows]

    # Consecutive-day streak counting back from today, with a one-day grace
    # (yesterday still counts as "unbroken" if today's beacon hasn't fired
    # yet) so the streak doesn't visibly reset the instant midnight passes.
    today = datetime.utcnow().date()
    streak = 0
    cursor = today
    active_set = set(active_days)
    if today not in active_set:
        cursor = today - timedelta(days=1)
    while cursor in active_set:
        streak += 1
        cursor -= timedelta(days=1)

    return jsonify({
        'distinct_days': len(active_days),
        'current_streak': streak,
        'is_regular': len(active_days) >= REGULAR_THRESHOLD_DAYS,
        'recent_days': [str(d) for d in active_days[:7]],
    })


@user_api.route('/<public_id>', methods=['GET'])
@token_required
def get_user(_current_user, public_id):
    user = User.query.filter_by(public_id=public_id).first()
    if not user:
        return jsonify({'message': 'User not found'}), 404
    return jsonify(user_schema.dump(user))


@user_api.route('/<public_id>', methods=['DELETE'])
@token_required
def delete_user(current_user, public_id):
    if not current_user.is_boss and current_user.public_id != public_id:
        return jsonify({'message': 'Not authorized'}), 403
    user = db.session.get(User, public_id)
    if not user:
        return jsonify({'message': 'User not found'}), 404
    db.session.delete(user)
    db.session.commit()
    return jsonify(user_schema.dump(user))
