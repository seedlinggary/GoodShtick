"""Nedarim Plus (Matara.pro) -- the Israeli, donation-focused payment
gateway the ported system uses. Fundamentally not OAuth/Checkout-Session
shaped like Stripe (see backend/business/payments/providers/nedarim_plus.py,
which is a DIFFERENT, still-stubbed thing reserved for a future commerce/
storefront integration) -- a nonprofit's donation/membership payment flow
is instead: build a redirect URL to Nedarim Plus's own hosted payment page
-> they pay there -> redirect back to a thank-you page -> Nedarim Plus
separately fires a server-to-server webhook to actually confirm payment.
No card data ever touches this server.

Every mechanic here is ported faithfully from the real, already-running
system this module is based on (see modals/nonprofit.py's own docstring),
cross-checked against Nedarim Plus's own API docs where available.
"""
import re
from datetime import datetime, timezone
from urllib.parse import quote

PAYMENT_PAGE_BASE = 'https://www.matara.pro/nedarimplus/online/'
MANAGE_API_BASE = 'https://matara.pro/nedarimplus/Reports/Manage3.aspx'

# The only two source IPs Nedarim Plus's webhook/CallBack system sends
# from -- documented in NedarimPlus-API.md and confirmed by the ported
# system's own webhook handler. Nedarim Plus does NOT sign/HMAC its
# webhook payloads at all, so this allowlist (plus cross-checking the
# amount/reference against what we expected -- see routes/
# nonprofit_webhook.py) is the entire defense against a forged callback.
NEDARIM_WEBHOOK_IPS = ('18.196.146.117', '18.194.219.73')

# The Avour/Comments prefix convention that routes a webhook/report call
# back to the right local record -- 'BILL-<id>' / 'DON-<id>' / 'MEM-<id>'
# / 'LINK-<id>'. Nedarim Plus has no concept of "your own reference id"
# field, so this hand-rolled convention, encoded into the one free-text
# field Nedarim Plus DOES echo back verbatim, is the only way to recover
# which local record a given payment was for.
_REFERENCE_RE = re.compile(r'\b(BILL|DON|MEM|LINK)-([A-Za-z0-9]+)')


def extract_reference_from_comment(comment):
    """-> (prefix, id) or None. prefix is one of BILL/DON/MEM/LINK."""
    if not comment:
        return None
    m = _REFERENCE_RE.search(comment)
    if not m:
        return None
    return m.group(1), m.group(2)


def _q(value):
    """URL-encode a value for hand-building a Nedarim Plus query string --
    NOT urllib.parse.urlencode/URLSearchParams, because Nedarim Plus does
    not decode '+' back to a space (confirmed behavior in the ported
    system's own link-builder comments); quote() with no safe spaces
    avoids that entirely."""
    return quote(str(value), safe='')


def build_payment_link(mosad_id, reference_prefix, record_id, amount_cents, full_name,
                        redirect_url, phone=None, email=None, street=None, city=None,
                        groupe=None, language=None):
    """A one-time payment link, amount/payment-count LOCKED to a single
    full payment (Payment=1&PaymentLock=1, AmountLock=1) so the webhook's
    reported Amount always matches the record's own total -- an
    installment/partial payment would otherwise leave the record PENDING
    forever, since the webhook handler only flips status to PAID when the
    resolved amount exactly equals the record's expected amount."""
    shekels = amount_cents / 100
    avour = f'{reference_prefix}-{record_id}'
    params = [
        f'mosad={_q(mosad_id)}',
        f'Amount={_q(shekels)}', 'AmountLock=1',
        'Payment=1', 'PaymentLock=1',
        'OnlyNormal=1',
        f'ClientName={_q(full_name)}',
        f'Avour={_q(avour)}', 'AvourLock=1',
        f'Redirect={_q(redirect_url)}',
    ]
    if phone:
        params.append(f'Phone={_q(phone)}')
    if email:
        params.append(f'Email={_q(email)}')
    if street:
        params.append(f'Street={_q(street)}')
    if city:
        params.append(f'City={_q(city)}')
    if groupe:
        params.append(f'Groupe={_q(groupe)}&GroupeLock=1')
    if language:
        params.append(f'Language={_q(language)}')
    return f'{PAYMENT_PAGE_BASE}?{"&".join(params)}'


