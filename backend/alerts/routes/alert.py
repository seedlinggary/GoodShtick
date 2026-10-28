"""Stage 3 of gut_next_level_agent.md ("Alerts, the reason to come back").

No Vercel-native cron wiring here, on purpose -- Vercel Cron Jobs are
defined in vercel.json and can only be changed by editing that file and
redeploying (no live/dashboard-only reschedule), and on the Hobby plan are
capped at one *loosely timed* invocation per day (can land anywhere in the
target hour), which can't honor an exact, admin-editable send time. See
also backend/analytics/routes/visitor.py's own comment on why this
codebase avoids shipping a Vercel cron schema nobody can verify against a
real deploy without a live test.

Instead: a secret-protected endpoint for a real external scheduler (point
cron-job.org or similar at POST /alerts/cron/send-digests every few
minutes with an X-Cron-Secret header, reusing the same CRON_SECRET env var
social.py's own cron already needs), PLUS an opportunistic low-probability
sweep hooked into a high-traffic route (see maybe_send_digests(), called
from tachlis_post.py's list_posts) so the feature still works with zero
extra setup, just looser timing. Both paths are just ordinary calls into
this same Flask app, so neither depends on any Vercel-specific feature --
nothing here can "break on Vercel".

Neither path sends immediately, though -- both are gated by
_maybe_run_scheduled_digest() against AlertDigestSchedule, a one-row table
holding an Israel-local send_hour/send_minute a super admin can edit any
time via PATCH /alerts/admin/schedule (SuperAdminDashboard), with zero
redeploy. The external scheduler's own interval never needs to change when
that time does -- it just needs to ping often enough (e.g. every 15 min)
to catch the window soon after it opens; last_run_date keeps repeated pings
across the same day from sending twice.
"""
import os
import random
import re
import secrets
from datetime import datetime, time, timedelta
from urllib.parse import parse_qsl
from zoneinfo import ZoneInfo

from flask import Blueprint, jsonify, request
from werkzeug.datastructures import MultiDict

from config import db
from security import token_required, token_optional, cron_secret_required, super_admin_required
from backend.alerts.modals.alert import Alert, AlertDigestSchedule, SEARCH_TYPES, CADENCES, CHANNELS
from backend.alerts.schemas.alert import alert_schema, alerts_schema
from backend.alerts import emails

# The digest's "send at" time is interpreted in this zone regardless of
# where the cron ping or the opportunistic sweep's request actually
# originates -- see AlertDigestSchedule / _maybe_run_scheduled_digest().
ISRAEL_TZ = ZoneInfo('Asia/Jerusalem')

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
    if 'cadence' in body:
        if body['cadence'] not in CADENCES:
            return jsonify({'message': f'cadence must be one of: {", ".join(CADENCES)}'}), 400
        alert.cadence = body['cadence']
    if 'channel' in body:
        if body['channel'] not in CHANNELS:
            return jsonify({'message': f'channel must be one of: {", ".join(CHANNELS)}'}), 400
        alert.channel = body['channel']
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


def _get_schedule():
    """Get-or-create the single schedule row (id=1). Created lazily here
    rather than via a data migration so a fresh/test DB never needs seeding."""
    schedule = db.session.get(AlertDigestSchedule, 1)
    if not schedule:
        schedule = AlertDigestSchedule(id=1)
        db.session.add(schedule)
        db.session.commit()
    return schedule


def _nearby_items_for_user(user, since):
    """Stage 4's "Your week" digest, "new near you" section -- up to 5
    Estates listings + 5 Tachlis posts from the last week, filtered to the
    member's own profile_area when they've set one (loose substring match,
    same as the live search filters use), otherwise just the most recent
    from each site so even a member with no profile set gets something real."""
    from backend.estates.modals.estates import EstatesListing
    from backend.tachlis.modals.tachlis_post import TachlisPost

    now = datetime.utcnow()
    area = (user.profile_area or '').strip()

    listing_q = (EstatesListing.query
                 .filter(db.or_(EstatesListing.expires_at.is_(None), EstatesListing.expires_at > now))
                 .filter(EstatesListing.pub_date > since))
    if area:
        like = f'%{area}%'
        listing_q = listing_q.filter(db.or_(EstatesListing.city.ilike(like), EstatesListing.neighborhood.ilike(like)))
    listings = listing_q.order_by(EstatesListing.pub_date.desc()).limit(5).all()

    post_q = (TachlisPost.query
              .filter(TachlisPost.approved_to_publish.is_(True))
              .filter(db.or_(TachlisPost.expires_at.is_(None), TachlisPost.expires_at > now))
              .filter(TachlisPost.pub_date > since))
    if area:
        post_q = post_q.filter(TachlisPost.location.ilike(f'%{area}%'))
    posts = post_q.order_by(TachlisPost.pub_date.desc()).limit(5).all()

    items = []
    for l in listings:
        place = l.neighborhood or l.city
        symbol = '₪' if l.currency == 'ILS' else '$'
        price = f'{symbol}{round(l.price):,}' if l.price is not None else None
        items.append({
            'title': l.title, 'subtitle': ' · '.join(b for b in (place, price) if b),
            'url': f'{_site_url("estates")}/listings/{l.slug}',
        })
    for p in posts:
        items.append({
            'title': p.title, 'subtitle': ' · '.join(b for b in (p.location, p.compensation) if b),
            'url': f'{_site_url("tachlis")}/tachlis/post/{p.id}',
        })
    return items


