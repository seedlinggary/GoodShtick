import os
import secrets
from datetime import datetime, timedelta

from flask import Blueprint, jsonify, request
from sqlalchemy import func
from sqlalchemy.orm import selectinload

from config import db
from security import token_required, token_optional, admin_required
from upload import upload_file
from backend.business.modals.business import Business, BusinessLocation
from backend.business.modals.business_post import BusinessPost, BUSINESS_POST_TYPES
from backend.business.modals.business_follow import BusinessFollow
from backend.business.schemas.business_post import make_business_post_schema
from backend.alerts import emails

business_post_api = Blueprint('business_post_api', __name__, url_prefix='/business')

# No fixed production domain for this site is referenced anywhere else in
# this codebase yet (unlike ESTATES_SITE_URL/TACHLIS_SITE_URL) -- .env.example's
# own FRONTEND_ORIGINS comment uses "goodshtickbusiness.com" as its one
# illustrative placeholder, so that's what this falls back to; set
# BUSINESS_SITE_URL for the real deployed domain.
BUSINESS_SITE_URL = os.environ.get('BUSINESS_SITE_URL', 'https://www.goodshtickbusiness.com')

PAGE_SIZE = 20
TITLE_MAX = 150
BODY_MAX = 4000
DEFAULT_EXPIRES_DAYS = 30
CANDIDATE_CAP = 500  # see list_posts(): only used for the Python-side sort=distance pass


def _feed_options():
    return [
        selectinload(BusinessPost.user),
        selectinload(BusinessPost.business).selectinload(Business.locations),
    ]


def _owns_business(business, user):
    return bool(user) and (user.is_boss or business.owner_user_id == user.public_id)


@business_post_api.route('/posts', methods=['GET'])
@token_optional
def list_posts(current_user):
    """Public deals feed across every business. Newest-first by default;
    ?sort=random gives the same 'shake the board' surprise-me option as the
    directory and the rest of the site; ?sort=distance (with lat/lng) sorts
    by proximity to the posting business's nearest location, the same
    candidate-window approach list_businesses() uses for its own "Near me"
    (a post has no lat/lng of its own -- it inherits its business's).
    Filters: post_type, city (via the business's locations), business_id, q."""
    post_type = (request.args.get('type') or '').strip().lower()
    city = (request.args.get('city') or '').strip()
    business_id = request.args.get('business_id')
    q = (request.args.get('q') or '').strip()
    sort = (request.args.get('sort') or 'recent').strip().lower()
    try:
        page = max(1, int(request.args.get('page', 1)))
    except (TypeError, ValueError):
        page = 1

    near_lat = near_lng = None
    if sort == 'distance':
        try:
            near_lat, near_lng = float(request.args.get('lat')), float(request.args.get('lng'))
        except (TypeError, ValueError):
            return jsonify({'message': 'sort=distance requires numeric lat and lng'}), 400

    now = datetime.utcnow()
    query = (BusinessPost.query
             .options(*_feed_options())
             .filter(BusinessPost.approved_to_publish.is_(True))
             .filter(db.or_(BusinessPost.expires_at.is_(None), BusinessPost.expires_at > now)))

    if post_type:
        if post_type not in BUSINESS_POST_TYPES:
            return jsonify({'message': f'type must be one of: {", ".join(BUSINESS_POST_TYPES)}'}), 400
        query = query.filter(BusinessPost.post_type == post_type)

    if business_id:
        try:
            query = query.filter(BusinessPost.business_id == int(business_id))
        except (TypeError, ValueError):
            return jsonify({'message': 'business_id must be an integer'}), 400

    if city:
        biz_ids = db.session.query(BusinessLocation.business_id).filter(BusinessLocation.city.ilike(f'%{city}%'))
        query = query.filter(BusinessPost.business_id.in_(biz_ids))

    if q:
        like = f'%{q}%'
        query = query.join(BusinessPost.business).filter(
            db.or_(BusinessPost.title.ilike(like), BusinessPost.body.ilike(like), Business.name.ilike(like)))

    if sort == 'distance':
        candidates = query.limit(CANDIDATE_CAP).all()

        def min_distance(post):
            locs = post.business.locations if post.business else []
            dists = [(l.lat - near_lat) ** 2 + (l.lng - near_lng) ** 2 for l in locs if l.lat is not None and l.lng is not None]
            return min(dists) if dists else float('inf')

        filtered = [p for p in candidates if min_distance(p) != float('inf')]
        filtered.sort(key=min_distance)
        total = len(filtered)
        start = (page - 1) * PAGE_SIZE
        page_rows = filtered[start:start + PAGE_SIZE + 1]
        has_more = len(page_rows) > PAGE_SIZE
        posts = page_rows[:PAGE_SIZE]
    else:
        if sort == 'random':
            query = query.order_by(func.random())
        else:
            query = query.order_by(BusinessPost.pub_date.desc())
        rows = query.limit(PAGE_SIZE + 1).offset((page - 1) * PAGE_SIZE).all()
        has_more = len(rows) > PAGE_SIZE
        posts = rows[:PAGE_SIZE]

    schema = make_business_post_schema(current_user, many=True)
    return jsonify({'posts': schema.dump(posts), 'page': page, 'has_more': has_more})


