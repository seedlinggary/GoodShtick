from config import db
from datetime import datetime


class BusinessComment(db.Model):
    __tablename__ = 'business_comment'

    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(db.Integer, db.ForeignKey('business.id'), nullable=False, index=True)
    user_id = db.Column(db.String(50), db.ForeignKey('user.public_id'), nullable=True, index=True)
    body = db.Column(db.Text, nullable=False)
    pub_date = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    # True = visible, False = taken down by an admin, None = a pending guest
    # comment awaiting admin review (see routes/business_comment.py's guest
    # block) -- list_comments' existing `filter_by(approved_to_publish=True)`
    # already excludes a pending guest comment with zero route-filter
    # changes needed. Deliberately no Python-side `default=` AND no
    # `server_default=` here -- either one makes SQLAlchemy quietly
    # substitute True whenever the ORM attribute is None at flush time
    # (confirmed live), which would clobber a guest comment's real None
    # right back to True. __init__'s own `approved_to_publish=True`
    # parameter default already covers every non-guest call site.
    approved_to_publish = db.Column(db.Boolean, nullable=True)

    # Guest posting: filled only when this comment was submitted without an
    # account. guest_manage_token is the no-login credential -- a private
    # link emailed to the submitter, validated purely by this unique token.
    guest_email = db.Column(db.String(150), nullable=True)
    guest_phone = db.Column(db.String(40), nullable=True)
    guest_manage_token = db.Column(db.String(64), nullable=True, unique=True, index=True)

    business = db.relationship('Business', backref=db.backref('comments', lazy=True, cascade='all, delete-orphan'))
    user = db.relationship('User', backref=db.backref('business_comments', lazy=True))

    def __init__(self, business_id, user_id=None, body=None, approved_to_publish=True,
                 guest_email=None, guest_phone=None, guest_manage_token=None):
        self.business_id = business_id
        self.user_id = user_id
        self.body = body
        self.approved_to_publish = approved_to_publish
        self.guest_email = guest_email
        self.guest_phone = guest_phone
        self.guest_manage_token = guest_manage_token

    def __repr__(self):
        return f'BusinessComment({self.id}) business={self.business_id} by={self.user_id}'