def _price_move_items_for_user(user, since):
    """Stage 4's "Your week" digest, "price moves" section -- reuses the
    Notification rows the price-drop/back-on-market sweep already created
    (see backend/estates/routes/estates.py's check_saved_listings_for_changes),
    rather than tracking a second, separate "what changed" signal."""
    from backend.notifications.modals.notification import Notification
    rows = (Notification.query
            .filter_by(user_id=user.public_id)
            .filter(Notification.type.in_(['price_drop', 'back_on_market']))
            .filter(Notification.pub_date > since)
            .order_by(Notification.pub_date.desc())
            .limit(10).all())
    return [{'message': n.message, 'url': n.link or MAIN_SITE_URL} for n in rows]


def _run_weekly_digests():
    """Stage 4's "Your week" digest -- one email per opted-in member,
    skipped entirely if there's nothing real to say (no "nothing new this
    week" emails). Mirrors _run_digests()'s shape: never raises per-user,
    one bad profile shouldn't break the whole run."""
    from backend.user.modals.user import User
    now = datetime.utcnow()
    since = now - timedelta(days=7)
    users = User.query.filter_by(weekly_digest_enabled=True).all()

    sent = 0
    for user in users:
        try:
            nearby = _nearby_items_for_user(user, since)
            moves = _price_move_items_for_user(user, since)
        except Exception:
            continue
        if not nearby and not moves:
            continue
        if not user.weekly_digest_token:
            user.weekly_digest_token = secrets.token_urlsafe(32)
            db.session.commit()
        try:
            emails.send_weekly_digest_email(
                user.email, nearby, moves,
                f'{MAIN_SITE_URL}/user/weekly-digest/unsubscribe/{user.weekly_digest_token}',
            )
        except Exception:
            continue
        user.last_weekly_digest_at = now
        sent += 1

    db.session.commit()
    return {'users_checked': len(users), 'emails_sent': sent}


def _run_digests(cadence=None):
    """The actual matching/send job -- shared by the cron endpoint and the
    opportunistic sweep below. Never sends a post twice: each alert's
    last_notified_at only advances after that alert's own email went out,
    and matching always filters to strictly newer than it. `cadence`
    ('daily'/'instant') scopes the run to just that cadence; omit it to run
    every confirmed, unpaused alert regardless (used by the admin
    force-run)."""
    now = datetime.utcnow()
    query = Alert.query.filter_by(confirmed=True, paused=False)
    if cadence is not None:
        query = query.filter_by(cadence=cadence)
    alerts = query.all()

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


def _maybe_run_scheduled_digest(include_still_available=False):
    """The shared gate behind both the cron endpoint and the opportunistic
    sweep. 'instant'-cadence alerts are checked on EVERY call, unconditionally
    -- that's what "within one run" means for them (see Stage 4's full alert
    rules); their own last_notified_at watermark makes a repeat call a no-op
    once nothing new has shown up. 'daily'-cadence alerts only actually send
    once a day, at/after the super-admin-set local time in Israel. Returns a
    dict either way, never raises -- a bad schedule row should never break a
    request it's piggybacking on.

    `include_still_available` defaults to False and is only ever passed
    True by send_digests_cron() -- Stage 5's "Still available?" check never
    runs from the random, zero-setup opportunistic sweep (maybe_send_digests),
    only from a deliberate cron ping, and even then only once a super admin
    has also turned it on (AlertDigestSchedule.still_available_check_enabled).
    Two separate locks for something that messages real posters and hides
    their content on silence."""
    instant_result = _run_digests(cadence='instant')

    try:
        from backend.estates.routes.estates import check_saved_listings_for_changes
        saved_items_result = check_saved_listings_for_changes()
    except Exception:
        saved_items_result = {'error': 'failed'}

    schedule = _get_schedule()
    now_local = datetime.now(ISRAEL_TZ)
    if schedule.last_run_date == now_local.date():
        daily_result = {'skipped': 'already sent today'}
    elif now_local.time() < time(schedule.send_hour, schedule.send_minute):
        daily_result = {'skipped': 'not due yet', 'send_at': f'{schedule.send_hour:02d}:{schedule.send_minute:02d} Israel time'}
    else:
        daily_result = _run_digests(cadence='daily')
        schedule.last_run_date = now_local.date()
        db.session.commit()

    # Python's weekday(): Monday=0..Sunday=6, matching weekly_weekday's own convention.
    if schedule.last_weekly_run_date == now_local.date():
        weekly_result = {'skipped': 'already sent this week'}
    elif now_local.weekday() != schedule.weekly_weekday:
        weekly_result = {'skipped': 'not the weekly send day'}
    elif now_local.time() < time(schedule.send_hour, schedule.send_minute):
        weekly_result = {'skipped': 'not due yet today'}
    else:
        weekly_result = _run_weekly_digests()
        schedule.last_weekly_run_date = now_local.date()
        db.session.commit()

    still_available_result = {'skipped': 'disabled'}
    if include_still_available and schedule.still_available_check_enabled:
        try:
            from backend.estates.routes.estates import check_still_available as check_estates_still_available
            from backend.tachlis.routes.tachlis_post import check_still_available as check_tachlis_still_available
            still_available_result = {
                'estates': check_estates_still_available(),
                'tachlis': check_tachlis_still_available(),
            }
        except Exception:
            still_available_result = {'error': 'failed'}

    return {
        'instant': instant_result, 'daily': daily_result, 'weekly': weekly_result,
        'saved_items': saved_items_result, 'still_available': still_available_result,
    }


