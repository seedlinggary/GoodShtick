from flask import Blueprint, jsonify, request
from sqlalchemy import func
from sqlalchemy.orm import selectinload
from config import db, cache
from security import admin_required, super_admin_required
from backend.user.modals.user import User
from backend.user.schemas.user import user_schema
from backend.shtick.modals.shtick import Shtick
from backend.shtick.schemas.shtick import shticks_schema
from backend.shtick.modals.comment import Comment
from backend.shtick.schemas.shtick import comments_schema
from backend.shtick.modals.like import Like
from backend.shtick.modals.content import Content
from backend.shtick.modals.generalc import Generalc
from backend.hock.modals.hock_post import HockPost
from backend.hock.modals.hock_comment import HockComment
from backend.tachlis.modals.tachlis_post import TachlisPost
from backend.user.modals.game_score import GameScore
from backend.user.schemas.game_score import game_scores_schema

def _admin_options():
    """Eager-load options for admin views. Evaluated at request time after all mappers are ready."""
    return [
        selectinload(Shtick.user),
        selectinload(Shtick.approver),
        selectinload(Shtick.categories),
        selectinload(Shtick.likes),
        selectinload(Shtick.comments).selectinload(Comment.user),
        selectinload(Shtick.content),
        selectinload(Shtick.url),
        selectinload(Shtick.picture),
    ]

admin_api = Blueprint('admin_api', __name__, url_prefix='/admin')


# ── Admin routes ──────────────────────────────────────────────────────────────

@admin_api.route('/pending', methods=['GET'])
@admin_required
def get_pending(_current_user):
    pending = (Shtick.query
               .options(*_admin_options())
               .filter_by(approved_to_publish=None)
               .order_by(Shtick.pub_date.desc()).all())
    return jsonify(shticks_schema.dump(pending))


@admin_api.route('/shtick/<int:shtick_id>/approve', methods=['POST'])
@admin_required
def approve_shtick(current_user, shtick_id):
    body = request.get_json() or {}
    shtick = db.session.get(Shtick, shtick_id)
    if not shtick:
        return jsonify({'message': 'Not found'}), 404
    approved = not body.get('reject', False)
    shtick.approved_to_publish = approved
    shtick.approved_by = current_user.public_id
    db.session.commit()
    cache.clear()
    return jsonify({'message': 'approved' if approved else 'rejected'})


@admin_api.route('/shtick/<int:shtick_id>/unapprove', methods=['POST'])
@super_admin_required
def unapprove_shtick(_current_user, shtick_id):
    """Revert an already-approved (or rejected) post back to the pending queue."""
    shtick = db.session.get(Shtick, shtick_id)
    if not shtick:
        return jsonify({'message': 'Not found'}), 404
    shtick.approved_to_publish = None
    shtick.approved_by = None
    db.session.commit()
    cache.clear()
    return jsonify({'message': 'unapproved'})


MAX_BULK_APPROVE = 200


@admin_api.route('/shtick/bulk-approve', methods=['POST'])
@admin_required
def bulk_approve_shtick(current_user):
    """Approve or reject many pending posts in one request -- avoids clicking
    Approve/Reject one at a time on a large backlog."""
    body = request.get_json() or {}
    ids = body.get('ids')
    if not ids or not isinstance(ids, list):
        return jsonify({'message': 'ids must be a non-empty list'}), 400
    if len(ids) > MAX_BULK_APPROVE:
        return jsonify({'message': f'Cannot process more than {MAX_BULK_APPROVE} at once'}), 400

    approved = not body.get('reject', False)
    updated = (
        Shtick.query.filter(Shtick.id.in_(ids))
        .update(
            {'approved_to_publish': approved, 'approved_by': current_user.public_id},
            synchronize_session=False,
        )
    )
    db.session.commit()
    cache.clear()
    return jsonify({'message': 'approved' if approved else 'rejected', 'updated': updated})


