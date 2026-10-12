"""The Social Desk: connect Facebook/Instagram/Google/X/LinkedIn accounts via
OAuth and compose one post that fans out to all of them, plus a share-sheet
handoff for TikTok/WhatsApp Status (no public posting API exists for either,
so those are never attempted server-side -- see social/publishers.py).

Every route here degrades to a clear "not configured" response rather than a
confusing failure when this deployment hasn't set up the relevant app's
client id/secret env vars yet -- see social/publishers.py:is_configured.
"""
import base64
import hashlib
import os
import random
import secrets
from datetime import datetime, timedelta

import jwt as pyjwt
import requests
from flask import Blueprint, jsonify, redirect, request

from config import application, db
from security import token_required, token_optional, cron_secret_required, super_admin_required
from upload import get_public_url
from backend.business.modals.business import Business
from backend.business.modals.social_account import SocialAccount, SOCIAL_PLATFORMS, API_PLATFORMS, SHARE_SHEET_PLATFORMS
from backend.business.modals.social_post import SocialPost, SocialPostTarget
from backend.business.schemas.social import SocialPostSchema, PlatformStatusSchema
from backend.business.social.crypto import encrypt_token, decrypt_token
from backend.business.social import publishers
from backend.business.social.campaigns import upcoming_campaign_templates

social_api = Blueprint('social_api', __name__, url_prefix='/business')

CAPTION_MAX = 2200
STATE_TTL_MINUTES = 15
# Opportunistic trigger for scheduled posts, same reasoning/pattern as
# analytics/routes/visitor.py's _maybe_cleanup: this repo has no verified
# cron wiring, so a small random chance of a due-post sweep on a
# high-traffic public route (see business.py's list_businesses) converges
# on "checked roughly every N requests" without needing deploy-time cron
# config. /social/cron/publish-due still exists too, for anyone who wants to
# point a real external scheduler at it for tighter timing.
PUBLISH_CHECK_CHANCE = 0.05


def _can_manage(business, user):
    """Mirrors business.py's _can_manage -- kept local instead of imported to
    avoid a circular import between the two route modules."""
    if not user:
        return False
    if user.is_boss:
        return True
    if business.owner_user_id:
        return business.owner_user_id == user.public_id
    return business.created_by == user.public_id

OAUTH_CONFIGS = {
    'facebook': {
        'authorize_url': 'https://www.facebook.com/v19.0/dialog/oauth',
        'token_url': 'https://graph.facebook.com/v19.0/oauth/access_token',
        'client_id_env': 'META_APP_ID', 'client_secret_env': 'META_APP_SECRET',
        'scope': 'pages_manage_posts,pages_read_engagement,pages_show_list',
    },
    'instagram': {
        'authorize_url': 'https://www.facebook.com/v19.0/dialog/oauth',
        'token_url': 'https://graph.facebook.com/v19.0/oauth/access_token',
        'client_id_env': 'META_APP_ID', 'client_secret_env': 'META_APP_SECRET',
        'scope': 'pages_show_list,instagram_basic,instagram_content_publish',
    },
    'google': {
        'authorize_url': 'https://accounts.google.com/o/oauth2/v2/auth',
        'token_url': 'https://oauth2.googleapis.com/token',
        'client_id_env': 'GOOGLE_CLIENT_ID', 'client_secret_env': 'GOOGLE_CLIENT_SECRET',
        'scope': 'https://www.googleapis.com/auth/business.manage',
        'extra_authorize_params': {'access_type': 'offline', 'prompt': 'consent'},
    },
    'x': {
        'authorize_url': 'https://twitter.com/i/oauth2/authorize',
        'token_url': 'https://api.twitter.com/2/oauth2/token',
        'client_id_env': 'X_CLIENT_ID', 'client_secret_env': 'X_CLIENT_SECRET',
        'scope': 'tweet.read tweet.write users.read offline.access',
        'pkce': True,
    },
    'linkedin': {
        'authorize_url': 'https://www.linkedin.com/oauth/v2/authorization',
        'token_url': 'https://www.linkedin.com/oauth/v2/accessToken',
        'client_id_env': 'LINKEDIN_CLIENT_ID', 'client_secret_env': 'LINKEDIN_CLIENT_SECRET',
        'scope': 'w_member_social',
    },
}


def _redirect_uri(platform):
    base = os.environ.get('BACKEND_PUBLIC_URL', request.host_url.rstrip('/'))
    return f'{base}/business/social/oauth/{platform}/callback'


