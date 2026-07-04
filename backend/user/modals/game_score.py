from config import db
from datetime import datetime


class GameScore(db.Model):
    __tablename__ = 'game_score'

    id = db.Column(db.Integer, primary_key=True)
    game_type = db.Column(db.String(50), nullable=False)   # hangman, snake, sudoku, minesweeper
    result = db.Column(db.String(20), nullable=False)       # win, loss, win_with_hint
    difficulty = db.Column(db.String(20), default='medium') # easy, medium, hard
    score = db.Column(db.Integer, default=0)
    pub_date = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.String(50), db.ForeignKey('user.public_id'), nullable=False)

    user = db.relationship('User', backref=db.backref('game_scores', lazy=True))

    def __init__(self, game_type, result, difficulty, score, user_id):
        self.game_type = game_type
        self.result = result
        self.difficulty = difficulty
        self.score = score
        self.user_id = user_id

    def __repr__(self):
        return f'GameScore({self.game_type} {self.result} by {self.user_id})'
