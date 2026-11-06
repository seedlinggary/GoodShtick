"""Server-to-Nedarim-Plus calls against Manage3.aspx -- history sync,
standing-order ('Keva') reports for decline detection, and LIVE standing-
order writes (update amount / delete / disable / enable). All require a
nonprofit's own Mosad number + ApiPassword (NonprofitPaymentConfig),
unlike the payment-link builder in nedarim.py which only needs the
Mosad number (ApiValid is sent client-side, not here).

Genuinely still a quirky vendor API, faithfully preserved as found rather
than smoothed over: inconsistent parameter naming (some actions want
`MosadId`, others `MosadNumber`, for the exact same value -- not a typo,
confirmed against Nedarim Plus's own docs), and THREE different response
shapes across the four write actions (DeleteKeva/DisableKeva: bare "OK" or
plain-text error; EnableKevaNew: {"NextDate": "..."} JSON on success, text
on error; UpdateKevaNew: real {Result, Message} JSON either way).
History/report reads are rate-limited by Nedarim Plus itself to 20 calls/
hour -- callers must not retry aggressively on failure.
"""
import requests

from backend.business.nonprofit_payments.nedarim import MANAGE_API_BASE, to_number, parse_nedarim_date

REQUEST_TIMEOUT = 20


class NedarimAdminError(Exception):
    """Raised when Nedarim Plus's own API reports an error (Result=Error,
    a bare non-'OK' text response, etc) -- never for a network/transport
    failure, which raises requests.RequestException instead and is left
    for the caller to decide how to handle (usually: log and move on,
    since none of these calls are safe to blindly retry)."""


def _get_history(mosad_id, api_password, last_id=None, max_id=2000):
    """GetHistoryJson -- every successful credit-card transaction/
    installment, used for the daily reconciliation sync (catches anything
    a missed/failed webhook delivery would otherwise silently drop).
    Results are ordered by ascending TransactionId; callers persist the
    highest TransactionId seen and pass it back as last_id next time."""
    params = {'Action': 'GetHistoryJson', 'MosadId': mosad_id, 'ApiPassword': api_password, 'MaxId': max_id}
    if last_id is not None:
        params['LastId'] = last_id
    resp = requests.get(MANAGE_API_BASE, params=params, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    try:
        return resp.json()
    except ValueError:
        raise NedarimAdminError(resp.text[:500])


def get_history(config, last_id=None, max_id=2000):
    return _get_history(config.mosad_id, config.api_password, last_id=last_id, max_id=max_id)


def get_keva_history(config, last_id=None, max_id=2000):
    """GetKevaJson -- the full transaction/attempt history of every
    standing order, INCLUDING declines (ErrorText populated) and frozen/
    disabled ones (Enabled=0). This is the only automatic decline signal
    Nedarim Plus exposes anywhere, and it only ever covers memberships --
    a one-time ('Ragil') decline is never reported anywhere by Nedarim
    Plus; it simply never creates a transaction at all."""
    params = {'Action': 'GetKevaJson', 'MosadId': config.mosad_id, 'ApiPassword': config.api_password, 'MaxId': max_id}
    if last_id is not None:
        params['LastId'] = last_id
    resp = requests.get(MANAGE_API_BASE, params=params, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    try:
        return resp.json()
    except ValueError:
        raise NedarimAdminError(resp.text[:500])


def get_keva_detail(config, keva_id):
    """GetKevaId -- full detail + charge history for one standing order
    (KevaStatus: 1 active | 2 frozen/disabled | 3 deleted)."""
    params = {'Action': 'GetKevaId', 'MosadId': config.mosad_id, 'ApiPassword': config.api_password, 'KevaId': keva_id}
    resp = requests.get(MANAGE_API_BASE, params=params, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    try:
        return resp.json()
    except ValueError:
        raise NedarimAdminError(resp.text[:500])


def update_keva_amount(config, keva_id, amount_cents):
    """UpdateKevaNew is a PARTIAL update -- only Amount is sent here, so
    every other field on the standing order (contact info, category,
    remaining-payments count, etc) is left exactly as it already is on
    Nedarim Plus's side. Returns {Result, Message} JSON either way;
    raises NedarimAdminError if Result != 'OK'."""
    params = {
        'Action': 'UpdateKevaNew', 'MosadNumber': config.mosad_id, 'ApiPassword': config.api_password,
        'KevaId': keva_id, 'Amount': amount_cents / 100,
    }
    resp = requests.get(MANAGE_API_BASE, params=params, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    try:
        data = resp.json()
    except ValueError:
        raise NedarimAdminError(resp.text[:500])
    if data.get('Result') != 'OK':
        raise NedarimAdminError(data.get('Message') or 'Unknown error updating the standing order')
    return data


def delete_keva(config, keva_id):
    """DeleteKeva is PERMANENT on Nedarim Plus's side -- there is no way
    to undo it through the API (a brand new standing order would have to
    be set up from scratch, with a new KevaId). Use disable_keva for a
    reversible pause instead. Response is plain text: 'OK' or an error
    string -- never JSON."""
    params = {'Action': 'DeleteKeva', 'MosadNumber': config.mosad_id, 'ApiPassword': config.api_password, 'KevaId': keva_id}
    resp = requests.get(MANAGE_API_BASE, params=params, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    text = resp.text.strip()
    if text != 'OK':
        raise NedarimAdminError(text[:500] or 'Unknown error deleting the standing order')
    return True


def disable_keva(config, keva_id):
    """DisableKeva freezes the standing order -- reversible via
    enable_keva. Plain-text 'OK'/error response, like delete_keva."""
    params = {'Action': 'DisableKeva', 'MosadNumber': config.mosad_id, 'ApiPassword': config.api_password, 'KevaId': keva_id}
    resp = requests.get(MANAGE_API_BASE, params=params, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    text = resp.text.strip()
    if text != 'OK':
        raise NedarimAdminError(text[:500] or 'Unknown error freezing the standing order')
    return True


def enable_keva(config, keva_id):
    """EnableKevaNew re-activates a frozen standing order. If the next
    charge date already passed while frozen, Nedarim Plus auto-advances
    it in whole months to the next one that hasn't passed yet -- this is
    THEIR behavior, not something to recompute here. Can't enable an
    order with no saved card on file. Success is JSON {"NextDate": "dd/
    MM/yy"} -- the only one of these four write actions whose success
    response is JSON instead of plain text; errors are still plain text."""
    params = {'Action': 'EnableKevaNew', 'MosadNumber': config.mosad_id, 'ApiPassword': config.api_password, 'KevaId': keva_id}
    resp = requests.get(MANAGE_API_BASE, params=params, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    text = resp.text.strip()
    try:
        data = resp.json()
    except ValueError:
        raise NedarimAdminError(text[:500] or 'Unknown error re-activating the standing order')
    next_date = parse_nedarim_date(data.get('NextDate'))
    return next_date
