from flask import Blueprint, jsonify, request
from config import db
from security import token_required
from backend.user.modals.game_score import GameScore
from backend.user.schemas.game_score import game_score_schema, game_scores_schema

game_api = Blueprint('game_api', __name__, url_prefix='/game')

VALID_GAMES = {
    'hangman', 'snake', 'sudoku', 'minesweeper',
    'wordle', 'word_scramble', 'simon', 'memory_match', '2048', 'lights_out',
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
    rows = (
        db.session.query(
            GameScore.user_id,
            func.max(GameScore.score).label('best'),
            func.sum(GameScore.score).label('total'),
            func.count(GameScore.id).label('games'),
        )
        .filter(GameScore.game_type == game_type, GameScore.result.in_(['win', 'win_with_hint']))
        .group_by(GameScore.user_id)
        .order_by(func.max(GameScore.score).desc())
        .limit(20)
        .all()
    )
    result = []
    for row in rows:
        user = User.query.filter_by(public_id=row.user_id).first()
        result.append({
            'profile_name': user.profile_name if user else 'Unknown',
            'best_score': row.best,
            'total_score': row.total,
            'games': row.games,
        })
    return jsonify(result)


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

    gs = GameScore(
        game_type=game_type,
        result=result,
        difficulty=difficulty,
        score=score,
        user_id=current_user.public_id
    )
    db.session.add(gs)
    db.session.commit()
    return jsonify(game_score_schema.dump(gs)), 201