@admin_api.route('/shtick/<int:shtick_id>', methods=['PATCH'])
@admin_required
def edit_shtick(current_user, shtick_id):
    body = request.get_json() or {}
    shtick = db.session.get(Shtick, shtick_id)
    if not shtick:
        return jsonify({'message': 'Not found'}), 404
    if 'caption' in body:
        shtick.caption = body['caption']
    if 'credit' in body:
        shtick.credit = body['credit']
    db.session.commit()
    cache.clear()
    from backend.shtick.schemas.shtick import shtick_schema
    return jsonify(shtick_schema.dump(shtick))


@admin_api.route('/shtick/<int:shtick_id>', methods=['DELETE'])
@admin_required
def delete_shtick(_current_user, shtick_id):
    shtick = db.session.get(Shtick, shtick_id)
    if not shtick:
        return jsonify({'message': 'Not found'}), 404
    db.session.delete(shtick)
    db.session.commit()
    cache.clear()
    return jsonify({'message': 'Deleted'})


@admin_api.route('/shticks', methods=['GET'])
@admin_required
def all_shticks(_current_user):
    shticks = (Shtick.query
               .options(*_admin_options())
               .order_by(Shtick.pub_date.desc())
               .limit(200).all())
    return jsonify(shticks_schema.dump(shticks))


@admin_api.route('/comments', methods=['GET'])
@admin_required
def all_comments(_current_user):
    comments = Comment.query.order_by(Comment.pub_date.desc()).limit(200).all()
    return jsonify(comments_schema.dump(comments))


@admin_api.route('/comments/<int:comment_id>/unapprove', methods=['POST'])
@super_admin_required
def unapprove_comment(_current_user, comment_id):
    """Hide a feed comment from public view without deleting it."""
    comment = db.session.get(Comment, comment_id)
    if not comment:
        return jsonify({'message': 'Not found'}), 404
    comment.approved_to_publish = False
    db.session.commit()
    return jsonify({'message': 'unapproved'})


@admin_api.route('/comments/<int:comment_id>/approve', methods=['POST'])
@super_admin_required
def approve_comment(_current_user, comment_id):
    """Restore a hidden feed comment to public view."""
    comment = db.session.get(Comment, comment_id)
    if not comment:
        return jsonify({'message': 'Not found'}), 404
    comment.approved_to_publish = True
    db.session.commit()
    return jsonify({'message': 'approved'})


# ── Super-admin routes ────────────────────────────────────────────────────────

@admin_api.route('/users', methods=['GET'])
@super_admin_required
def list_users(_current_user):
    users = User.query.order_by(User.pub_date.asc()).all()

    # Batched counts instead of N+1 lazy-loading each user's four collections
    # (was 1 + 4*N queries for N users -- now a fixed 4 regardless of N).
    def counts_by_user(group_col):
        rows = db.session.query(group_col, func.count()).group_by(group_col).all()
        return dict(rows)

    shtick_counts = counts_by_user(Shtick.user_id)
    like_counts = counts_by_user(Like.user_id)
    comment_counts = counts_by_user(Comment.user_id)
    game_counts = counts_by_user(GameScore.user_id)

    result = []
    for u in users:
        data = user_schema.dump(u)
        data['shtick_count'] = shtick_counts.get(u.public_id, 0)
        data['like_count'] = like_counts.get(u.public_id, 0)
        data['comment_count'] = comment_counts.get(u.public_id, 0)
        data['game_count'] = game_counts.get(u.public_id, 0)
        result.append(data)
    return jsonify(result)


@admin_api.route('/users/<public_id>/role', methods=['PATCH'])
@super_admin_required
def set_user_role(_current_user, public_id):
    body = request.get_json() or {}
    new_role = body.get('role')
    valid_roles = {'viewer', 'user', 'admin', 'super_admin'}
    if new_role not in valid_roles:
        return jsonify({'message': f'role must be one of: {", ".join(valid_roles)}'}), 400
    user = User.query.filter_by(public_id=public_id).first()
    if not user:
        return jsonify({'message': 'User not found'}), 404
    user.role = new_role
    db.session.commit()
    return jsonify(user_schema.dump(user))


