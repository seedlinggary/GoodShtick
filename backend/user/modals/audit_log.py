from config import db
from datetime import datetime


class AuditLog(db.Model):
    """Append-only record of who did what, when, for SuperAdmin actions that
    have no other undo path -- role changes, ad status changes/deletion,
    category deletion, unapproving a post. Nothing in this app updates or
    deletes a row here; it's write-once by design (see log_admin_action)."""
    __tablename__ = 'audit_log'

    id = db.Column(db.Integer, primary_key=True)
    actor_public_id = db.Column(db.String(50), db.ForeignKey('user.public_id'), nullable=True, index=True)

    # e.g. 'role_change', 'ad_status_change', 'ad_delete', 'category_delete', 'unapprove_post'
    action = db.Column(db.String(50), nullable=False, index=True)

    # What the action was done to -- kept as simple strings rather than real
    # FKs since the target spans several unrelated tables (user/ad/category/
    # shtick) and the row the action targeted may itself later be deleted
    # (e.g. a draft ad); target_id is stringified so it can hold either a
    # numeric id (ad/category/shtick) or a user's public_id.
    target_type = db.Column(db.String(50), nullable=True)
    target_id = db.Column(db.String(50), nullable=True)

    details = db.Column(db.Text, nullable=True)  # free-form, e.g. "role: admin -> super_admin"
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    actor = db.relationship('User', foreign_keys=[actor_public_id],
                             backref=db.backref('admin_audit_logs', lazy=True))

    def __repr__(self):
        return f'<AuditLog {self.id} {self.action} by {self.actor_public_id}>'


def log_admin_action(actor, action, target_type, target_id, details=None):
    """Stages one audit-log row on the current session -- does NOT call
    db.session.commit() itself. Call this right before the route's own
    commit() so the log entry lands in the same transaction as the action
    it's describing (both succeed or both roll back together)."""
    db.session.add(AuditLog(
        actor_public_id=actor.public_id if actor else None,
        action=action,
        target_type=target_type,
        target_id=str(target_id) if target_id is not None else None,
        details=details,
    ))