@business_post_api.route('/posts/<int:post_id>', methods=['GET'])
@token_optional
def get_post(current_user, post_id):
    post = BusinessPost.query.options(*_feed_options()).filter_by(id=post_id).first()
    if not post:
        return jsonify({'message': 'Post not found'}), 404
    is_owner = current_user and post.user_id == current_user.public_id
    is_admin_viewer = current_user and current_user.is_boss
    if post.approved_to_publish is not True and not is_owner and not is_admin_viewer:
        return jsonify({'message': 'Post not found'}), 404
    schema = make_business_post_schema(current_user, many=False)
    return jsonify(schema.dump(post))


def _notify_followers_of_new_deal(business, post):
    """Emails every follower of this business about a brand-new deal post --
    BusinessFollow's own docstring already calls this out as "the gate for
    the 'new deal' notify() a business fires"; this is that notify, by
    email, firing automatically the moment a deal goes up (vs. the existing
    in-app-only notify() in business_follow.py's broadcast(), which only
    fires when the owner deliberately sends a message). Synchronous -- no
    queue/worker infrastructure exists anywhere in this codebase, same as
    every other email this project sends -- and never lets a bad address or
    a Resend hiccup for one follower block the rest, or this request."""
    followers = (BusinessFollow.query
                 .filter_by(business_id=business.id)
                 .filter(BusinessFollow.user_id != post.user_id)
                 .options(selectinload(BusinessFollow.user))
                 .all())
    if not followers:
        return

    post_url = f'{BUSINESS_SITE_URL}/deals?post={post.id}'
    token_backfilled = False
    for follow in followers:
        follower_email = follow.user.email if follow.user else None
        if not follower_email:
            continue
        if not follow.unsubscribe_token:
            # Lazy backfill for any follow row created before this column
            # existed -- same convention as EstatesListing.still_available_token.
            follow.unsubscribe_token = secrets.token_urlsafe(32)
            token_backfilled = True
        try:
            emails.send_deal_alert_email(
                follower_email, business.name, post.title, post.body, post_url,
                f'{BUSINESS_SITE_URL}/follow/unsubscribe/{follow.unsubscribe_token}',
            )
        except Exception:
            continue
    if token_backfilled:
        db.session.commit()