@admin_api.route('/users/<public_id>/activity', methods=['GET'])
@super_admin_required
def user_activity(_current_user, public_id):
    user = User.query.filter_by(public_id=public_id).first()
    if not user:
        return jsonify({'message': 'User not found'}), 404
    likes_data = [{'shtick_id': l.shtick_id, 'pub_date': str(l.pub_date)} for l in user.likes]
    comments_data = [{'text': c.text, 'shtick_id': c.shtick_id, 'pub_date': str(c.pub_date)}
                     for c in user.comments]
    shticks_data = [{'id': s.id, 'caption': s.caption, 'approved': s.approved_to_publish,
                     'pub_date': str(s.pub_date)} for s in user.shticks]
    scores_data = game_scores_schema.dump(user.game_scores)
    return jsonify({
        'user': user_schema.dump(user),
        'shticks': shticks_data,
        'likes': likes_data,
        'comments': comments_data,
        'game_scores': scores_data,
    })


@admin_api.route('/stats', methods=['GET'])
@super_admin_required
@cache.cached(timeout=60)
def platform_stats(_current_user):
    total_users = User.query.count()
    total_shticks = Shtick.query.count()
    pending_shticks = Shtick.query.filter_by(approved_to_publish=None).count()
    approved_shticks = Shtick.query.filter_by(approved_to_publish=True).count()
    total_comments = Comment.query.count()
    total_likes = Like.query.count()
    total_games = GameScore.query.count()
    return jsonify({
        'users': total_users,
        'shticks': {'total': total_shticks, 'pending': pending_shticks, 'approved': approved_shticks},
        'comments': total_comments,
        'likes': total_likes,
        'game_sessions': total_games,
    })


@admin_api.route('/rejected', methods=['GET'])
@admin_required
def get_rejected(_current_user):
    rejected = (Shtick.query
                .options(*_admin_options())
                .filter(Shtick.approved_to_publish.is_(False))
                .order_by(Shtick.pub_date.desc()).all())
    return jsonify(shticks_schema.dump(rejected))


@admin_api.route('/approvals', methods=['GET'])
@super_admin_required
def approval_history(_current_user):
    approved = (Shtick.query
                .options(*_admin_options())
                .filter(Shtick.approved_by.isnot(None))
                .order_by(Shtick.pub_date.desc()).all())
    return jsonify(shticks_schema.dump(approved))


SEARCH_LIMIT = 25