def _frontend_return_url(business_id, ok, message=None):
    base = os.environ.get('FRONTEND_BUSINESS_URL', 'http://localhost:3000')
    status = 'connected' if ok else 'error'
    msg = f'&message={message}' if message else ''
    return f'{base}/business/{business_id}/edit?social={status}{msg}#social-desk'


def _sign_state(payload):
    payload = {**payload, 'exp': datetime.utcnow() + timedelta(minutes=STATE_TTL_MINUTES)}
    return pyjwt.encode(payload, application.config['SECRET_KEY'], algorithm='HS256')


def _read_state(token):
    try:
        return pyjwt.decode(token, application.config['SECRET_KEY'], algorithms=['HS256'])
    except pyjwt.PyJWTError:
        return None


def _pkce_pair():
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(40)).decode().rstrip('=')
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
    return verifier, challenge


# ── Status / connect / disconnect ───────────────────────────────────────────

@social_api.route('/businesses/<int:business_id>/social/status', methods=['GET'])
@super_admin_required
def social_status(current_user, business_id):
    business = db.session.get(Business, business_id)
    if not business or not _can_manage(business, current_user):
        return jsonify({'message': 'Not authorized'}), 403

    accounts = {a.platform: a for a in SocialAccount.query.filter_by(business_id=business_id).all()}
    rows = []
    for platform in SOCIAL_PLATFORMS:
        rows.append({
            'platform': platform,
            'connected': platform in accounts,
            'account': accounts.get(platform),
            'mode': 'api' if platform in API_PLATFORMS else 'share_sheet',
        })
    return jsonify(PlatformStatusSchema(many=True).dump(rows))


@social_api.route('/businesses/<int:business_id>/social/connect/<platform>', methods=['POST'])
@super_admin_required
def start_connect(current_user, business_id, platform):
    business = db.session.get(Business, business_id)
    if not business or not _can_manage(business, current_user):
        return jsonify({'message': 'Not authorized'}), 403
    if platform not in OAUTH_CONFIGS:
        return jsonify({'message': f'{platform} connects via the share sheet, not OAuth'}), 400
    if not publishers.is_configured(platform):
        return jsonify({'message': f'{platform.title()} isn\'t configured on this deployment yet '
                                    f'(missing app credentials) -- connecting will work once that\'s set up.'}), 501

    cfg = OAUTH_CONFIGS[platform]
    client_id, _ = publishers.get_credentials(platform)
    state_payload = {'business_id': business_id, 'user_id': current_user.public_id, 'platform': platform}

    params = {
        'client_id': client_id,
        'redirect_uri': _redirect_uri(platform),
        'scope': cfg['scope'],
        'response_type': 'code',
    }
    if cfg.get('pkce'):
        verifier, challenge = _pkce_pair()
        state_payload['code_verifier'] = verifier
        params['code_challenge'] = challenge
        params['code_challenge_method'] = 'S256'
    params.update(cfg.get('extra_authorize_params', {}))
    params['state'] = _sign_state(state_payload)

    authorize_url = f'{cfg["authorize_url"]}?{requests.compat.urlencode(params)}'
    return jsonify({'authorize_url': authorize_url})


@social_api.route('/businesses/<int:business_id>/social/campaign-templates', methods=['GET'])
@super_admin_required
def campaign_templates(current_user, business_id):
    business = db.session.get(Business, business_id)
    if not business or not _can_manage(business, current_user):
        return jsonify({'message': 'Not authorized'}), 403
    templates = upcoming_campaign_templates(category=business.category, business_name=business.name)
    return jsonify(templates)


@social_api.route('/social/oauth/<platform>/callback', methods=['GET'])
def oauth_callback(platform):
    state = _read_state(request.args.get('state', ''))
    if not state or state.get('platform') != platform:
        return redirect(_frontend_return_url(0, False, 'That connection link expired -- try again'))

    business_id = state['business_id']
    code = request.args.get('code')
    if not code:
        return redirect(_frontend_return_url(business_id, False, 'Connection was cancelled'))

    cfg = OAUTH_CONFIGS[platform]
    client_id, client_secret = publishers.get_credentials(platform)
    if not client_id or not client_secret:
        return redirect(_frontend_return_url(business_id, False, 'This platform is no longer configured'))
    token_body = {
        'grant_type': 'authorization_code',
        'code': code,
        'redirect_uri': _redirect_uri(platform),
        'client_id': client_id,
        'client_secret': client_secret,
    }
    if cfg.get('pkce'):
        token_body['code_verifier'] = state.get('code_verifier')

    try:
        resp = requests.post(cfg['token_url'], data=token_body, timeout=15)
        resp.raise_for_status()
        tokens = resp.json()
    except requests.RequestException:
        return redirect(_frontend_return_url(business_id, False, 'Could not complete that connection'))

    access_token = tokens.get('access_token')
    refresh_token = tokens.get('refresh_token')
    expires_in = tokens.get('expires_in')
    expires_at = datetime.utcnow() + timedelta(seconds=int(expires_in)) if expires_in else None

    external_id, external_name, error = _resolve_identity(platform, access_token)
    if error:
        return redirect(_frontend_return_url(business_id, False, error))

    account = SocialAccount.query.filter_by(business_id=business_id, platform=platform).first()
    if not account:
        account = SocialAccount(business_id=business_id, platform=platform, external_account_id=external_id)
        db.session.add(account)
    account.external_account_id = external_id
    account.external_account_name = external_name
    account.access_token_enc = encrypt_token(access_token)
    if refresh_token:
        account.refresh_token_enc = encrypt_token(refresh_token)
    account.expires_at = expires_at
    account.status = 'active'
    account.last_error = None
    account.connected_by = state['user_id']
    db.session.commit()

    return redirect(_frontend_return_url(business_id, True))


