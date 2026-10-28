"""Stage 3 of gut_next_level_agent.md ("Alerts, the reason to come back").

No Vercel-native cron wiring here, on purpose -- see
backend/analytics/routes/visitor.py's own comment on why this codebase
avoids shipping a Vercel cron schema nobody can verify against a real
deploy without a live test. Follows the exact pattern already proven in
backend/business/routes/social.py instead: a secret-protected endpoint for
a real external scheduler (point cron-job.org or similar at
POST /alerts/cron/send-digests with an X-Cron-Secret header, reusing the
same CRON_SECRET env var social.py's own cron already needs), PLUS an
opportunistic low-probability sweep hooked into a high-traffic route
(see maybe_send_digests(), called from tachlis_post.py's list_posts) so
the feature still works with zero extra setup, just looser timing.
"""
import os
import random
import re
from datetime import datetime
from urllib.parse import parse_qsl

from flask import Blueprint, jsonify, request
from werkzeug.datastructures import MultiDict

from config import db
from security import token_required, token_optional, cron_secret_required
from backend.alerts.modals.alert import Alert, SEARCH_TYPES
from backend.alerts.schemas.alert import alert_schema, alerts_schema
from backend.alerts import emails

alerts_api = Blueprint('alerts_api', __name__, url_prefix='/alerts')

LABEL_MAX = 300
FILTERS_MAX = 2000
_EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')

# Where the confirm/unsubscribe links in an alert email point -- one shared
# pair of pages on the main site regardless of which site's search created
# the alert (Estates and Money both feed the same Alert table), so there's
# only ever one confirm/unsubscribe page to build and maintain.
MAIN_SITE_URL = os.environ.get('MAIN_SITE_URL', 'https://www.gutshtick.com')

# How often a request to a hot route also checks for due digests, when no
# external scheduler is configured -- deliberately low; over-firing just
# wastes a query (each alert's own last_notified_at watermark makes a
# duplicate run a no-op), so this only needs to be "a few times a day"
# across real traffic, not precise.
OPPORTUNISTIC_CHANCE = 1 / 3000

MAX_ITEMS_PER_ALERT = 20


def _site_url(search_type):
    return {'estates': 'https://www.gutestates.com', 'tachlis': 'https://www.gutmoney.com'}.get(search_type, MAIN_SITE_URL)


def _args_from_filters(filters_str):
    return MultiDict(parse_qsl(filters_str or ''))


def _validate_filters(search_type, filters_str):
    """Dry-runs the saved filters through the exact same query-building code
    the live search uses, so a bad/malformed alert can never be created in
    the first place -- see estates.py's/tachlis_post.py's shared
    _apply_*_filters(). Raises ValueError with a user-facing message."""
    args = _args_from_filters(filters_str)
    if search_type == 'estates':
        from backend.estates.routes.estates import _apply_listing_filters, FilterError
        from backend.estates.modals.estates import EstatesListing
        try:
            _apply_listing_filters(EstatesListing.query, args)
        except FilterError as e:
            raise ValueError(str(e))
    else:
        from backend.tachlis.routes.tachlis_post import _apply_post_filters, FilterError
        from backend.tachlis.modals.tachlis_post import TachlisPost
        try:
            _apply_post_filters(TachlisPost.query, args)
        except FilterError as e:
            raise ValueError(str(e))


def link_alerts_to_user(user):
    """Backfills user_id on any alert(s) made with this email before the
    person had (or was logged into) an account -- Stage 3's "alerts made
    before signing up attach to the account with the same email." Called
    from application.py's login() and user.py's add_user(); safe to call on
    every login, not just the first -- a no-op once already linked."""
    Alert.query.filter_by(email=user.email, user_id=None).update({'user_id': user.public_id})
    db.session.commit()


