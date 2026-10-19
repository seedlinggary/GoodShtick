from config import db
from datetime import datetime

# Enforced at the Python/route level, matching this project's convention of
# avoiding DB-level enums (see business.py).
TEFILAH_TYPES = ('shacharit', 'mincha', 'maariv', 'other')

# A minyan's time is either a fixed clock time, or relative to a daily
# halachic anchor that itself shifts with the sun -- "10 min before shkiya"
# means something different every day of the year, so storing only a fixed
# time would silently go stale. ANCHORS mirrors what shuls themselves post.
RELATIVE_ANCHORS = ('netz', 'shkiya', 'chatzos', 'alos', 'tzeis')


class Minyan(db.Model):
    """A shul's minyan time. Deliberately NEVER created without a source --
    see _validate_minyan in routes/minyan.py, which refuses to save one
    without at least a source_name (a URL is preferred but not every shul
    publishes one online; "called the shul office 3/2026" is still a real
    source). Every public display of this data carries a disclaimer to
    confirm with the shul directly -- times shift with the season/the sun
    and shuls change them without always updating whatever we sourced this
    from."""
    __tablename__ = 'minyan'

    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(db.Integer, db.ForeignKey('business.id'), nullable=False, index=True)

    tefilah = db.Column(db.String(20), nullable=False)
    label = db.Column(db.String(150), nullable=True)  # e.g. "Daf Yomi Minyan", "Early Minyan"
    days = db.Column(db.String(100), nullable=True)   # free text: "Sun-Fri", "Shabbat", "Rosh Chodesh"
    season = db.Column(db.String(60), nullable=True)  # free text: "Summer", "Winter", None = year-round

    # Exactly one of (fixed_time) or (relative_anchor + relative_offset_minutes)
    # is expected to be set -- enforced at the route level, not the DB, same
    # reasoning as the category enums elsewhere in this codebase.
    fixed_time = db.Column(db.Time, nullable=True)
    relative_anchor = db.Column(db.String(20), nullable=True)
    relative_offset_minutes = db.Column(db.Integer, nullable=True)  # negative = before the anchor

    notes = db.Column(db.String(300), nullable=True)

    source_name = db.Column(db.String(200), nullable=False)
    source_url = db.Column(db.String(500), nullable=True)

    created_by = db.Column(db.String(50), db.ForeignKey('user.public_id'), nullable=True)
    pub_date = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    business = db.relationship('Business', backref=db.backref('minyanim', lazy=True, cascade='all, delete-orphan'))
    creator = db.relationship('User', foreign_keys=[created_by])

    def __init__(self, business_id, tefilah, source_name, label=None, days=None, season=None,
                 fixed_time=None, relative_anchor=None, relative_offset_minutes=None,
                 notes=None, source_url=None, created_by=None):
        self.business_id = business_id
        self.tefilah = tefilah
        self.source_name = source_name
        self.label = label
        self.days = days
        self.season = season
        self.fixed_time = fixed_time
        self.relative_anchor = relative_anchor
        self.relative_offset_minutes = relative_offset_minutes
        self.notes = notes
        self.source_url = source_url
        self.created_by = created_by

    def __repr__(self):
        return f'Minyan({self.id}) business={self.business_id} {self.tefilah}'