def build_recurring_payment_link(mosad_id, record_id, amount_cents, full_name,
                                  redirect_url, phone=None, email=None, street=None,
                                  city=None, groupe=None, language=None):
    """A recurring ('Keva', standing-order) payment link -- OnlyKeva=1
    instead of OnlyNormal=1, and Payment is deliberately left unset
    (Nedarim Plus treats a blank Payment count as ongoing/unlimited for a
    Keva setup, vs. a fixed payment count for a one-time Ragil payment).
    Always uses the 'MEM-' reference prefix."""
    shekels = amount_cents / 100
    avour = f'MEM-{record_id}'
    params = [
        f'mosad={_q(mosad_id)}',
        f'Amount={_q(shekels)}', 'AmountLock=1',
        'OnlyKeva=1',
        f'ClientName={_q(full_name)}',
        f'Avour={_q(avour)}', 'AvourLock=1',
        f'Redirect={_q(redirect_url)}',
    ]
    if phone:
        params.append(f'Phone={_q(phone)}')
    if email:
        params.append(f'Email={_q(email)}')
    if street:
        params.append(f'Street={_q(street)}')
    if city:
        params.append(f'City={_q(city)}')
    if groupe:
        params.append(f'Groupe={_q(groupe)}&GroupeLock=1')
    if language:
        params.append(f'Language={_q(language)}')
    return f'{PAYMENT_PAGE_BASE}?{"&".join(params)}'


def to_number(value):
    """Nedarim Plus sometimes returns a numeric-looking value as a string
    with thousands-separator commas (e.g. "1,200") -- confirmed behavior
    in the ported system. Returns a float, or None if truly unparseable
    (never raises -- every caller treats an unparseable amount as 'use
    the fallback/expected amount instead', never as a hard error)."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return value
    text = str(value).strip().replace(',', '')
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


_ASPNET_DATE_RE = re.compile(r'/Date\((-?\d+)\)/')
_DMY_RE = re.compile(r'^(\d{1,2})/(\d{1,2})/(\d{2,4})$')


def parse_nedarim_date(value):
    """Nedarim Plus has been confirmed, across different endpoints, to
    return a date in any of FOUR different encodings. Never trusts JS/
    Python's locale-sensitive MM/DD parsing for the slash form -- that
    would silently swap day and month for anything past the 12th.
    1. ASP.NET AJAX wrapper: '/Date(1700000000000)/' (milliseconds since
       epoch).
    2. 'DD/MM/YYYY' or 'DD/MM/YY' (explicit day-first, always).
    3. A raw integer/numeric-string epoch (milliseconds).
    4. ISO 8601, as a last resort.
    Returns a naive UTC datetime, or None if nothing matched (logged by
    the caller, never raised -- a single unparseable date must never
    crash an entire sync/import batch)."""
    if value is None or value == '':
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value / 1000, tz=timezone.utc).replace(tzinfo=None)
        except (ValueError, OverflowError, OSError):
            return None
    text = str(value).strip()
    m = _ASPNET_DATE_RE.match(text)
    if m:
        try:
            return datetime.fromtimestamp(int(m.group(1)) / 1000, tz=timezone.utc).replace(tzinfo=None)
        except (ValueError, OverflowError, OSError):
            return None
    m = _DMY_RE.match(text)
    if m:
        day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if year < 100:
            year += 2000
        try:
            return datetime(year, month, day)
        except ValueError:
            return None
    if text.lstrip('-').isdigit():
        try:
            return datetime.fromtimestamp(int(text) / 1000, tz=timezone.utc).replace(tzinfo=None)
        except (ValueError, OverflowError, OSError):
            return None
    try:
        return datetime.fromisoformat(text.replace('Z', '+00:00')).replace(tzinfo=None)
    except ValueError:
        return None
