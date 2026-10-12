"""Per-platform "actually call the API" layer for the social composer.

Each publish_* function takes a SocialAccount (decrypted token attached by
the caller) and a SocialPost, and returns (remote_post_id, error) --
exactly one of the two is set. Nothing here runs unless the corresponding
app credentials are configured (see is_configured), so a business owner
connecting an account on a deployment that hasn't set up a Meta/Google/X
app yet gets a clear "not configured" response instead of a confusing
failure deep in an HTTP call.

Facebook Page + Instagram Business post through the same Meta Graph API app;
Google posts through the Business Profile (My Business) API; X posts through
API v2. TikTok and WhatsApp Status have no public "post on behalf of a user"
API at all -- those are handled entirely client-side via the share-sheet
handoff (see routes/social.py's /share-payload), never through this module.
"""
import os

import requests

GRAPH_API_VERSION = 'v19.0'
GRAPH_BASE = f'https://graph.facebook.com/{GRAPH_API_VERSION}'
GOOGLE_BUSINESS_BASE = 'https://mybusiness.googleapis.com/v4'
X_API_BASE = 'https://api.twitter.com/2'

REQUEST_TIMEOUT = 15

# instagram shares the same Meta app/credential row as facebook.
CREDENTIAL_KEY = {
    'facebook': 'facebook', 'instagram': 'facebook', 'google': 'google',
    'x': 'x', 'linkedin': 'linkedin',
}
ENV_VAR_NAMES = {
    'facebook': ('META_APP_ID', 'META_APP_SECRET'),
    'google': ('GOOGLE_CLIENT_ID', 'GOOGLE_CLIENT_SECRET'),
    'x': ('X_CLIENT_ID', 'X_CLIENT_SECRET'),
    'linkedin': ('LINKEDIN_CLIENT_ID', 'LINKEDIN_CLIENT_SECRET'),
}


def get_credentials(platform):
    """(client_id, client_secret) for this platform, or (None, None) if
    nothing's configured. Checks the admin-editable PlatformCredential table
    first (see routes/admin_integrations.py) and falls back to environment
    variables, so either a UI-configured deployment or an env-var-configured
    one works without code changes."""
    from backend.business.modals.platform_credential import PlatformCredential
    from backend.business.social.crypto import decrypt_token

    key = CREDENTIAL_KEY.get(platform)
    if not key:
        return None, None
    row = PlatformCredential.query.filter_by(platform=key).first()
    if row:
        return row.client_id, decrypt_token(row.client_secret_enc)

    id_env, secret_env = ENV_VAR_NAMES.get(key, (None, None))
    if id_env and os.environ.get(id_env) and os.environ.get(secret_env):
        return os.environ[id_env], os.environ[secret_env]
    return None, None


def platform_credentials_configured():
    client_id, client_secret = None, None
    result = {}
    for platform in ('facebook', 'instagram', 'google', 'x', 'linkedin'):
        client_id, client_secret = get_credentials(platform)
        result[platform] = bool(client_id and client_secret)
    # tiktok/whatsapp are share-sheet only -- always "available" since they
    # need no app credentials at all.
    result['tiktok'] = True
    result['whatsapp'] = True
    return result


def is_configured(platform):
    return platform_credentials_configured().get(platform, False)


def publish_facebook(account, post, media_url=None):
    token = account['access_token']
    page_id = account['external_account_id']
    try:
        if media_url:
            resp = requests.post(
                f'{GRAPH_BASE}/{page_id}/photos',
                data={'url': media_url, 'caption': post.caption, 'access_token': token},
                timeout=REQUEST_TIMEOUT,
            )
        else:
            resp = requests.post(
                f'{GRAPH_BASE}/{page_id}/feed',
                data={'message': post.caption, 'link': post.link_url or None, 'access_token': token},
                timeout=REQUEST_TIMEOUT,
            )
        resp.raise_for_status()
        data = resp.json()
        return data.get('post_id') or data.get('id'), None
    except requests.RequestException as exc:
        return None, _extract_error(exc)


def publish_instagram(account, post, media_url):
    if not media_url:
        return None, 'Instagram requires an image or video'
    ig_user_id = account['external_account_id']
    token = account['access_token']
    try:
        container = requests.post(
            f'{GRAPH_BASE}/{ig_user_id}/media',
            data={'image_url': media_url, 'caption': post.caption, 'access_token': token},
            timeout=REQUEST_TIMEOUT,
        )
        container.raise_for_status()
        creation_id = container.json().get('id')
        publish = requests.post(
            f'{GRAPH_BASE}/{ig_user_id}/media_publish',
            data={'creation_id': creation_id, 'access_token': token},
            timeout=REQUEST_TIMEOUT,
        )
        publish.raise_for_status()
        return publish.json().get('id'), None
    except requests.RequestException as exc:
        return None, _extract_error(exc)


def publish_google(account, post, media_url=None):
    """Google Business Profile 'local post' -- shows directly in Search/Maps."""
    token = account['access_token']
    account_location = account['external_account_id']  # "accounts/{id}/locations/{id}"
    body = {
        'languageCode': 'en-US',
        'summary': post.caption,
        'topicType': 'STANDARD',
    }
    if media_url:
        body['media'] = [{'mediaFormat': 'PHOTO', 'sourceUrl': media_url}]
    if post.link_url:
        body['callToAction'] = {'actionType': 'LEARN_MORE', 'url': post.link_url}
    try:
        resp = requests.post(
            f'{GOOGLE_BUSINESS_BASE}/{account_location}/localPosts',
            json=body,
            headers={'Authorization': f'Bearer {token}'},
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get('name'), None
    except requests.RequestException as exc:
        return None, _extract_error(exc)


def publish_x(account, post, media_url=None):
    token = account['access_token']
    try:
        resp = requests.post(
            f'{X_API_BASE}/tweets',
            json={'text': post.caption[:280]},
            headers={'Authorization': f'Bearer {token}'},
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json().get('data', {}).get('id'), None
    except requests.RequestException as exc:
        return None, _extract_error(exc)


def publish_linkedin(account, post, media_url=None):
    token = account['access_token']
    author = account['external_account_id']
    body = {
        'author': author,
        'lifecycleState': 'PUBLISHED',
        'specificContent': {
            'com.linkedin.ugc.ShareContent': {
                'shareCommentary': {'text': post.caption},
                'shareMediaCategory': 'NONE',
            }
        },
        'visibility': {'com.linkedin.ugc.MemberNetworkVisibility': 'PUBLIC'},
    }
    try:
        resp = requests.post(
            'https://api.linkedin.com/v2/ugcPosts',
            json=body,
            headers={'Authorization': f'Bearer {token}', 'X-Restli-Protocol-Version': '2.0.0'},
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.headers.get('x-restli-id'), None
    except requests.RequestException as exc:
        return None, _extract_error(exc)


PUBLISHERS = {
    'facebook': publish_facebook,
    'instagram': publish_instagram,
    'google': publish_google,
    'x': publish_x,
    'linkedin': publish_linkedin,
}


def _extract_error(exc):
    resp = getattr(exc, 'response', None)
    if resp is not None:
        try:
            data = resp.json()
            return (data.get('error') or {}).get('message') or str(data)[:300]
        except ValueError:
            return resp.text[:300]
    return str(exc)[:300]
