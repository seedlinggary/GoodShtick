import random
from config import db
from datetime import datetime, timedelta

# Lazy-cleanup approach, same reasoning/pattern as analytics/routes/visitor.py's
# _maybe_cleanup: no cron wiring in this repo, so a small random chance of a
# cleanup sweep on every write converges on the same steady-state table size a
# cron job would give you, just with fuzzier timing.
RETENTION_DAYS = 180
CLEANUP_CHANCE = 0.02


class LoginLog(db.Model):
    """Append-only record of login attempts (password and SSO-exchange),
    success and failure alike -- lets a SuperAdmin see who's logging in from
    where, and spot repeated failed attempts. Nothing in this app updates or
    deletes a row here except the probabilistic retention purge below; it's
    write-once by design (see log_login)."""
    __tablename__ = 'login_log'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(50), db.ForeignKey('user.public_id'), nullable=True, index=True)
    email_attempted = db.Column(db.String(255), nullable=True)
    site = db.Column(db.String(20), nullable=True, index=True)
    method = db.Column(db.String(20), nullable=False)  # 'password' | 'sso_exchange'
    success = db.Column(db.Boolean, nullable=False)
    ip_address = db.Column(db.String(64), nullable=True)
    user_agent = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    user = db.relationship('User', foreign_keys=[user_id])

    def __repr__(self):
        return f'<LoginLog {self.id} {self.method} success={self.success}>'


def _maybe_cleanup_login_log():
    """Opportunistically purge rows past the retention window. Never allowed
    to break the login flow that triggered it."""
    if random.random() >= CLEANUP_CHANCE:
        return
    try:
        cutoff = datetime.utcnow() - timedelta(days=RETENTION_DAYS)
        LoginLog.query.filter(LoginLog.created_at < cutoff).delete(synchronize_session=False)
        db.session.commit()
    except Exception:
        db.session.rollback()


def log_login(user, email_attempted, site, method, success, request):
    """Stages one login-log row on the current session -- does NOT call
    db.session.commit() itself. Call this right before the route's own
    commit() so the log entry lands in the same transaction as the login
    attempt it's describing."""
    db.session.add(LoginLog(
        user_id=user.public_id if user else None,
        email_attempted=email_attempted,
        site=site,
        method=method,
        success=success,
        ip_address=request.remote_addr,
        user_agent=(request.headers.get('User-Agent') or '')[:255],
    ))
    _maybe_cleanup_login_log()
