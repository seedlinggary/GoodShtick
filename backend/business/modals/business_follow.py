import secrets

from config import db
from datetime import datetime


class BusinessFollow(db.Model):
    """A customer following a business -- what a follower count/broadcast
    list is built from, and the gate for the 'new deal' notify() a business
    fires when it broadcasts an update (see routes/business_follow.py). Also
    now the gate for the automatic 'new deal' EMAIL sent from
    routes/business_post.py's create_post() -- unfollowing (including via
    unsubscribe_token below) is the one-click opt-out for that, same
    reasoning as Alert.unsubscribe_token: there's no separate "follow but
    mute emails" state, since following is itself what opts someone in."""
    __tablename__ = 'business_follow'

    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(db.Integer, db.ForeignKey('business.id'), nullable=False, index=True)
    user_id = db.Column(db.String(50), db.ForeignKey('user.public_id'), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    # Powers the one-click "unfollow" link in a deal-alert email with no
    # login required -- same pattern as Alert.unsubscribe_token/
    # User.weekly_digest_token. Nullable because it's new: existing rows
    # from before this column existed get one lazily backfilled the first
    # time they'd actually need it (see business_post.py's
    # _notify_followers_of_new_deal), same lazy-backfill convention as
    # EstatesListing.still_available_token.
    unsubscribe_token = db.Column(db.String(64), nullable=True, unique=True, index=True)

    __table_args__ = (
        db.UniqueConstraint('business_id', 'user_id', name='uq_follow_business_user'),
    )

    business = db.relationship('Business', backref=db.backref('followers', lazy=True, cascade='all, delete-orphan'))
    user = db.relationship('User', backref=db.backref('followed_businesses', lazy=True))

    def __init__(self, business_id, user_id):
        self.business_id = business_id
        self.user_id = user_id
        self.unsubscribe_token = secrets.token_urlsafe(32)

    def __repr__(self):
        return f'BusinessFollow(business={self.business_id} user={self.user_id})'
