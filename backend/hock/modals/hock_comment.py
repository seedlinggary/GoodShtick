from config import db
from datetime import datetime


class HockComment(db.Model):
    __tablename__ = 'hock_comment'

    id = db.Column(db.Integer, primary_key=True)
    text = db.Column(db.Text, nullable=False)
    hock_post_id = db.Column(db.Integer, db.ForeignKey('hock_post.id'), nullable=False, index=True)
    user_id = db.Column(db.String(50), db.ForeignKey('user.public_id'), nullable=False)
    parent_comment_id = db.Column(db.Integer, db.ForeignKey('hock_comment.id'), nullable=True, index=True)
    pub_date = db.Column(db.DateTime, default=datetime.utcnow)
    edited_at = db.Column(db.DateTime, nullable=True)
    # Visible by default -- this is a moderation takedown switch for super_admin,
    # not a pre-publish gate.
    approved_to_publish = db.Column(db.Boolean, default=True, server_default='true', nullable=False)

    user = db.relationship('User', foreign_keys=[user_id], backref=db.backref('hock_comments', lazy=True))
    # Self-referential thread: a comment's direct replies. remote_side pins
    # the "one" side of the relationship to the parent's own id column so
    # SQLAlchemy can tell replies-of apart from parent-of.
    replies = db.relationship(
        'HockComment',
        backref=db.backref('parent', remote_side=[id]),
        cascade='all, delete-orphan',
        single_parent=True,
    )
    likes = db.relationship('HockCommentLike', backref='comment', lazy=True, cascade='all, delete-orphan')

    def __init__(self, text, hock_post_id, user_id, parent_comment_id=None):
        self.text = text
        self.hock_post_id = hock_post_id
        self.user_id = user_id
        self.parent_comment_id = parent_comment_id

    def __repr__(self):
        return f'HockComment({self.id}) by {self.user_id}'