@alerts_api.route('', methods=['POST'])
@token_optional
def create_alert(current_user):
    body = request.get_json(silent=True) or {}
    search_type = (body.get('search_type') or '').strip().lower()
    filters = (body.get('filters') or '').strip().lstrip('?')
    label = (body.get('label') or '').strip()[:LABEL_MAX] or None
    email = (current_user.email if current_user else (body.get('email') or '').strip().lower())

    if search_type not in SEARCH_TYPES:
        return jsonify({'message': f'search_type must be one of: {", ".join(SEARCH_TYPES)}'}), 400
    if not filters or len(filters) > FILTERS_MAX:
        return jsonify({'message': 'filters is required'}), 400
    if not email or not _EMAIL_RE.match(email):
        return jsonify({'message': 'A valid email is required'}), 400

    try:
        _validate_filters(search_type, filters)
    except ValueError as e:
        return jsonify({'message': str(e)}), 400

    existing = Alert.query.filter_by(email=email, search_type=search_type, filters=filters).first()
    if existing:
        if not existing.confirmed:
            # Same search, still unconfirmed -- resend rather than silently
            # no-op, in case the first email was lost/missed.
            try:
                emails.send_confirmation_email(existing, f'{MAIN_SITE_URL}/alerts/confirm/{existing.confirm_token}')
            except Exception:
                pass
            return jsonify({'message': 'You already have this alert pending -- check your email to confirm it.'}), 200
        return jsonify({'message': 'You already have an active alert for this exact search.'}), 200

    alert = Alert(
        email=email, search_type=search_type, filters=filters, label=label,
        user_id=current_user.public_id if current_user else None,
    )
    if current_user:
        # Already a verified account holder -- no separate email round trip
        # needed, same reasoning create_shtick/create_post give admin/boss
        # posters an approval bypass elsewhere in this codebase.
        alert.confirmed = True
    db.session.add(alert)
    db.session.commit()

    if not alert.confirmed:
        try:
            emails.send_confirmation_email(alert, f'{MAIN_SITE_URL}/alerts/confirm/{alert.confirm_token}')
        except Exception as exc:
            db.session.delete(alert)
            db.session.commit()
            return jsonify({'message': f'Could not send the confirmation email: {exc}'}), 502

    return jsonify(alert_schema.dump(alert)), 201


@alerts_api.route('/confirm/<token>', methods=['GET'])
def confirm_alert(token):
    alert = Alert.query.filter_by(confirm_token=token).first()
    if not alert:
        return jsonify({'message': 'This confirmation link is invalid or has already been used.'}), 404
    if not alert.confirmed:
        alert.confirmed = True
        db.session.commit()
    return jsonify({'message': 'Confirmed', 'label': alert.label, 'search_type': alert.search_type})


@alerts_api.route('/unsubscribe/<token>', methods=['GET'])
def unsubscribe_alert(token):
    alert = Alert.query.filter_by(unsubscribe_token=token).first()
    if not alert:
        return jsonify({'message': 'This alert is already gone.'}), 404
    db.session.delete(alert)
    db.session.commit()
    return jsonify({'message': 'Unsubscribed'})


@alerts_api.route('/mine', methods=['GET'])
@token_required
def my_alerts(current_user):
    rows = Alert.query.filter_by(user_id=current_user.public_id).order_by(Alert.created_at.desc()).all()
    return jsonify(alerts_schema.dump(rows))


@alerts_api.route('/<int:alert_id>', methods=['PATCH'])
@token_required
def update_alert(current_user, alert_id):
    alert = db.session.get(Alert, alert_id)
    if not alert or alert.user_id != current_user.public_id:
        return jsonify({'message': 'Alert not found'}), 404
    body = request.get_json(silent=True) or {}
    if 'paused' in body:
        alert.paused = bool(body['paused'])
    db.session.commit()
    return jsonify(alert_schema.dump(alert))


@alerts_api.route('/<int:alert_id>', methods=['DELETE'])
@token_required
def delete_alert(current_user, alert_id):
    alert = db.session.get(Alert, alert_id)
    if not alert or alert.user_id != current_user.public_id:
        return jsonify({'message': 'Alert not found'}), 404
    db.session.delete(alert)
    db.session.commit()
    return jsonify({'message': 'Deleted'})


