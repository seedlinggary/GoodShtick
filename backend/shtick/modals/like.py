from config import db
from datetime import datetime


class Like(db.Model):
    __tablename__ = 'like'

    id = db.Column(db.Integer, primary_key=True)
    pub_date = db.Column(db.DateTime, default=datetime.utcnow)
    shtick_id = db.Column(db.Integer, db.ForeignKey('shtick.id'), nullable=False, index=True)
    user_id = db.Column(db.String(50), db.ForeignKey('user.public_id'), index=True)
    user = db.relationship('User', foreign_keys=[user_id], backref=db.backref('likes', lazy=True))

    def __init__(self, user_id, shtick_id):
        self.user_id = user_id
        self.shtick_id = shtick_id