@business_post_api.route('/posts', methods=['POST'])
@token_required
def create_post(current_user):
    """Only the verified owner of the business (or an admin) can post --
    the claim approval is the trust gate, so this auto-publishes."""
    body = request.get_json() or {}
    try:
        business_id = int(body.get('business_id'))
    except (TypeError, ValueError):
        return jsonify({'message': 'business_id is required'}), 400

    business = db.session.get(Business, business_id)
    if not business:
        return jsonify({'message': 'Business not found'}), 404
    if not _owns_business(business, current_user):
        return jsonify({'message': 'Only this business\'s claimed owner can post deals'}), 403

    post_type = (body.get('post_type') or '').strip().lower()
    title = (body.get('title') or '').strip()
    post_body = (body.get('body') or '').strip()

    if post_type not in BUSINESS_POST_TYPES:
        return jsonify({'message': f'post_type must be one of: {", ".join(BUSINESS_POST_TYPES)}'}), 400
    if not title:
        return jsonify({'message': 'Title is required'}), 400
    if len(title) > TITLE_MAX:
        return jsonify({'message': f'Title must be {TITLE_MAX} characters or fewer'}), 400
    if not post_body:
        return jsonify({'message': 'Body is required'}), 400
    if len(post_body) > BODY_MAX:
        return jsonify({'message': f'Body must be {BODY_MAX} characters or fewer'}), 400

    post = BusinessPost(
        business_id=business_id,
        user_id=current_user.public_id,
        post_type=post_type,
        title=title,
        body=post_body,
        image=body.get('image') or None,
        expires_at=datetime.utcnow() + timedelta(days=DEFAULT_EXPIRES_DAYS),
    )
    db.session.add(post)
    db.session.commit()

    try:
        _notify_followers_of_new_deal(business, post)
    except Exception:
        pass  # a notify-path bug should never surface as a failed post

    schema = make_business_post_schema(current_user, many=False)
    return jsonify(schema.dump(post)), 201


@business_post_api.route('/posts/<int:post_id>', methods=['PATCH'])
@token_required
def edit_post(current_user, post_id):
    post = db.session.get(BusinessPost, post_id)
    if not post:
        return jsonify({'message': 'Post not found'}), 404
    if post.user_id != current_user.public_id and not current_user.is_boss:
        return jsonify({'message': 'Not authorized'}), 403

    body = request.get_json() or {}
    if 'title' in body:
        title = (body.get('title') or '').strip()
        if not title or len(title) > TITLE_MAX:
            return jsonify({'message': f'Title is required and must be {TITLE_MAX} characters or fewer'}), 400
        post.title = title
    if 'body' in body:
        text = (body.get('body') or '').strip()
        if not text or len(text) > BODY_MAX:
            return jsonify({'message': f'Body is required and must be {BODY_MAX} characters or fewer'}), 400
        post.body = text
    if 'image' in body:
        post.image = body.get('image') or None

    db.session.commit()
    schema = make_business_post_schema(current_user, many=False)
    return jsonify(schema.dump(post))


@business_post_api.route('/posts/<int:post_id>', methods=['DELETE'])
@token_required
def delete_post(current_user, post_id):
    post = db.session.get(BusinessPost, post_id)
    if not post:
        return jsonify({'message': 'Post not found'}), 404
    if post.user_id != current_user.public_id and not current_user.is_boss:
        return jsonify({'message': 'Not authorized'}), 403
    db.session.delete(post)
    db.session.commit()
    return jsonify({'message': 'Deleted'})


@business_post_api.route('/posts/upload', methods=['POST'])
@token_required
def add_post_upload(_current_user):
    filename = upload_file(request)
    if not filename:
        return jsonify({'message': 'Upload failed'}), 400
    return jsonify(filename)


# ── Admin moderation (reversible takedown/restore -- posts auto-publish) ────

@business_post_api.route('/admin/posts/<int:post_id>/unapprove', methods=['POST'])
@admin_required
def unapprove_post(current_user, post_id):
    post = db.session.get(BusinessPost, post_id)
    if not post:
        return jsonify({'message': 'Not found'}), 404
    post.approved_to_publish = False
    post.approved_by = current_user.public_id
    db.session.commit()
    return jsonify({'message': 'unapproved'})


@business_post_api.route('/admin/posts/<int:post_id>/approve', methods=['POST'])
@admin_required
def approve_post(current_user, post_id):
    post = db.session.get(BusinessPost, post_id)
    if not post:
        return jsonify({'message': 'Not found'}), 404
    post.approved_to_publish = True
    post.approved_by = current_user.public_id
    db.session.commit()
    return jsonify({'message': 'approved'})
