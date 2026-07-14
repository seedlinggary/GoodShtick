from config import db
from datetime import datetime


class Comment(db.Model):
    __tablename__ = 'comment'

    id = db.Column(db.Integer, primary_key=True)
    text = db.Column(db.Text, nullable=False)
    pub_date = db.Column(db.DateTime, default=datetime.utcnow)
    shtick_id = db.Column(db.Integer, db.ForeignKey('shtick.id'), nullable=False, index=True)
    user_id = db.Column(db.String(50), db.ForeignKey('user.public_id'), nullable=False)
    # Visible by default -- this is a moderation takedown switch for super_admin,
    # not a pre-publish gate like Shtick/Tachlis's approved_to_publish.
    approved_to_publish = db.Column(db.Boolean, default=True, server_default='true', nullable=False)

    user = db.relationship('User', backref=db.backref('comments', lazy=True))

    def __init__(self, text, shtick_id, user_id):
        self.text = text
        self.shtick_id = shtick_id
        self.user_id = user_id

    def __repr__(self):
        return f'Comment({self.id}) by {self.user_id}'
