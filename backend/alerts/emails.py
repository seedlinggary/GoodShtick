"""Alert emails -- sends via Resend, same pattern as backend/contact/routes/
contact.py (the only other place this project sends real email). Kept
separate from routes/alert.py so the matching/digest logic there isn't
tangled up with HTML string-building."""
import os
from html import escape

SITE_NAMES = {'estates': 'Gut Estates', 'tachlis': 'Gut Money'}
ACCENT = '#15332c'


def _client():
    api_key = os.environ.get('RESEND_API_KEY')
    from_addr = os.environ.get('EMAIL_FROM')
    if not api_key or not from_addr:
        raise RuntimeError('Email is not configured on the server.')
    import resend  # lazy -- same reasoning as contact.py: don't fail module import if the package/key is missing
    resend.api_key = api_key
    from_name = os.environ.get('EMAIL_FROM_NAME', 'Gut Shtick')
    return resend, f'{from_name} <{from_addr}>'


def _button(url, text):
    return (
        f'<a href="{url}" style="display:inline-block;background:{ACCENT};color:#fff;'
        f'text-decoration:none;padding:10px 20px;border-radius:8px;font-weight:600;'
        f'font-family:sans-serif;font-size:14px;">{text}</a>'
    )


def _wrap(inner_html):
    return (
        '<div style="font-family:sans-serif;color:#182420;max-width:480px;margin:0 auto;">'
        f'{inner_html}'
        '<p style="color:#96a39c;font-size:12px;margin-top:32px;">GUT -- gutshtick.com</p>'
        '</div>'
    )


def send_confirmation_email(alert, confirm_url):
    resend, from_header = _client()
    site = SITE_NAMES.get(alert.search_type, 'GUT')
    label = escape(alert.label or 'your search')
    html = _wrap(
        f'<p>You asked to get alerts for <strong>{label}</strong> on {site}.</p>'
        f'<p>One more step -- nothing is sent until you confirm:</p>'
        f'<p>{_button(confirm_url, "Confirm this alert")}</p>'
        f'<p style="color:#5b6b63;font-size:13px;">Didn\'t ask for this? Ignore this email and nothing happens -- the alert stays unconfirmed and nothing is ever sent.</p>'
    )
    resend.Emails.send({
        'from': from_header, 'to': [alert.email],
        'subject': f'Confirm your {site} alert',
        'html': html,
    })


def send_digest_email(email, sections):
    """`sections`: [{alert, site_name, items: [{title, subtitle, url}], unsubscribe_url}, ...]
    -- one section per alert that found a new match, combined into ONE email
    per person (never one email per alert) per Stage 3's own requirement."""
    resend, from_header = _client()
    total = sum(len(s['items']) for s in sections)

    def _item_li(item):
        subtitle_html = f' &mdash; {escape(item["subtitle"])}' if item.get('subtitle') else ''
        return (
            f'<li style="margin-bottom:6px;">'
            f'<a href="{escape(item["url"])}" style="color:{ACCENT};">{escape(item["title"])}</a>{subtitle_html}'
            f'</li>'
        )

    parts = [f'<p>{total} new match{"es" if total != 1 else ""} since your last update:</p>']
    for s in sections:
        items_html = ''.join(_item_li(it) for it in s['items'])
        parts.append(
            f'<div style="margin:20px 0;padding:16px;background:#f2f5f2;border-radius:10px;">'
            f'<p style="margin:0 0 8px;font-weight:700;">{escape(s["label"])} <span style="font-weight:400;color:#5b6b63;">on {s["site_name"]}</span></p>'
            f'<ul style="margin:0;padding-left:20px;">{items_html}</ul>'
            f'<p style="margin:10px 0 0;"><a href="{s["unsubscribe_url"]}" style="color:#96a39c;font-size:12px;">Unsubscribe from this alert</a></p>'
            f'</div>'
        )
    html = _wrap(''.join(parts))

    resend.Emails.send({
        'from': from_header, 'to': [email],
        'subject': f'{total} new match{"es" if total != 1 else ""} on GUT',
        'html': html,
    })
