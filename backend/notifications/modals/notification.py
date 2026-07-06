from config import db
from datetime import datetime


class Notification(db.Model):
    __tablename__ = 'notification'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(50), db.ForeignKey('user.public_id'), nullable=False, index=True)  # recipient
    actor_id = db.Column(db.String(50), nullable=True)  # who triggered it, if anyone
    type = db.Column(db.String(30), nullable=False)  # 'like', 'comment', 'leaderboard'
    message = db.Column(db.String(200), nullable=False)
    link = db.Column(db.String(300), nullable=True)  # frontend path to navigate to on click
    is_read = db.Column(db.Boolean, default=False)
    pub_date = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<Notification {self.id} to={self.user_id} type={self.type}>'
