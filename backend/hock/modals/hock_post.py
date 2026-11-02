from config import db
from datetime import datetime


class HockPost(db.Model):
    __tablename__ = 'hock_post'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    body = db.Column(db.Text, nullable=False)
    image = db.Column(db.String(255), nullable=True)
    user_id = db.Column(db.String(50), db.ForeignKey('user.public_id'), nullable=True, index=True)
    pub_date = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    edited_at = db.Column(db.DateTime, nullable=True)
    # True by default for every real member's post (still just a reversible
    # super_admin takedown/restore switch for them) -- but also now a real
    # three-state pending gate for guest posts, which explicitly set this to
    # None at creation. See routes/hock_post.py's guest block.
    approved_to_publish = db.Column(db.Boolean, default=True, server_default='true', nullable=True)
    approved_by = db.Column(db.String(50), db.ForeignKey('user.public_id'), nullable=True)

    # Set only for a no-account ("guest") post -- see routes/hock_post.py's
    # create_guest_post. guest_manage_token is the no-login credential: a
    # private link emailed at submission time (and shown once on-screen)
    # that lets the poster edit/delete without ever creating an account.
    guest_email = db.Column(db.String(150), nullable=True)
    guest_phone = db.Column(db.String(40), nullable=True)
    guest_manage_token = db.Column(db.String(64), nullable=True, unique=True, index=True)

    user = db.relationship('User', foreign_keys=[user_id], backref=db.backref('hock_posts', lazy=True))
    approver = db.relationship('User', foreign_keys=[approved_by], backref=db.backref('approved_hock_posts', lazy=True))
    comments = db.relationship('HockComment', backref='post', lazy=True, cascade='all, delete-orphan')
    likes = db.relationship('HockPostLike', backref='post', lazy=True, cascade='all, delete-orphan')

    __table_args__ = (
        db.Index('ix_hock_post_approved_pub_date', 'approved_to_publish', 'pub_date'),
    )

    def __init__(self, title, body, user_id, image=None,
                 guest_email=None, guest_phone=None, guest_manage_token=None):
        self.title = title
        self.body = body
        self.user_id = user_id
        self.image = image
        self.guest_email = guest_email
        self.guest_phone = guest_phone
        self.guest_manage_token = guest_manage_token

    def __repr__(self):
        return f'HockPost({self.id}) {self.title}'