@admin_api.route('/search', methods=['GET'])
@admin_required
def admin_search(_current_user):
    """Cross-table lookup for the SuperAdmin console's search bar -- checks
    id, title/caption/body/text, category, and submitted-by across every
    content type (Feed posts, Hock posts, Hock comments, Tachlis posts, Feed
    comments) plus the Users table itself."""
    q = (request.args.get('q') or '').strip()
    if not q:
        return jsonify({
            'shticks': [], 'hock_posts': [], 'hock_comments': [],
            'tachlis_posts': [], 'comments': [], 'users': [],
        })

    like = f'%{q}%'
    is_id = q.isdigit()

    shtick_filters = [
        Shtick.caption.ilike(like), Shtick.credit.ilike(like),
        Shtick.specific_category.ilike(like), Content.stuff.ilike(like),
        Generalc.name.ilike(like), User.profile_name.ilike(like), User.email.ilike(like),
    ]
    if is_id:
        shtick_filters.append(Shtick.id == int(q))
    shticks = (Shtick.query
               .join(Shtick.user)
               .outerjoin(Shtick.content)
               .outerjoin(Shtick.categories)
               .filter(db.or_(*shtick_filters))
               .order_by(Shtick.pub_date.desc())
               .distinct().limit(SEARCH_LIMIT).all())
    shticks_data = [{
        'id': s.id, 'caption': s.caption, 'approved_to_publish': s.approved_to_publish,
        'pub_date': str(s.pub_date), 'submitted_by': s.user.profile_name if s.user else None,
    } for s in shticks]

    hock_filters = [
        HockPost.title.ilike(like), HockPost.body.ilike(like),
        User.profile_name.ilike(like), User.email.ilike(like),
    ]
    if is_id:
        hock_filters.append(HockPost.id == int(q))
    hock_posts = (HockPost.query.join(HockPost.user)
                  .filter(db.or_(*hock_filters))
                  .order_by(HockPost.pub_date.desc())
                  .limit(SEARCH_LIMIT).all())
    hock_posts_data = [{
        'id': p.id, 'title': p.title, 'approved_to_publish': p.approved_to_publish,
        'pub_date': str(p.pub_date), 'submitted_by': p.user.profile_name if p.user else None,
    } for p in hock_posts]

    hock_comment_filters = [HockComment.text.ilike(like), User.profile_name.ilike(like), User.email.ilike(like)]
    if is_id:
        hock_comment_filters.append(HockComment.id == int(q))
    hock_comments = (HockComment.query.join(HockComment.user)
                      .filter(db.or_(*hock_comment_filters))
                      .order_by(HockComment.pub_date.desc())
                      .limit(SEARCH_LIMIT).all())
    hock_comments_data = [{
        'id': c.id, 'text': c.text, 'hock_post_id': c.hock_post_id,
        'approved_to_publish': c.approved_to_publish, 'pub_date': str(c.pub_date),
        'submitted_by': c.user.profile_name if c.user else None,
    } for c in hock_comments]

    tachlis_filters = [
        TachlisPost.title.ilike(like), TachlisPost.body.ilike(like), TachlisPost.post_type.ilike(like),
        TachlisPost.location.ilike(like), TachlisPost.compensation.ilike(like), TachlisPost.contact.ilike(like),
        User.profile_name.ilike(like), User.email.ilike(like),
    ]
    if is_id:
        tachlis_filters.append(TachlisPost.id == int(q))
    tachlis_posts = (TachlisPost.query.join(TachlisPost.user)
                      .filter(db.or_(*tachlis_filters))
                      .order_by(TachlisPost.pub_date.desc())
                      .limit(SEARCH_LIMIT).all())
    tachlis_posts_data = [{
        'id': t.id, 'title': t.title, 'post_type': t.post_type,
        'approved_to_publish': t.approved_to_publish, 'pub_date': str(t.pub_date),
        'submitted_by': t.user.profile_name if t.user else None,
    } for t in tachlis_posts]

    comment_filters = [Comment.text.ilike(like), User.profile_name.ilike(like), User.email.ilike(like)]
    if is_id:
        comment_filters.append(Comment.id == int(q))
    comments = (Comment.query.join(Comment.user)
                .filter(db.or_(*comment_filters))
                .order_by(Comment.pub_date.desc())
                .limit(SEARCH_LIMIT).all())
    comments_data = [{
        'id': c.id, 'text': c.text, 'shtick_id': c.shtick_id,
        'approved_to_publish': c.approved_to_publish, 'pub_date': str(c.pub_date),
        'submitted_by': c.user.profile_name if c.user else None,
    } for c in comments]

    user_filters = [
        User.profile_name.ilike(like), User.email.ilike(like),
        User.first_name.ilike(like), User.last_name.ilike(like), User.public_id.ilike(like),
    ]
    if is_id:
        user_filters.append(User.id == int(q))
    users = User.query.filter(db.or_(*user_filters)).limit(SEARCH_LIMIT).all()
    users_data = [{
        'id': u.id, 'public_id': u.public_id, 'profile_name': u.profile_name,
        'email': u.email, 'role': u.role,
    } for u in users]

    return jsonify({
        'shticks': shticks_data, 'hock_posts': hock_posts_data, 'hock_comments': hock_comments_data,
        'tachlis_posts': tachlis_posts_data, 'comments': comments_data, 'users': users_data,
    })


