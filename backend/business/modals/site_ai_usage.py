from datetime import date

from config import db

# Separate from backend/askgut/modals/usage.py's AskGutUsage despite
# solving the identical (identity, date) rate-limit problem -- same
# precedent as backend/guest/modals/guest_throttle.py's own docstring for
# why it didn't reuse AskGutUsage either: a distinct feature with its own
# budget, not a shared counter two different features would silently
# exhaust for each other. A full page-generation call is also heavier
# (more output tokens) than one AskGut chat turn, so it warrants a lower
# daily cap, not the same number reused for a different meaning.
DAILY_GENERATE_CAP = 15


class SiteAiUsage(db.Model):
    """Per-caller, per-day counter for the site builder's AI assistant
    (POST /business/site-ai/generate). identity is a logged-in user's
    public_id or an anonymous caller's IP -- this endpoint is public (the
    free, no-login builder at /build gets AI help too), so it needs the
    same identity-or-IP fallback AskGutUsage/GuestSubmissionThrottle
    already use for the same reason."""
    __tablename__ = 'site_ai_usage'

    id = db.Column(db.Integer, primary_key=True)
    identity = db.Column(db.String(120), nullable=False, index=True)
    usage_date = db.Column(db.Date, nullable=False, default=date.today, index=True)
    generate_count = db.Column(db.Integer, nullable=False, default=0, server_default='0')

    __table_args__ = (
        db.UniqueConstraint('identity', 'usage_date', name='uq_site_ai_usage_identity_date'),
    )

    def __repr__(self):
        return f'SiteAiUsage({self.identity} {self.usage_date} x{self.generate_count})'


def check_and_record_generate(identity):
    """Returns True if this call is allowed (and records it), False if
    today's cap is already hit for this identity. Call once, right before
    actually calling OpenAI -- mirrors guest_throttle.py's own
    check_and_record_guest_submission."""
    today = date.today()
    row = SiteAiUsage.query.filter_by(identity=identity, usage_date=today).first()
    if row is None:
        row = SiteAiUsage(identity=identity, usage_date=today, generate_count=0)
        db.session.add(row)
    if row.generate_count >= DAILY_GENERATE_CAP:
        return False
    row.generate_count += 1
    return True
