from config import db
from datetime import datetime


class HockPost(db.Model):
    __tablename__ = 'hock_post'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    body = db.Column(db.Text, nullable=False)
    image = db.Column(db.String(255), nullable=True)
    user_id = db.Column(db.String(50), db.ForeignKey('user.public_id'), nullable=False, index=True)
    pub_date = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    edited_at = db.Column(db.DateTime, nullable=True)
    # Posts auto-publish (True by default) same as always -- this only gives
    # super_admin a reversible takedown switch, not a pre-publish approval gate.
    approved_to_publish = db.Column(db.Boolean, default=True, server_default='true', nullable=False)
    approved_by = db.Column(db.String(50), db.ForeignKey('user.public_id'), nullable=True)

    user = db.relationship('User', foreign_keys=[user_id], backref=db.backref('hock_posts', lazy=True))
    approver = db.relationship('User', foreign_keys=[approved_by], backref=db.backref('approved_hock_posts', lazy=True))
    comments = db.relationship('HockComment', backref='post', lazy=True, cascade='all, delete-orphan')
    likes = db.relationship('HockPostLike', backref='post', lazy=True, cascade='all, delete-orphan')

    __table_args__ = (
        db.Index('ix_hock_post_approved_pub_date', 'approved_to_publish', 'pub_date'),
    )

    def __init__(self, title, body, user_id, image=None):
        self.title = title
        self.body = body
        self.user_id = user_id
        self.image = image

    def __repr__(self):
        return f'HockPost({self.id}) {self.title}'