def _resolve_identity(platform, access_token):
    """Fetches the actual postable account id (a Facebook Page, an Instagram
    Business account, etc) -- the OAuth token alone only proves who logged
    in, not which page/profile to post to. Returns (id, name, error)."""
    try:
        if platform == 'facebook':
            resp = requests.get('https://graph.facebook.com/v19.0/me/accounts',
                                 params={'access_token': access_token}, timeout=15)
            resp.raise_for_status()
            pages = resp.json().get('data', [])
            if not pages:
                return None, None, 'No Facebook Pages found for that login -- you need to manage at least one Page'
            page = pages[0]
            return page['id'], page.get('name'), None
        if platform == 'instagram':
            resp = requests.get('https://graph.facebook.com/v19.0/me/accounts',
                                 params={'access_token': access_token,
                                         'fields': 'instagram_business_account,name'}, timeout=15)
            resp.raise_for_status()
            for page in resp.json().get('data', []):
                ig = page.get('instagram_business_account')
                if ig:
                    return ig['id'], page.get('name'), None
            return None, None, 'No Instagram Business account linked to any of your Facebook Pages'
        if platform == 'google':
            resp = requests.get('https://mybusinessaccountmanagement.googleapis.com/v1/accounts',
                                 headers={'Authorization': f'Bearer {access_token}'}, timeout=15)
            resp.raise_for_status()
            accounts = resp.json().get('accounts', [])
            if not accounts:
                return None, None, 'No Google Business Profile found for that login'
            return accounts[0]['name'], accounts[0].get('accountName'), None
        if platform == 'x':
            resp = requests.get('https://api.twitter.com/2/users/me',
                                 headers={'Authorization': f'Bearer {access_token}'}, timeout=15)
            resp.raise_for_status()
            data = resp.json().get('data', {})
            return data.get('id'), data.get('username'), None
        if platform == 'linkedin':
            resp = requests.get('https://api.linkedin.com/v2/userinfo',
                                 headers={'Authorization': f'Bearer {access_token}'}, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            return f'urn:li:person:{data.get("sub")}', data.get('name'), None
    except requests.RequestException as exc:
        return None, None, publishers._extract_error(exc)
    return None, None, 'Unsupported platform'


@social_api.route('/businesses/<int:business_id>/social/disconnect/<platform>', methods=['DELETE'])
@super_admin_required
def disconnect(current_user, business_id, platform):
    business = db.session.get(Business, business_id)
    if not business or not _can_manage(business, current_user):
        return jsonify({'message': 'Not authorized'}), 403
    account = SocialAccount.query.filter_by(business_id=business_id, platform=platform).first()
    if account:
        db.session.delete(account)
        db.session.commit()
    return jsonify({'message': 'Disconnected'})


# ── Composer ─────────────────────────────────────────────────────────────

@social_api.route('/businesses/<int:business_id>/social/posts', methods=['POST'])
@super_admin_required
def create_post(current_user, business_id):
    business = db.session.get(Business, business_id)
    if not business or not _can_manage(business, current_user):
        return jsonify({'message': 'Not authorized'}), 403

    body = request.get_json() or {}
    caption = (body.get('caption') or '').strip()
    if not caption:
        return jsonify({'message': 'Caption is required'}), 400
    if len(caption) > CAPTION_MAX:
        return jsonify({'message': f'Caption must be {CAPTION_MAX} characters or fewer'}), 400

    platforms = [p for p in (body.get('platforms') or []) if p in SOCIAL_PLATFORMS]
    if not platforms:
        return jsonify({'message': 'Pick at least one platform'}), 400

    scheduled_at = None
    if body.get('scheduled_at'):
        try:
            scheduled_at = datetime.fromisoformat(body['scheduled_at'].replace('Z', '+00:00')).replace(tzinfo=None)
        except ValueError:
            return jsonify({'message': 'scheduled_at must be an ISO datetime'}), 400

    post = SocialPost(
        business_id=business_id, created_by=current_user.public_id, caption=caption,
        media=body.get('media') or None, link_url=(body.get('link_url') or '').strip() or None,
        scheduled_at=scheduled_at, status='scheduled' if scheduled_at else 'draft',
    )
    db.session.add(post)
    db.session.flush()

    accounts = {a.platform: a for a in SocialAccount.query.filter_by(business_id=business_id).all()}
    for platform in platforms:
        account = accounts.get(platform)
        status = 'share_pending' if platform in SHARE_SHEET_PLATFORMS else 'pending'
        db.session.add(SocialPostTarget(social_post_id=post.id, platform=platform,
                                         social_account_id=account.id if account else None, status=status))
    db.session.commit()

    if not scheduled_at:
        _publish_now(post)

    db.session.commit()
    return jsonify(SocialPostSchema().dump(post)), 201


@social_api.route('/businesses/<int:business_id>/social/posts', methods=['GET'])
@super_admin_required
def list_posts(current_user, business_id):
    business = db.session.get(Business, business_id)
    if not business or not _can_manage(business, current_user):
        return jsonify({'message': 'Not authorized'}), 403
    posts = (SocialPost.query.filter_by(business_id=business_id)
             .order_by(SocialPost.created_at.desc()).limit(50).all())
    return jsonify(SocialPostSchema(many=True).dump(posts))


@social_api.route('/businesses/<int:business_id>/social/posts/<int:post_id>/share-payload/<platform>', methods=['GET'])
@super_admin_required
def share_payload(current_user, business_id, post_id, platform):
    """What the frontend hands to navigator.share() for TikTok/WhatsApp
    Status -- the honest workaround for the two platforms with no public
    posting API. Not automation: the owner still taps once more inside
    their own phone's share sheet, but the caption/image are ready to go."""
    post = db.session.get(SocialPost, post_id)
    business = db.session.get(Business, business_id)
    if not post or post.business_id != business_id or not business or not _can_manage(business, current_user):
        return jsonify({'message': 'Not authorized'}), 403
    return jsonify({
        'caption': post.caption,
        'media_url': get_public_url(post.media) if post.media else None,
        'platform': platform,
    })


def _publish_now(post):
    for target in post.targets:
        if target.status not in ('pending',):
            continue
        publisher = publishers.PUBLISHERS.get(target.platform)
        if not publisher or not target.account:
            target.status = 'failed'
            target.error = 'No connected account for this platform'
            continue
        access_token = decrypt_token(target.account.access_token_enc)
        media_url = get_public_url(post.media) if post.media else None
        remote_id, error = publisher(
            {'access_token': access_token, 'external_account_id': target.account.external_account_id},
            post, media_url,
        )
        if error:
            target.status = 'failed'
            target.error = error
        else:
            target.status = 'posted'
            target.remote_post_id = remote_id
            target.posted_at = datetime.utcnow()

    statuses = {t.status for t in post.targets if t.status != 'share_pending'}
    if not statuses:
        post.status = 'posted'  # share-sheet-only post: "posted" once composed, the rest is on-device
    elif statuses == {'posted'}:
        post.status = 'posted'
    elif 'posted' in statuses:
        post.status = 'partial'
    else:
        post.status = 'failed'


@social_api.route('/social/cron/publish-due', methods=['POST'])
@cron_secret_required
def publish_due():
    """For anyone who wants tighter timing than the opportunistic sweep below
    -- point a real external scheduler (cron-job.org, etc.) at this with the
    X-Cron-Secret header set to CRON_SECRET."""
    due = SocialPost.query.filter(SocialPost.status == 'scheduled',
                                   SocialPost.scheduled_at <= datetime.utcnow()).all()
    for post in due:
        _publish_now(post)
    db.session.commit()
    return jsonify({'published': len(due)})


def maybe_publish_due_posts():
    """Called opportunistically from a high-traffic public route (see
    business.py's list_businesses) -- never raises, never blocks the request
    that triggered it."""
    if random.random() >= PUBLISH_CHECK_CHANCE:
        return
    try:
        due = (SocialPost.query.filter(SocialPost.status == 'scheduled',
                                        SocialPost.scheduled_at <= datetime.utcnow())
               .limit(20).all())
        for post in due:
            _publish_now(post)
        if due:
            db.session.commit()
    except Exception:
        db.session.rollback()
