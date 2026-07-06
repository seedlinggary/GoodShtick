from datetime import datetime, timedelta

from flask import Blueprint, jsonify, request
from config import db
from security import token_required
from backend.user.modals.game_score import GameScore
from backend.user.schemas.game_score import game_score_schema, game_scores_schema
from backend.notifications.helpers import notify

game_api = Blueprint('game_api', __name__, url_prefix='/game')

VALID_PERIODS = {'daily', 'weekly', 'monthly', 'yearly', 'all_time'}
PERIOD_DAYS = {'daily': 1, 'weekly': 7, 'monthly': 30, 'yearly': 365}

VALID_GAMES = {
    # original solo
    'hangman', 'snake', 'sudoku', 'minesweeper',
    'wordle', 'word_scramble', 'simon', 'memory_match', '2048', 'lights_out',
    # new solo strategy
    'kenken', 'kakuro', 'nonogram', 'n_queens', 'futoshiki', 'binary_puzzle',
    'skyscrapers', 'fifteen_puzzle', 'towers_hanoi', 'flow_free', 'cryptogram',
    'sokoban', 'hashi', 'nurikabe', 'mastermind',
    # 1v1 games
    'chess', 'checkers', 'connect_four', 'reversi', 'battleship',
    'dots_and_boxes', 'tic_tac_toe', 'nim', 'word_duel', 'mancala',
    # multiplayer games
    'spades', 'uno', 'yahtzee', 'poker', 'codenames',
    'catan', 'scrabble_lite', 'clue', 'risk', 'rummy',
}
VALID_RESULTS = {'win', 'loss', 'win_with_hint'}
VALID_DIFFICULTIES = {'easy', 'medium', 'hard'}


@game_api.route('/scores', methods=['GET'])
@token_required
def get_my_scores(current_user):
    scores = GameScore.query.filter_by(user_id=current_user.public_id).order_by(
        GameScore.pub_date.desc()
    ).all()
    return jsonify(game_scores_schema.dump(scores))


@game_api.route('/stats', methods=['GET'])
@token_required
def get_my_stats(current_user):
    scores = GameScore.query.filter_by(user_id=current_user.public_id).all()
    stats = {}
    for game in VALID_GAMES:
        game_scores = [s for s in scores if s.game_type == game]
        stats[game] = {
            'wins': sum(1 for s in game_scores if s.result == 'win'),
            'losses': sum(1 for s in game_scores if s.result == 'loss'),
            'wins_with_hint': sum(1 for s in game_scores if s.result == 'win_with_hint'),
            'best_score': max((s.score for s in game_scores), default=0),
            'total_games': len(game_scores),
        }
    return jsonify(stats)


@game_api.route('/leaderboard/<game_type>', methods=['GET'])
def get_leaderboard(game_type):
    if game_type not in VALID_GAMES:
        return jsonify({'message': 'Invalid game type'}), 400
    from sqlalchemy import func
    from backend.user.modals.user import User

    period = request.args.get('period', 'all_time')
    if period not in VALID_PERIODS:
        period = 'all_time'
    try:
        limit = min(max(int(request.args.get('limit', 20)), 1), 25)
    except (TypeError, ValueError):
        limit = 20

    filters = [GameScore.game_type == game_type, GameScore.result.in_(['win', 'win_with_hint'])]
    if period in PERIOD_DAYS:
        filters.append(GameScore.pub_date >= datetime.utcnow() - timedelta(days=PERIOD_DAYS[period]))

    rows = (
        db.session.query(
            GameScore.user_id,
            func.max(GameScore.score).label('best'),
            func.sum(GameScore.score).label('total'),
            func.count(GameScore.id).label('games'),
        )
        .filter(*filters)
        .group_by(GameScore.user_id)
        .order_by(func.max(GameScore.score).desc())
        .limit(limit)
        .all()
    )
    # One batched user lookup instead of one query per row.
    users_by_id = {
        u.public_id: u.profile_name
        for u in User.query.filter(User.public_id.in_([r.user_id for r in rows])).all()
    } if rows else {}
    result = [{
        'profile_name': users_by_id.get(row.user_id, 'Unknown'),
        'best_score': row.best,
        'total_score': row.total,
        'games': row.games,
    } for row in rows]
    response = jsonify(result)
    response.headers['Cache-Control'] = 'public, s-maxage=60, stale-while-revalidate=300'
    return response