@alerts_api.route('/cron/send-digests', methods=['POST'])
@cron_secret_required
def send_digests_cron():
    return jsonify(_maybe_run_scheduled_digest(include_still_available=True))


def maybe_send_digests():
    """Opportunistic fallback -- see module docstring. Call from a
    high-traffic route; never raises, never blocks the request that
    triggered it. Still gated by the same daily schedule as the cron
    endpoint -- this is just an extra chance to notice "it's due," not a
    second, independent send path."""
    if random.random() >= OPPORTUNISTIC_CHANCE:
        return
    try:
        _maybe_run_scheduled_digest()
    except Exception:
        pass


@alerts_api.route('/admin/schedule', methods=['GET'])
@super_admin_required
def get_digest_schedule(_current_user):
    s = _get_schedule()
    return jsonify({
        'send_hour': s.send_hour,
        'send_minute': s.send_minute,
        'weekly_weekday': s.weekly_weekday,
        'timezone': 'Asia/Jerusalem',
        'last_run_date': s.last_run_date.isoformat() if s.last_run_date else None,
        'last_weekly_run_date': s.last_weekly_run_date.isoformat() if s.last_weekly_run_date else None,
        'still_available_check_enabled': s.still_available_check_enabled,
    })


@alerts_api.route('/admin/schedule', methods=['PATCH'])
@super_admin_required
def update_digest_schedule(_current_user):
    body = request.get_json(silent=True) or {}
    hour = body.get('send_hour')
    minute = body.get('send_minute', 0)
    if not isinstance(hour, int) or not (0 <= hour <= 23):
        return jsonify({'message': 'send_hour must be an integer 0-23'}), 400
    if not isinstance(minute, int) or not (0 <= minute <= 59):
        return jsonify({'message': 'send_minute must be an integer 0-59'}), 400
    s = _get_schedule()
    s.send_hour = hour
    s.send_minute = minute
    if 'weekly_weekday' in body:
        weekday = body['weekly_weekday']
        if not isinstance(weekday, int) or not (0 <= weekday <= 6):
            return jsonify({'message': 'weekly_weekday must be an integer 0 (Monday) - 6 (Sunday)'}), 400
        s.weekly_weekday = weekday
    if 'still_available_check_enabled' in body:
        s.still_available_check_enabled = bool(body['still_available_check_enabled'])
    s.updated_at = datetime.utcnow()
    db.session.commit()
    return jsonify({
        'send_hour': s.send_hour, 'send_minute': s.send_minute,
        'weekly_weekday': s.weekly_weekday, 'timezone': 'Asia/Jerusalem',
        'still_available_check_enabled': s.still_available_check_enabled,
    })


@alerts_api.route('/admin/run-now', methods=['POST'])
@super_admin_required
def run_digests_now(_current_user):
    """Manual override for testing/verification -- bypasses the schedule
    gate entirely (but still updates last_run_date, so the regularly
    scheduled run today becomes a no-op instead of double-sending). Does
    NOT force the weekly digest too -- that one's rare/heavier (one email
    per member) and has its own admin/run-weekly-now below for when that's
    specifically what's being tested."""
    result = _run_digests()
    s = _get_schedule()
    s.last_run_date = datetime.now(ISRAEL_TZ).date()
    db.session.commit()
    return jsonify(result)


@alerts_api.route('/admin/run-weekly-now', methods=['POST'])
@super_admin_required
def run_weekly_digests_now(_current_user):
    """Manual override for Stage 4's "Your week" digest -- sends real email
    to every opted-in member who has something new, right now."""
    result = _run_weekly_digests()
    s = _get_schedule()
    s.last_weekly_run_date = datetime.now(ISRAEL_TZ).date()
    db.session.commit()
    return jsonify(result)


@alerts_api.route('/admin/run-still-available-now', methods=['POST'])
@super_admin_required
def run_still_available_now(_current_user):
    """Manual test-run for Stage 5's "Still available?" check -- runs
    regardless of still_available_check_enabled (that flag only gates the
    automatic cron path), so a super admin can verify it before ever
    turning the automatic version on. Sends real email to real posters
    whose listings/posts are actually old enough."""
    from backend.estates.routes.estates import check_still_available as check_estates_still_available
    from backend.tachlis.routes.tachlis_post import check_still_available as check_tachlis_still_available
    return jsonify({
        'estates': check_estates_still_available(),
        'tachlis': check_tachlis_still_available(),
    })
