import hashlib
import time
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request
from sqlalchemy import func
from sqlalchemy.orm import selectinload
from config import db, cache
from security import token_required, admin_required
from backend.shtick.modals.shtick import Shtick
from backend.shtick.modals.like import Like
from backend.shtick.modals.content import Content
from backend.shtick.modals.url import Url
from backend.shtick.modals.picture import Picture
from backend.shtick.modals.generalc import Generalc
from backend.shtick.schemas.shtick import shtick_schema, shticks_schema, shtick_feed_schema, shticks_feed_schema
from backend.hock.modals.hock_post import HockPost
from backend.hock.schemas.hock import make_post_schema as make_hock_post_schema
from backend.tachlis.modals.tachlis_post import TachlisPost
from backend.tachlis.schemas.tachlis import make_tachlis_post_schema
import jwt
from backend.user.modals.user import User
from config import application
from upload import upload_file

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


@shtick_api.route('/post/<int:shtick_id>', methods=['GET'])
def get_single_post(shtick_id):
    """Single approved post, for permalinks/sharing — a plain '<generalc_id>/<page>'
    URL can't be pointed at from outside, since it always returns a whole page."""
    shtick = (Shtick.query
              .options(*_feed_options())
              .filter_by(id=shtick_id, approved_to_publish=True)
              .first())
    if not shtick:
        return jsonify({'message': 'Post not found'}), 404
    response = jsonify(shtick_feed_schema.dump(shtick))
    response.headers['Cache-Control'] = 'public, s-maxage=60, stale-while-revalidate=300'
    return response


PAGE_SIZE = 10

# ── Daily Board feed algorithm ──────────────────────────────────────────────
# The root board ("mix=1", see get_all_approved_shtick) doesn't want a
# perfectly frozen reverse-chronological order forever -- every visit looks
# identical, and older-but-still-good posts have zero chance of resurfacing.
# It also shouldn't be pure randomness -- newer posts should still generally
# float up. The compromise: bucket candidates into recency tiers, then shuffle
# *within* each tier using a seed tied to a rotating time window. Newer tiers
# always sort before older ones (recency-weighted), but the exact order
# inside a tier drifts every BOARD_BUCKET_SECONDS instead of being fixed.
# The shuffle is a pure function of (kind, id, bucket) -- no per-request
# randomness -- so it stays stable (and CDN/in-process cacheable) for the
# whole bucket window, and pagination never repeats or skips an item within
# that window.
BOARD_BUCKET_SECONDS = 20 * 60  # how often the shuffle re-rolls
RECENCY_TIER_HOURS = [2, 6, 24, 72]  # tier boundaries; anything older is the last tier
HOCK_SLOT = 3      # 0-indexed position of the Hock pick within each 10-item page
TACHLIS_SLOT = 7   # 0-indexed position of the Tachlis pick within each 10-item page
BOARD_SHTICK_CANDIDATES = 200
BOARD_HOCK_CANDIDATES = 40
BOARD_TACHLIS_CANDIDATES = 30


def _recency_tier(pub_date, now):
    if not pub_date:
        return len(RECENCY_TIER_HOURS)
    age_hours = (now - pub_date).total_seconds() / 3600
    for tier, bound in enumerate(RECENCY_TIER_HOURS):
        if age_hours < bound:
            return tier
    return len(RECENCY_TIER_HOURS)


def _shuffle_key(kind, item_id, bucket):
    """Deterministic per-item, per-bucket pseudo-random key -- same inputs
    always produce the same key, so the order is stable within one bucket
    window and reshuffles cleanly once the bucket rolls over."""
    digest = hashlib.md5(f'{kind}:{item_id}:{bucket}'.encode()).hexdigest()
    return digest


def _tiered_shuffle(rows, kind, now, bucket):
    return sorted(
        rows,
        key=lambda row: (_recency_tier(row.pub_date, now), _shuffle_key(kind, row.id, bucket))
    )