def _matches_for_alert(alert):
    """Returns up to MAX_ITEMS_PER_ALERT new matches as plain
    {title, subtitle, url} dicts, newest first, limited to items newer than
    this alert's own watermark -- the exact same filters the live search
    uses (see _validate_filters), plus one extra "is it new" clause."""
    args = _args_from_filters(alert.filters)
    since = alert.last_notified_at or alert.created_at

    if alert.search_type == 'estates':
        from backend.estates.routes.estates import _apply_listing_filters
        from backend.estates.modals.estates import EstatesListing
        now = datetime.utcnow()
        newest_key = db.func.coalesce(EstatesListing.source_posted_at, EstatesListing.pub_date)
        query = (EstatesListing.query
                 .filter(db.or_(EstatesListing.expires_at.is_(None), EstatesListing.expires_at > now))
                 .filter(newest_key > since))
        query = _apply_listing_filters(query, args)
        rows = query.order_by(newest_key.desc()).limit(MAX_ITEMS_PER_ALERT).all()
        base = _site_url('estates')
        items = []
        for l in rows:
            place = l.neighborhood or l.city
            price = f'{"₪" if l.currency == "ILS" else "$"}{round(l.price):,}' if l.price is not None else None
            items.append({
                'title': l.title,
                'subtitle': ' · '.join(b for b in (place, price) if b),
                'url': f'{base}/listings/{l.slug}',
            })
        return items

    from backend.tachlis.routes.tachlis_post import _apply_post_filters
    from backend.tachlis.modals.tachlis_post import TachlisPost
    now = datetime.utcnow()
    newest_key = db.func.coalesce(TachlisPost.source_posted_at, TachlisPost.pub_date)
    query = (TachlisPost.query
             .filter(TachlisPost.approved_to_publish.is_(True))
             .filter(db.or_(TachlisPost.expires_at.is_(None), TachlisPost.expires_at > now))
             .filter(newest_key > since))
    query = _apply_post_filters(query, args)
    rows = query.order_by(newest_key.desc()).limit(MAX_ITEMS_PER_ALERT).all()
    base = _site_url('tachlis')
    items = []
    for p in rows:
        items.append({
            'title': p.title,
            'subtitle': ' · '.join(b for b in (p.location, p.compensation) if b),
            'url': f'{base}/tachlis/post/{p.id}',
        })
    return items


def _run_digests():
    """The actual matching/send job -- shared by the cron endpoint and the
    opportunistic sweep below. Never sends a post twice: each alert's
    last_notified_at only advances after that alert's own email went out,
    and matching always filters to strictly newer than it."""
    now = datetime.utcnow()
    alerts = Alert.query.filter_by(confirmed=True, paused=False).all()

    by_email = {}
    for alert in alerts:
        try:
            items = _matches_for_alert(alert)
        except Exception:
            continue  # one bad/stale saved search shouldn't break the whole run
        if not items:
            continue
        by_email.setdefault(alert.email, []).append((alert, items))

    sent_emails = 0
    sent_alerts = 0
    for email, alert_items in by_email.items():
        sections = [{
            'alert': alert,
            'label': alert.label or ('Homes search' if alert.search_type == 'estates' else 'Job search'),
            'site_name': emails.SITE_NAMES.get(alert.search_type, 'GUT'),
            'items': items,
            'unsubscribe_url': f'{MAIN_SITE_URL}/alerts/unsubscribe/{alert.unsubscribe_token}',
        } for alert, items in alert_items]
        try:
            emails.send_digest_email(email, sections)
        except Exception:
            continue  # leave those alerts' watermarks alone -- picked up again next run
        for alert, _items in alert_items:
            alert.last_notified_at = now
            sent_alerts += 1
        sent_emails += 1

    db.session.commit()
    return {'alerts_checked': len(alerts), 'emails_sent': sent_emails, 'alerts_notified': sent_alerts}


@alerts_api.route('/cron/send-digests', methods=['POST'])
@cron_secret_required
def send_digests_cron():
    return jsonify(_run_digests())


def maybe_send_digests():
    """Opportunistic fallback -- see module docstring. Call from a
    high-traffic route; never raises, never blocks the request that
    triggered it."""
    if random.random() >= OPPORTUNISTIC_CHANCE:
        return
    try:
        _run_digests()
    except Exception:
        pass
