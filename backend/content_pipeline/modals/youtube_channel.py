from config import db
from datetime import datetime


class YoutubeChannel(db.Model):
    """A channel tracked for new uploads. `last_video_id` is a fast-path
    cache of the most recent video already posted; `YoutubeVideoPost` below
    is the authoritative per-video dedup record (handles the case where
    several videos were uploaded since the last check)."""
    __tablename__ = 'youtube_channel'

    id = db.Column(db.Integer, primary_key=True)
    channel_id = db.Column(db.String(64), nullable=False, unique=True)  # YouTube's channel ID, e.g. "UC..."
    display_name = db.Column(db.String(150))
    added_by = db.Column(db.String(50), db.ForeignKey('user.public_id'), nullable=True)
    added_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_video_id = db.Column(db.String(32), nullable=True)
    last_checked_at = db.Column(db.DateTime, nullable=True)
    active = db.Column(db.Boolean, default=True, nullable=False)

    adder = db.relationship('User', foreign_keys=[added_by], backref=db.backref('youtube_channels_added', lazy=True))

    def __init__(self, channel_id, display_name=None, added_by=None):
        self.channel_id = channel_id
        self.display_name = display_name
        self.added_by = added_by

    def __repr__(self):
        return f'YoutubeChannel({self.channel_id}) {self.display_name}'


class YoutubeVideoPost(db.Model):
    """One video already turned into a (pending) Shtick — the authoritative
    dedup record so a channel check never reposts the same video twice."""
    __tablename__ = 'youtube_video_post'

    id = db.Column(db.Integer, primary_key=True)
    channel_id = db.Column(db.String(64), db.ForeignKey('youtube_channel.channel_id'), nullable=False)
    video_id = db.Column(db.String(32), nullable=False, unique=True)
    shtick_id = db.Column(db.Integer, db.ForeignKey('shtick.id'), nullable=True)
    posted_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __init__(self, channel_id, video_id, shtick_id=None):
        self.channel_id = channel_id
        self.video_id = video_id
        self.shtick_id = shtick_id
