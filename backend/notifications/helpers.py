from config import db
from backend.notifications.modals.notification import Notification


def notify(user_id, message, type='info', actor_id=None, link=None):
    """Create a notification. Never raises — a broken notification should
    never break the action that triggered it (liking a post, saving a score).
    Does not commit; caller's existing db.session.commit() picks it up too."""
    if not user_id or (actor_id and actor_id == user_id):
        return  # don't notify yourself
    try:
        db.session.add(Notification(
            user_id=user_id,
            actor_id=actor_id,
            type=type,
            message=message,
            link=link,
        ))
    except Exception:
        pass
