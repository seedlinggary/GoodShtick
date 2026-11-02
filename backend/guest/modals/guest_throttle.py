from datetime import date

from config import db

# One combined cap across EVERY content type a guest can post to (jobs,
# listings, businesses, comments, ...), not ten separate per-type caps a
# single IP could otherwise exhaust in parallel.
GUEST_SUBMISSION_DAILY_CAP = 8


class GuestSubmissionThrottle(db.Model):
    """Per-IP, per-day counter capping anonymous guest-post submissions
    across the whole site -- the first unauthenticated-write surface in
    this codebase, so there's no existing abuse defense to lean on.

    Deliberately a DB-backed counter, not Flask-Limiter's default
    in-memory store: config.py runs this app serverless with pool_size=1
    and an explicit cold-start-per-invocation design, so an in-memory
    limiter would silently do nothing in production -- each invocation's
    memory starts empty. Same (identity, date) bare-counter shape as
    backend/askgut/modals/usage.py's AskGutUsage, which solves the
    identical problem for a different feature -- kept as its own table
    since this is a distinct concern, not reused."""
    __tablename__ = 'guest_submission_throttle'

    id = db.Column(db.Integer, primary_key=True)
    identity = db.Column(db.String(64), nullable=False, index=True)  # 'ip:<remote_addr>'
    usage_date = db.Column(db.Date, nullable=False, default=date.today, index=True)
    count = db.Column(db.Integer, nullable=False, default=0, server_default='0')

    __table_args__ = (
        db.UniqueConstraint('identity', 'usage_date', name='uq_guest_submission_throttle_identity_date'),
    )

    def __repr__(self):
        return f'GuestSubmissionThrottle({self.identity} {self.usage_date} x{self.count})'


def check_and_record_guest_submission(request):
    """Returns True if this submission is allowed (and records it), False
    if today's combined cap is already hit for this IP. Call this ONCE,
    right before actually inserting a new guest post/listing/comment row --
    same "check, then commit together" shape as AskGutUsage's own
    _check_and_increment_usage. request.remote_addr is used as-is (no
    X-Forwarded-For handling) -- same simple convention the rest of this
    codebase's few IP checks already use; a soft abuse cap, not meant to be
    unspoofable."""
    identity = f'ip:{request.remote_addr or "unknown"}'
    today = date.today()
    row = GuestSubmissionThrottle.query.filter_by(identity=identity, usage_date=today).first()
    if row is None:
        row = GuestSubmissionThrottle(identity=identity, usage_date=today, count=0)
        db.session.add(row)
    if row.count >= GUEST_SUBMISSION_DAILY_CAP:
        return False
    row.count += 1
    return True
