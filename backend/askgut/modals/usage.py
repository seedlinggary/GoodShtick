from datetime import date

from config import db


class AskGutUsage(db.Model):
    """Per-caller, per-day message counter -- the cost/abuse guardrail this
    feature needs that nothing else calling the OpenAI API in this codebase
    has today (ai_content.py/estates.py/tachlis_post.py's AI calls are all
    admin-triggered batch jobs, not a public-facing endpoint someone could
    hammer). One row per (identity, date); `identity` is a logged-in user's
    public_id or an anonymous caller's IP address (see routes/chat.py's
    _caller_identity) -- deliberately NOT a real FK, since it spans two
    different kinds of identity the same way AuditLog.target_id does for a
    similar reason. `message_count` is incremented in place; there's no
    per-message history table since there's nothing to audit/dispute here,
    unlike points or redemptions -- just a running total we need to reset
    daily, which a (identity, date) unique row gives us for free."""
    __tablename__ = 'askgut_usage'

    id = db.Column(db.Integer, primary_key=True)
    identity = db.Column(db.String(120), nullable=False, index=True)
    usage_date = db.Column(db.Date, nullable=False, default=date.today, index=True)
    message_count = db.Column(db.Integer, nullable=False, default=0, server_default='0')
    prompt_tokens = db.Column(db.Integer, nullable=False, default=0, server_default='0')
    completion_tokens = db.Column(db.Integer, nullable=False, default=0, server_default='0')

    __table_args__ = (
        db.UniqueConstraint('identity', 'usage_date', name='uq_askgut_usage_identity_date'),
    )

    def __repr__(self):
        return f'AskGutUsage({self.identity} {self.usage_date} x{self.message_count})'
