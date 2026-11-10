"""Google Calendar connect/disconnect for a business's own bookings. Same
state-signing/OAuth-callback shape as routes/payments.py's Stripe Connect
flow (kept local rather than imported, same reasoning payments.py and
social.py both give for duplicating _can_manage/_sign_state/_read_state).

Reuses the Google OAuth app already configured for Business Profile posting
(see social/publishers.get_credentials('google') + routes/admin_integrations.py)
-- just a different scope, not a second app.
"""
import os
from datetime import datetime, timedelta

import jwt as pyjwt
import requests
from flask import Blueprint, jsonify, redirect, request

from config import application, db
from security import token_required
from backend.business.modals.business import Business
from backend.business.modals.calendar_account import CalendarAccount
from backend.business.social.crypto import encrypt_token
from backend.business.social.publishers import get_credentials
from backend.business.calendar.google import get_user_email, get_primary_calendar_id

calendar_api = Blueprint('calendar_api', __name__, url_prefix='/business')

STATE_TTL_MINUTES = 15
AUTHORIZE_URL = 'https://accounts.google.com/o/oauth2/v2/auth'
TOKEN_URL = 'https://oauth2.googleapis.com/token'
SCOPE = 'https://www.googleapis.com/auth/calendar.events'


# TEMPORARY, prod-testing-only restriction -- see business_site.py's
# _can_manage for why (site builder is super-admin-only while testing on
# prod, not the usual is_boss-or-owner check).
def _can_manage(business, user):
    return bool(user and user.is_super_admin)


def _sign_state(payload):
    payload = {**payload, 'exp': datetime.utcnow() + timedelta(minutes=STATE_TTL_MINUTES)}
    return pyjwt.encode(payload, application.config['SECRET_KEY'], algorithm='HS256')


def _read_state(token):
    try:
        return pyjwt.decode(token, application.config['SECRET_KEY'], algorithms=['HS256'])
    except pyjwt.PyJWTError:
        return None


def _redirect_uri():
    base = os.environ.get('BACKEND_PUBLIC_URL', request.host_url.rstrip('/'))
    return f'{base}/business/calendar/oauth/google/callback'


def _frontend_return_url(business_id, ok, message=None):
    base = os.environ.get('FRONTEND_BUSINESS_URL', 'http://localhost:3000')
    status = 'connected' if ok else 'error'
    msg = f'&message={message}' if message else ''
    return f'{base}/business/{business_id}/tools?tab=site&calendar={status}{msg}'


def _serialize_account(account):
    if not account:
        return None
    return {
        'provider': account.provider,
        'status': account.status,
        'account_email': account.account_email,
        'connected_at': account.connected_at.isoformat() if account.connected_at else None,
    }


@calendar_api.route('/businesses/<int:business_id>/calendar/status', methods=['GET'])
@token_required
def calendar_status(current_user, business_id):
    business = db.session.get(Business, business_id)
    if not business or not _can_manage(business, current_user):
        return jsonify({'message': 'Not authorized'}), 403
    account = CalendarAccount.query.filter_by(business_id=business_id).first()
    client_id, client_secret = get_credentials('google')
    return jsonify({
        'account': _serialize_account(account),
        'google_configured': bool(client_id and client_secret),
    })


@calendar_api.route('/businesses/<int:business_id>/calendar/connect/start', methods=['POST'])
@token_required
def start_connect(current_user, business_id):
    business = db.session.get(Business, business_id)
    if not business or not _can_manage(business, current_user):
        return jsonify({'message': 'Not authorized'}), 403
    client_id, client_secret = get_credentials('google')
    if not client_id or not client_secret:
        return jsonify({'message': "Google isn't configured on this deployment yet (missing app credentials)"}), 501

    state = _sign_state({'business_id': business_id, 'user_id': current_user.public_id})
    params = {
        'client_id': client_id,
        'redirect_uri': _redirect_uri(),
        'response_type': 'code',
        'scope': SCOPE,
        'access_type': 'offline',
        'prompt': 'consent',  # forces a refresh_token every time, even on a re-connect
        'state': state,
    }
    authorize_url = f'{AUTHORIZE_URL}?{requests.compat.urlencode(params)}'
    return jsonify({'authorize_url': authorize_url})


@calendar_api.route('/calendar/oauth/google/callback', methods=['GET'])
def oauth_callback():
    state = _read_state(request.args.get('state', ''))
    if not state:
        return redirect(_frontend_return_url(0, False, 'That connection link expired -- try again'))

    business_id = state['business_id']
    code = request.args.get('code')
    if not code:
        return redirect(_frontend_return_url(business_id, False, 'Connection was cancelled'))

    client_id, client_secret = get_credentials('google')
    if not client_id or not client_secret:
        return redirect(_frontend_return_url(business_id, False, 'Google is no longer configured'))

    try:
        resp = requests.post(TOKEN_URL, data={
            'grant_type': 'authorization_code', 'code': code,
            'redirect_uri': _redirect_uri(), 'client_id': client_id, 'client_secret': client_secret,
        }, timeout=15)
        resp.raise_for_status()
        tokens = resp.json()
    except requests.RequestException:
        return redirect(_frontend_return_url(business_id, False, 'Could not complete that connection'))

    access_token = tokens.get('access_token')
    refresh_token = tokens.get('refresh_token')
    if not refresh_token:
        # Happens if the owner had already granted this scope before and
        # Google skipped re-issuing one -- prompt=consent above should
        # prevent this, but fail clearly rather than silently storing an
        # account that can never refresh once the access token expires.
        return redirect(_frontend_return_url(business_id, False, 'Could not get a refresh token -- try disconnecting any prior Google access for this app first'))
    expires_in = tokens.get('expires_in')

    try:
        calendar_id = get_primary_calendar_id(access_token)
        email = get_user_email(access_token)
    except requests.RequestException as exc:
        hint = 'calendar_api_disabled' if 'accessNotConfigured' in str(exc) or '403' in str(exc) else 'calendar_api_error'
        return redirect(_frontend_return_url(business_id, False, hint))

    account = CalendarAccount.query.filter_by(business_id=business_id).first()
    if not account:
        account = CalendarAccount(business_id=business_id, provider='google')
        db.session.add(account)
    account.calendar_id = calendar_id
    account.account_email = email
    account.access_token_enc = encrypt_token(access_token)
    account.refresh_token_enc = encrypt_token(refresh_token)
    account.expires_at = datetime.utcnow() + timedelta(seconds=int(expires_in)) if expires_in else None
    account.status = 'active'
    account.connected_by = state['user_id']
    account.connected_at = datetime.utcnow()
    db.session.commit()

    return redirect(_frontend_return_url(business_id, True))


@calendar_api.route('/businesses/<int:business_id>/calendar/disconnect', methods=['DELETE'])
@token_required
def disconnect(current_user, business_id):
    business = db.session.get(Business, business_id)
    if not business or not _can_manage(business, current_user):
        return jsonify({'message': 'Not authorized'}), 403
    account = CalendarAccount.query.filter_by(business_id=business_id).first()
    if account:
        db.session.delete(account)
        db.session.commit()
    return jsonify({'message': 'Disconnected'})
