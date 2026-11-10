"""Google Calendar sync for bookings. Plain REST calls via `requests`,
deliberately not the google-api-python-client/google-auth-oauthlib
packages (not dependencies of this backend today, and every other Google
API this codebase calls -- see social/publishers.py, routes/social.py's
Business Profile calls -- already goes through plain `requests`, never a
provider SDK).

All functions take a CalendarAccount with its tokens still encrypted; each
one decrypts/refreshes as needed and persists a refreshed access token
before returning. Every call site in routes/business_site_public.py and
routes/booking.py wraps these in try/except -- a Calendar failure must
never block a booking, a payment, or slot listing.
"""
from datetime import datetime, timedelta

import requests

from config import db
from backend.business.social.crypto import encrypt_token, decrypt_token
from backend.business.social.publishers import get_credentials

TOKEN_URL = 'https://oauth2.googleapis.com/token'
CALENDAR_BASE = 'https://www.googleapis.com/calendar/v3'
REQUEST_TIMEOUT = 15


def _valid_access_token(account):
    """Returns a usable access token, refreshing it first if expired.
    Persists the refreshed token immediately -- callers never see or
    manage the refresh themselves."""
    access_token = decrypt_token(account.access_token_enc)
    if account.expires_at and account.expires_at > datetime.utcnow() + timedelta(seconds=30):
        return access_token

    refresh_token = decrypt_token(account.refresh_token_enc)
    if not refresh_token:
        return access_token  # nothing to refresh with -- let the caller's API call fail clearly

    client_id, client_secret = get_credentials('google')
    resp = requests.post(TOKEN_URL, data={
        'grant_type': 'refresh_token',
        'refresh_token': refresh_token,
        'client_id': client_id,
        'client_secret': client_secret,
    }, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    tokens = resp.json()

    new_access_token = tokens['access_token']
    expires_in = tokens.get('expires_in')
    account.access_token_enc = encrypt_token(new_access_token)
    account.expires_at = datetime.utcnow() + timedelta(seconds=int(expires_in)) if expires_in else None
    db.session.commit()
    return new_access_token


def _headers(account):
    return {'Authorization': f'Bearer {_valid_access_token(account)}', 'Content-Type': 'application/json'}


def get_busy_periods(account, day_start, day_end):
    """[(start, end), ...] datetimes busy on the connected calendar within
    [day_start, day_end). Never raises on anything but a real request
    failure -- callers treat that as "couldn't check, assume nothing busy"."""
    resp = requests.post(
        f'{CALENDAR_BASE}/freeBusy',
        headers=_headers(account),
        json={
            'timeMin': day_start.isoformat() + 'Z',
            'timeMax': day_end.isoformat() + 'Z',
            'items': [{'id': account.calendar_id}],
        },
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    busy = resp.json()['calendars'][account.calendar_id]['busy']
    return [
        (datetime.fromisoformat(b['start'].replace('Z', '+00:00')).replace(tzinfo=None),
         datetime.fromisoformat(b['end'].replace('Z', '+00:00')).replace(tzinfo=None))
        for b in busy
    ]


def create_event(account, appointment, business):
    """Creates the calendar event for a confirmed booking, returns the new
    event id. sendUpdates=none -- this platform's own notify()/receipt
    email already tells the customer; a second Google invite would just
    double up on that."""
    event = {
        'summary': f'{appointment.service_type.name if appointment.service_type else "Booking"} -- {appointment.customer_label}',
        'description': f'Booked via {business.name} on Gut Shtick (appointment #{appointment.id})',
        'start': {'dateTime': appointment.start_at.isoformat()},
        'end': {'dateTime': appointment.end_at.isoformat()},
    }
    resp = requests.post(
        f'{CALENDAR_BASE}/calendars/{account.calendar_id}/events',
        headers=_headers(account), json=event,
        params={'sendUpdates': 'none'}, timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()['id']


def delete_event(account, event_id):
    resp = requests.delete(
        f'{CALENDAR_BASE}/calendars/{account.calendar_id}/events/{event_id}',
        headers=_headers(account), params={'sendUpdates': 'none'}, timeout=REQUEST_TIMEOUT,
    )
    # Google returns 410 Gone for an event already deleted on the calendar
    # itself (the owner removed it by hand) -- that's not a failure here.
    if resp.status_code not in (204, 404, 410):
        resp.raise_for_status()


def push_new_appointment(business, appointment):
    """Shared by both booking-confirmation call sites (a free service
    confirms immediately in routes/business_site_public.py; a paid one only
    once routes/payments.py's _mark_order_paid fires) -- looks up the
    business's CalendarAccount itself so neither caller duplicates that
    lookup. A no-op (not an error) when the business has no connected
    calendar. Raises on an actual API failure -- every call site wraps this
    in try/except, since a Calendar failure must never block a booking."""
    from backend.business.modals.calendar_account import CalendarAccount

    account = CalendarAccount.query.filter_by(business_id=business.id, status='active').first()
    if not account:
        return
    appointment.google_event_id = create_event(account, appointment, business)
    db.session.commit()


def get_user_email(access_token):
    """Display-only -- "Connected as <email>" in BookingsPanel.js."""
    resp = requests.get(
        'https://www.googleapis.com/oauth2/v2/userinfo',
        headers={'Authorization': f'Bearer {access_token}'}, timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json().get('email')


def get_primary_calendar_id(access_token):
    """Resolves the real primary calendar id right after connecting --
    used instead of the literal string 'primary' so a later freeBusy query
    (which needs the real id as its `items` key) lines up."""
    resp = requests.get(
        f'{CALENDAR_BASE}/calendars/primary',
        headers={'Authorization': f'Bearer {access_token}'}, timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json().get('id', 'primary')
