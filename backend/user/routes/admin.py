from flask import Blueprint, jsonify, request
from sqlalchemy.orm import selectinload
from config import db, cache
from security import admin_required, super_admin_required
from backend.user.modals.user import User
from backend.user.schemas.user import user_schema
from backend.shtick.modals.shtick import Shtick
from backend.shtick.schemas.shtick import shticks_schema
from backend.shtick.modals.comment import Comment
from backend.shtick.schemas.shtick import comments_schema
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


# ── Super-admin routes ────────────────────────────────────────────────────────

@admin_api.route('/users', methods=['GET'])
@super_admin_required
def list_users(_current_user):
    users = User.query.order_by(User.pub_date.asc()).all()
    result = []
    for u in users:
        data = user_schema.dump(u)
        data['shtick_count'] = len(u.shticks)
        data['like_count'] = len(u.likes)
        data['comment_count'] = len(u.comments)
        data['game_count'] = len(u.game_scores)
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
def platform_stats(_current_user):
    total_users = User.query.count()
    total_shticks = Shtick.query.count()
    pending_shticks = Shtick.query.filter_by(approved_to_publish=None).count()
    approved_shticks = Shtick.query.filter_by(approved_to_publish=True).count()
    total_comments = Comment.query.count()
    from backend.shtick.modals.like import Like
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
