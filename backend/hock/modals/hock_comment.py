from config import db
from datetime import datetime


class HockComment(db.Model):
    __tablename__ = 'hock_comment'

    id = db.Column(db.Integer, primary_key=True)
    text = db.Column(db.Text, nullable=False)
    hock_post_id = db.Column(db.Integer, db.ForeignKey('hock_post.id'), nullable=False, index=True)
    user_id = db.Column(db.String(50), db.ForeignKey('user.public_id'), nullable=True)
    parent_comment_id = db.Column(db.Integer, db.ForeignKey('hock_comment.id'), nullable=True, index=True)
    pub_date = db.Column(db.DateTime, default=datetime.utcnow)
    edited_at = db.Column(db.DateTime, nullable=True)
    # True = visible, False = taken down by a moderator, None = a pending
    # guest comment awaiting admin review (see routes/hock_comment.py's
    # guest block) -- get_comments' existing
    # `filter_by(approved_to_publish=True)` already excludes a pending
    # guest comment with zero route-filter changes needed. Deliberately no
    # Python-side `default=` AND no `server_default=` here -- either one
    # makes SQLAlchemy quietly substitute True whenever the ORM attribute
    # is None at flush time (confirmed live), which would clobber a guest
    # comment's real None right back to True. __init__'s own
    # `approved_to_publish=True` parameter default already covers every
    # non-guest call site.
    approved_to_publish = db.Column(db.Boolean, nullable=True)

    # Guest posting: filled only when this comment was submitted without an
    # account. guest_manage_token is the no-login credential -- a private
    # link emailed to the submitter, validated purely by this unique token.
    guest_email = db.Column(db.String(150), nullable=True)
    guest_phone = db.Column(db.String(40), nullable=True)
    guest_manage_token = db.Column(db.String(64), nullable=True, unique=True, index=True)

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

    def __init__(self, text, hock_post_id, user_id=None, parent_comment_id=None,
                 approved_to_publish=True, guest_email=None, guest_phone=None,
                 guest_manage_token=None):
        self.text = text
        self.hock_post_id = hock_post_id
        self.user_id = user_id
        self.parent_comment_id = parent_comment_id
        self.approved_to_publish = approved_to_publish
        self.guest_email = guest_email
        self.guest_phone = guest_phone
        self.guest_manage_token = guest_manage_token

    def __repr__(self):
        return f'HockComment({self.id}) by {self.user_id}'