@game_api.route('/leaderboards/top3', methods=['GET'])
def get_all_top3_leaderboards():
    """Top-3 all-time leaderboard for every game, in a single query — used by the
    Games hub so it doesn't have to fire one /leaderboard/<game_type> request per
    game card (was 45 requests + 45 queries on page load; this is 1 of each)."""
    from sqlalchemy import func
    from backend.user.modals.user import User

    per_user_per_game = (
        db.session.query(
            GameScore.game_type.label('game_type'),
            GameScore.user_id.label('user_id'),
            func.max(GameScore.score).label('best'),
            func.sum(GameScore.score).label('total'),
            func.count(GameScore.id).label('games'),
        )
        .filter(GameScore.result.in_(['win', 'win_with_hint']))
        .group_by(GameScore.game_type, GameScore.user_id)
        .subquery()
    )
    ranked = (
        db.session.query(
            per_user_per_game,
            func.row_number().over(
                partition_by=per_user_per_game.c.game_type,
                order_by=per_user_per_game.c.best.desc(),
            ).label('rnk'),
        )
        .subquery()
    )
    rows = db.session.query(ranked).filter(ranked.c.rnk <= 3).all()

    users_by_id = {
        u.public_id: u.profile_name
        for u in User.query.filter(User.public_id.in_({r.user_id for r in rows})).all()
    } if rows else {}

    result = {}
    for row in rows:
        result.setdefault(row.game_type, []).append({
            'profile_name': users_by_id.get(row.user_id, 'Unknown'),
            'best_score': row.best,
            'total_score': row.total,
            'games': row.games,
            'rank': row.rnk,
        })
    for game_type in result:
        result[game_type].sort(key=lambda e: e['rank'])
        for e in result[game_type]:
            del e['rank']
    response = jsonify(result)
    response.headers['Cache-Control'] = 'public, s-maxage=60, stale-while-revalidate=300'
    return response


@game_api.route('/save', methods=['POST'])
@token_required
def save_score(current_user):
    body = request.get_json()
    if not body:
        return jsonify({'message': 'Body required'}), 400
    game_type = body.get('game_type', '').lower()
    result = body.get('result', '').lower()
    difficulty = body.get('difficulty', 'medium').lower()
    score = int(body.get('score', 0))

    if game_type not in VALID_GAMES:
        return jsonify({'message': f'Invalid game_type. Must be one of: {", ".join(VALID_GAMES)}'}), 400
    if result not in VALID_RESULTS:
        return jsonify({'message': f'Invalid result. Must be one of: {", ".join(VALID_RESULTS)}'}), 400
    if difficulty not in VALID_DIFFICULTIES:
        difficulty = 'medium'

    # Snapshot the current #1 before adding the new score, so we can tell
    # afterward whether this save just knocked someone off the top spot.
    previous_leader = None
    if result in ('win', 'win_with_hint') and score > 0:
        from sqlalchemy import func
        previous_leader = (
            db.session.query(GameScore.user_id, func.max(GameScore.score).label('best'))
            .filter(GameScore.game_type == game_type, GameScore.result.in_(['win', 'win_with_hint']))
            .group_by(GameScore.user_id)
            .order_by(func.max(GameScore.score).desc())
            .first()
        )

    gs = GameScore(
        game_type=game_type,
        result=result,
        difficulty=difficulty,
        score=score,
        user_id=current_user.public_id
    )
    db.session.add(gs)

    if previous_leader and previous_leader.user_id != current_user.public_id and score > previous_leader.best:
        game_label = game_type.replace('_', ' ').title()
        notify(
            previous_leader.user_id,
            f"{current_user.profile_name} just beat your #1 score on {game_label}!",
            type='leaderboard',
            actor_id=current_user.public_id,
            link='/games',
        )

    db.session.commit()
    return jsonify(game_score_schema.dump(gs)), 201
