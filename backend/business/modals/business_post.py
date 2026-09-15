from config import db
from datetime import datetime

BUSINESS_POST_TYPES = ('sale', 'new_product', 'new_service', 'event', 'announcement', 'other')


class BusinessPost(db.Model):
    __tablename__ = 'business_post'

    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(db.Integer, db.ForeignKey('business.id'), nullable=False, index=True)
    user_id = db.Column(db.String(50), db.ForeignKey('user.public_id'), nullable=False, index=True)
    post_type = db.Column(db.String(20), nullable=False, index=True)
    title = db.Column(db.String(150), nullable=False)
    body = db.Column(db.Text, nullable=False)
    # Raw Supabase Storage filename -- resolved to a public URL at
    # serialization time, same pattern as Business.logo.
    image = db.Column(db.String(300), nullable=True)

    pub_date = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    expires_at = db.Column(db.DateTime, nullable=True)

    # Deal posts auto-publish (the claim step is the trust gate) -- this is
    # a reversible takedown/restore switch for admins, same pattern as
    # HockPost/HockComment's approved_to_publish.
    approved_to_publish = db.Column(db.Boolean, default=True, server_default='true', nullable=False)
    approved_by = db.Column(db.String(50), db.ForeignKey('user.public_id'), nullable=True)

    __table_args__ = (
        db.Index('ix_business_post_business_pub_date', 'business_id', 'pub_date'),
        db.Index('ix_business_post_approved_pub_date', 'approved_to_publish', 'pub_date'),
    )

    business = db.relationship('Business', backref=db.backref('posts', lazy=True, cascade='all, delete-orphan'))
    user = db.relationship('User', foreign_keys=[user_id], backref=db.backref('business_posts', lazy=True))
    approver = db.relationship('User', foreign_keys=[approved_by])

    def __init__(self, business_id, user_id, post_type, title, body, image=None, expires_at=None):
        self.business_id = business_id
        self.user_id = user_id
        self.post_type = post_type
        self.title = title
        self.body = body
        self.image = image
        self.expires_at = expires_at

    def __repr__(self):
        return f'BusinessPost({self.id}) [{self.post_type}] {self.title}'