@admin_api.route('/seed', methods=['POST'])
@super_admin_required
def seed_posts(current_user):
    """Seed sample categories and 10 pending posts. Safe to call multiple times."""
    from backend.shtick.modals.generalc import Generalc
    from backend.shtick.modals.content import Content
    from backend.shtick.modals.url import Url

    defaults = ['Funny', 'Inspiring', 'Videos', 'Tech', 'News', 'Sports', 'Music', 'Random', 'Quotes', 'Viral']
    for name in defaults:
        if not Generalc.query.filter_by(name=name).first():
            db.session.add(Generalc(name=name))
    db.session.commit()
    cats = {c.name: c for c in Generalc.query.all()}

    posts = [
        {'caption': 'The secret of getting ahead is getting started', 'credit': 'Mark Twain', 'generalc': 'Quotes',
         'content': 'The secret of getting ahead is getting started. The secret of getting started is breaking your complex, overwhelming tasks into small, manageable tasks, and then starting on the first one.'},
        {'caption': 'Carl Sagan on the Pale Blue Dot — this will give you chills', 'credit': 'Carl Sagan', 'generalc': 'Inspiring',
         'url': 'https://www.youtube.com/watch?v=GO5FwsblpT8'},
        {'caption': "SNL — Every State's Slogan", 'credit': 'Saturday Night Live', 'generalc': 'Funny',
         'url': 'https://www.youtube.com/watch?v=F57P9C4SAW4'},
        {'caption': "Elon on why he thinks we're likely living in a simulation", 'credit': 'Elon Musk', 'generalc': 'Tech',
         'url': 'https://twitter.com/elonmusk/status/1590044369476767744'},
        {'caption': 'Why procrastination is about emotions, not time management', 'credit': 'TED-Ed', 'generalc': 'Inspiring',
         'url': 'https://www.youtube.com/watch?v=mhFQA998WiA'},
        {'caption': 'Two things are infinite: the universe and human stupidity', 'credit': 'Albert Einstein', 'generalc': 'Funny',
         'content': "Two things are infinite: the universe and human stupidity; and I'm not sure about the universe."},
        {'caption': 'OpenAI releases o3 model — and the AI race just went nuclear', 'credit': 'The Verge', 'generalc': 'Tech',
         'url': 'https://www.theverge.com/2024/12/20/24326141/openai-o3-reasoning-model-safety-benchmark'},
        {'caption': 'Tiny Desk Concert: Chappell Roan', 'credit': 'NPR Music', 'generalc': 'Music',
         'url': 'https://www.youtube.com/watch?v=KrZSaL7w-gY'},
        {'caption': "Life is what happens when you're busy making other plans", 'credit': 'John Lennon', 'generalc': 'Quotes',
         'content': "Life is what happens when you're busy making other plans. Beautiful Boy (Darling Boy), 1980."},
        {'caption': 'A $20 trick that tricks your brain into focusing instantly', 'credit': 'Andrew Huberman', 'generalc': 'Viral',
         'url': 'https://www.youtube.com/watch?v=If58MdFVMRM',
         'content': "Dr. Huberman explains the visual focus trick: look at a fixed point for 30-60 seconds before starting work. It triggers the brain's alertness circuits without caffeine."},
    ]

    added = 0
    for p in posts:
        cat = cats.get(p['generalc'], cats.get('Random'))
        if not cat:
            continue
        s = Shtick(caption=p['caption'], credit=p.get('credit', ''), specific_category='',
                   user_id=current_user.public_id, generalc_id=cat.id)
        db.session.add(s)
        db.session.flush()
        s.categories.append(cat)
        if p.get('content'):
            db.session.add(Content(stuff=p['content'], shtick_id=s.id))
        if p.get('url'):
            db.session.add(Url(name=p['url'], shtick_id=s.id))
        added += 1
    db.session.commit()
    return jsonify({'message': f'Seeded {added} posts pending approval.'})
