from config import db
from datetime import datetime

# Many-to-many join table for multiple categories per shtick
shtick_categories = db.Table(
    'shtick_categories',
    db.Column('shtick_id', db.Integer, db.ForeignKey('shtick.id'), primary_key=True),
    db.Column('generalc_id', db.Integer, db.ForeignKey('generalc.id'), primary_key=True)
)


class Shtick(db.Model):
    __tablename__ = 'shtick'

    id = db.Column(db.Integer, primary_key=True)
    caption = db.Column(db.String(120))
    credit = db.Column(db.String(125))
    specific_category = db.Column(db.String(120))
    pub_date = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    # Already nullable -- a guest (no-account) post has no user_id at all
    # (see routes/shtick.py's create_guest_shtick), identified instead by
    # its own guest_email/guest_phone + guest_manage_token below.
    user_id = db.Column(db.String(50), db.ForeignKey('user.public_id'), index=True)
    approved_by = db.Column(db.String(50), db.ForeignKey('user.public_id'), nullable=True)
    generalc_id = db.Column(db.Integer, db.ForeignKey('generalc.id'), index=True)
    approved_to_publish = db.Column(db.Boolean, default=None)
    view_count = db.Column(db.Integer, default=0, nullable=False)
    # Guest ("post without an account") fields -- only set when user_id is
    # None. guest_manage_token is the no-login credential: a private link
    # emailed to the poster (see backend/alerts/emails.py's
    # send_guest_submission_email) that lets them view/edit/delete this post
    # purely by presenting the token, same shape as TachlisPost's
    # still_available_token.
    guest_email = db.Column(db.String(150), nullable=True)
    guest_phone = db.Column(db.String(40), nullable=True)
    guest_manage_token = db.Column(db.String(64), nullable=True, unique=True, index=True)

    __table_args__ = (
        # Matches the exact filter+sort pattern used by every feed/listing query:
        # WHERE approved_to_publish = ... ORDER BY pub_date DESC.
        db.Index('ix_shtick_approved_pub_date', 'approved_to_publish', 'pub_date'),
    )

    # Relationships
    user = db.relationship('User', foreign_keys=[user_id],
                            backref=db.backref('shticks', lazy=True))
    approver = db.relationship('User', foreign_keys=[approved_by],
                                backref=db.backref('approved_shticks', lazy=True))
    categories = db.relationship('Generalc', secondary=shtick_categories,
                                  backref=db.backref('tagged_shticks', lazy='dynamic'))
    content = db.relationship('Content', backref='shtick', lazy=True, uselist=False,
                               cascade='all, delete-orphan')
    url = db.relationship('Url', backref='shtick', lazy=True, uselist=False,
                           cascade='all, delete-orphan')
    picture = db.relationship('Picture', backref='shtick', lazy=True, uselist=False,
                               cascade='all, delete-orphan')
    likes = db.relationship('Like', backref='shtick', lazy=True, cascade='all, delete-orphan')
    comments = db.relationship('Comment', backref='shtick', lazy=True,
                                cascade='all, delete-orphan', order_by='Comment.pub_date.asc()')

    def __init__(self, caption, credit, specific_category, user_id, generalc_id,
                 guest_email=None, guest_phone=None, guest_manage_token=None):
        self.caption = caption
        self.credit = credit
        self.specific_category = specific_category
        self.user_id = user_id
        self.generalc_id = generalc_id
        self.guest_email = guest_email
        self.guest_phone = guest_phone
        self.guest_manage_token = guest_manage_token

    def __repr__(self):
        return f'{self.caption}'
