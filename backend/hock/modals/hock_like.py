from config import db
from datetime import datetime


class HockPostLike(db.Model):
    __tablename__ = 'hock_post_like'

    id = db.Column(db.Integer, primary_key=True)
    hock_post_id = db.Column(db.Integer, db.ForeignKey('hock_post.id'), nullable=False)
    user_id = db.Column(db.String(50), db.ForeignKey('user.public_id'), nullable=False)
    pub_date = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', foreign_keys=[user_id], backref=db.backref('hock_post_likes', lazy=True))

    __table_args__ = (db.UniqueConstraint('hock_post_id', 'user_id', name='uq_hock_post_like'),)

    def __init__(self, hock_post_id, user_id):
        self.hock_post_id = hock_post_id
        self.user_id = user_id


class HockCommentLike(db.Model):
    __tablename__ = 'hock_comment_like'

    id = db.Column(db.Integer, primary_key=True)
    hock_comment_id = db.Column(db.Integer, db.ForeignKey('hock_comment.id'), nullable=False)
    user_id = db.Column(db.String(50), db.ForeignKey('user.public_id'), nullable=False)
    pub_date = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', foreign_keys=[user_id], backref=db.backref('hock_comment_likes', lazy=True))

    __table_args__ = (db.UniqueConstraint('hock_comment_id', 'user_id', name='uq_hock_comment_like'),)

    def __init__(self, hock_comment_id, user_id):
        self.hock_comment_id = hock_comment_id
        self.user_id = user_id