def _board_feed_page(page, current_user=None):
    """One page of the mixed, recency-weighted board feed: mostly Shtick
    posts in tiered-shuffled order, with one Hock pick and one Tachlis pick
    folded into fixed slots on every page so cross-pollination is a steady
    presence rather than a one-off strip at the very top."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    bucket = int(time.time() // BOARD_BUCKET_SECONDS)

    shticks = (Shtick.query
               .options(*_feed_options())
               .filter_by(approved_to_publish=True)
               .order_by(Shtick.pub_date.desc())
               .limit(BOARD_SHTICK_CANDIDATES).all())
    shticks = _tiered_shuffle(shticks, 'shtick', now, bucket)

    hock_posts = (HockPost.query
                  .filter_by(approved_to_publish=True)
                  .order_by(HockPost.pub_date.desc())
                  .limit(BOARD_HOCK_CANDIDATES).all())
    hock_posts = _tiered_shuffle(hock_posts, 'hock', now, bucket)

    tachlis_posts = (TachlisPost.query
                      .filter_by(approved_to_publish=True)
                      .order_by(TachlisPost.pub_date.desc())
                      .limit(BOARD_TACHLIS_CANDIDATES).all())
    tachlis_posts = _tiered_shuffle(tachlis_posts, 'tachlis', now, bucket)

    shticks_per_page = PAGE_SIZE - (1 if hock_posts else 0) - (1 if tachlis_posts else 0)
    shtick_start = (page - 1) * shticks_per_page
    page_shticks = shticks[shtick_start:shtick_start + shticks_per_page]

    items = [('shtick', s) for s in page_shticks]
    if hock_posts:
        pick = hock_posts[(page - 1) % len(hock_posts)]
        items.insert(min(HOCK_SLOT, len(items)), ('hock', pick))
    if tachlis_posts:
        pick = tachlis_posts[(page - 1) % len(tachlis_posts)]
        items.insert(min(TACHLIS_SLOT, len(items)), ('tachlis', pick))

    hock_schema = make_hock_post_schema(current_user, card=True)
    tachlis_schema = make_tachlis_post_schema(current_user, card=True)

    dumped = []
    for kind, obj in items:
        if kind == 'shtick':
            dumped.append({'kind': 'shtick', **shtick_feed_schema.dump(obj)})
        elif kind == 'hock':
            dumped.append({'kind': 'hock', **hock_schema.dump(obj)})
        else:
            dumped.append({'kind': 'tachlis', **tachlis_schema.dump(obj)})
    return dumped


@shtick_api.route('/<generalc_id>/<int:page>', methods=['GET'])
def get_all_approved_shtick(generalc_id, page):
    # `page` was previously treated as a cumulative multiplier (limit = page*10),
    # so every "Load more" click re-fetched, re-serialized, and re-cached EVERY
    # previously-seen row from scratch on top of the new ones -- quadratic cost
    # as a user scrolls, and an ever-growing set of cache entries (one per
    # distinct limit ever requested) that never got reused. Real OFFSET/LIMIT
    # paging below: each page is fetched, serialized, and cached exactly once,
    # and the frontend appends pages instead of replacing the whole feed.
    offset = (page - 1) * PAGE_SIZE

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

    # The Daily Board home feed (root only -- NOT the "/feed/all" browse-all
    # page, which sends generalc_id='all' too but omits ?mix=1 and stays pure
    # reverse-chronological Shtick, same as any other category). Cache key
    # includes the shuffle bucket so a cached page never outlives its own
    # ordering, and naturally expires right as the bucket rolls over.
    if generalc_id == 'all' and request.args.get('mix') == '1':
        bucket = int(time.time() // BOARD_BUCKET_SECONDS)
        cache_key = f'feed:board:page:{page}:bucket:{bucket}'
        cached = cache.get(cache_key)
        if cached is not None:
            return cached
        items = _board_feed_page(page)
        response = jsonify(items)
        response.headers['Cache-Control'] = f'public, s-maxage={BOARD_BUCKET_SECONDS}, stale-while-revalidate=300'
        cache.set(cache_key, response, timeout=BOARD_BUCKET_SECONDS)
        return response

    # Public feed — cache by category + page (bounded set of keys now that
    # each page is its own entry, instead of one growing entry per cumulative limit)
    cache_key = f'feed:{generalc_id}:page:{page}'
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    if generalc_id == 'all':
        shticks = (Shtick.query
                   .options(*_feed_options())
                   .filter_by(approved_to_publish=True)
                   .order_by(Shtick.pub_date.desc())
                   .offset(offset).limit(PAGE_SIZE).all())
    else:
        # A post can carry several categories (many-to-many) — match on ANY of
        # them, not just the legacy single generalc_id, so filtering by a tag
        # a post has actually finds it regardless of which one is "primary".
        shticks = (Shtick.query
                   .options(*_feed_options())
                   .filter(Shtick.approved_to_publish.is_(True))
                   .filter(Shtick.categories.any(Generalc.id == generalc_id))
                   .order_by(Shtick.pub_date.desc())
                   .offset(offset).limit(PAGE_SIZE).all())

    response = jsonify(shticks_feed_schema.dump(shticks))
    # s-maxage lets Vercel's edge CDN cache this across every region/container,
    # unlike the in-process SimpleCache above which only helps a single warm
    # serverless instance re-hit by luck.
    response.headers['Cache-Control'] = 'public, s-maxage=60, stale-while-revalidate=300'
    cache.set(cache_key, response, timeout=60)
    return response


@shtick_api.route('/random', methods=['GET'])
def get_random_shtick():
    """One random approved post -- backs the Home board's "Shake the Board"
    button. Deliberately uncached (a cached "random" pick would just be the
    same post over and over until the cache expired, defeating the point)."""
    pick = (Shtick.query
            .options(*_feed_options())
            .filter_by(approved_to_publish=True)
            .order_by(func.random())
            .first())
    if not pick:
        return jsonify({'message': 'Nothing to shake loose yet'}), 404
    return jsonify(shtick_feed_schema.dump(pick))


@shtick_api.route('', methods=['POST'])
@token_required
def create_shtick(current_user):
    body = request.get_json()
    if not body or not body.get('caption'):
        return jsonify({'message': 'Caption is required'}), 400
    if len(body['caption']) > 120:
        return jsonify({'message': 'Caption must be 120 characters or fewer'}), 400
    if body.get('credit') and len(body['credit']) > 125:
        return jsonify({'message': 'Credit must be 125 characters or fewer'}), 400

    # One category picker, multiple options selectable — category_id (singular)
    # is still accepted for old callers, folded into the list either way.
    category_ids = list(body.get('category_ids') or [])
    primary_id = body.get('category_id')
    if primary_id and primary_id not in category_ids:
        category_ids = [primary_id] + category_ids
    if not category_ids:
        return jsonify({'message': 'Please select at least one category'}), 400

    new_shtick = Shtick(
        caption=body['caption'],
        credit=body.get('credit', ''),
        specific_category=body.get('specific_category', ''),
        user_id=current_user.public_id,
        generalc_id=category_ids[0]
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
