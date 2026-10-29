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


def send_weekly_digest_email(email, nearby_items, price_move_items, unsubscribe_url):
    """Stage 4's "Your week" digest -- `nearby_items`: [{title, subtitle,
    url}], `price_move_items`: [{message, url}] (straight from Notification
    rows). Either list can be empty; the email still sends if at least one
    of the two has something, since "nothing new" isn't worth an email."""
    resend, from_header = _client()

    def _item_li(item):
        subtitle_html = f' &mdash; {escape(item["subtitle"])}' if item.get('subtitle') else ''
        return (
            f'<li style="margin-bottom:6px;">'
            f'<a href="{escape(item["url"])}" style="color:{ACCENT};">{escape(item["title"])}</a>{subtitle_html}'
            f'</li>'
        )

    def _move_li(item):
        return (
            f'<li style="margin-bottom:6px;">'
            f'<a href="{escape(item["url"])}" style="color:{ACCENT};">{escape(item["message"])}</a>'
            f'</li>'
        )

    parts = ['<p>Your week on GUT:</p>']
    if nearby_items:
        parts.append(
            '<div style="margin:16px 0;padding:16px;background:#f2f5f2;border-radius:10px;">'
            '<p style="margin:0 0 8px;font-weight:700;">New near you</p>'
            f'<ul style="margin:0;padding-left:20px;">{"".join(_item_li(i) for i in nearby_items)}</ul>'
            '</div>'
        )
    if price_move_items:
        parts.append(
            '<div style="margin:16px 0;padding:16px;background:#f2f5f2;border-radius:10px;">'
            '<p style="margin:0 0 8px;font-weight:700;">Price moves on things you saved</p>'
            f'<ul style="margin:0;padding-left:20px;">{"".join(_move_li(i) for i in price_move_items)}</ul>'
            '</div>'
        )
    parts.append(
        f'<p style="margin-top:20px;"><a href="{unsubscribe_url}" style="color:#96a39c;font-size:12px;">'
        f'Stop getting this weekly email</a></p>'
    )
    html = _wrap(''.join(parts))

    resend.Emails.send({
        'from': from_header, 'to': [email],
        'subject': 'Your week on GUT',
        'html': html,
    })


def send_still_available_email(poster_email, item_title, confirm_url, site_name):
    """Stage 5's "Still available?" check -- one click confirms; no click
    at all is a valid, silent answer too (the item just gets hidden after
    the grace period, see check_still_available() in routes/estates.py /
    routes/tachlis_post.py)."""
    resend, from_header = _client()
    html = _wrap(
        f'<p>Is <strong>{escape(item_title)}</strong> still available on {escape(site_name)}?</p>'
        f'<p>{_button(confirm_url, "Yes, still available")}</p>'
        f'<p style="color:#5b6b63;font-size:13px;">If we don\'t hear back in a few days, it\'ll be hidden from search '
        f'so people aren\'t contacting you about something that\'s gone. You can always re-list it.</p>'
    )
    resend.Emails.send({
        'from': from_header, 'to': [poster_email],
        'subject': f'Still available? {item_title}',
        'html': html,
    })


def send_deal_alert_email(follower_email, business_name, post_title, post_body, post_url, unsubscribe_url):
    """New-deal alert -- fired from backend/business/routes/business_post.py's
    create_post() to every follower of the business that just posted
    (BusinessFollow is the opt-in gate; see that model's own docstring).
    Plain-text preview of the post body, same truncate-and-link shape as
    send_digest_email's items rather than trying to recreate DealsFeed's
    own card styling in an email."""
    resend, from_header = _client()
    preview = post_body if len(post_body) <= 300 else post_body[:300].rstrip() + '...'
    html = _wrap(
        f'<p><strong>{escape(business_name)}</strong> just posted a new deal:</p>'
        f'<div style="margin:16px 0;padding:16px;background:#f2f5f2;border-radius:10px;">'
        f'<p style="margin:0 0 8px;font-weight:700;">{escape(post_title)}</p>'
        f'<p style="margin:0;color:#5b6b63;white-space:pre-wrap;">{escape(preview)}</p>'
        f'</div>'
        f'<p>{_button(post_url, "View deal")}</p>'
        f'<p style="margin-top:20px;"><a href="{unsubscribe_url}" style="color:#96a39c;font-size:12px;">'
        f'Unfollow {escape(business_name)} to stop these emails</a></p>'
    )
    resend.Emails.send({
        'from': from_header, 'to': [follower_email],
        'subject': f'New deal from {business_name}: {post_title}',
        'html': html,
    })


def send_job_match_email(email, post, unsubscribe_url):
    """Tachlis job-match alert -- fired from
    backend/tachlis/routes/tachlis_post.py's _notify_job_match_users() to
    members whose own profile_area/line_of_work looks like a fit, even
    though they never set up a saved-search Alert for it. `post`:
    {title, location, compensation, url}. Shares User.weekly_digest_token's
    unsubscribe link (see that caller) rather than a separate token, since
    this is gated on the same weekly_digest_enabled consent."""
    resend, from_header = _client()
    subtitle = ' · '.join(b for b in (post.get('location'), post.get('compensation')) if b)
    subtitle_html = f'<p style="margin:0;color:#5b6b63;">{escape(subtitle)}</p>' if subtitle else ''
    html = _wrap(
        '<p>A new job post on Gut Money looks like a fit for you:</p>'
        f'<div style="margin:16px 0;padding:16px;background:#f2f5f2;border-radius:10px;">'
        f'<p style="margin:0 0 8px;font-weight:700;">{escape(post["title"])}</p>'
        f'{subtitle_html}'
        f'</div>'
        f'<p>{_button(post["url"], "View job")}</p>'
        f'<p style="margin-top:20px;"><a href="{unsubscribe_url}" style="color:#96a39c;font-size:12px;">'
        f'Stop getting these match emails</a></p>'
    )
    resend.Emails.send({
        'from': from_header, 'to': [email],
        'subject': f'New job match: {post["title"]}',
        'html': html,
    })


def send_job_application_email(employer_email, job_title, applicant_name, applicant_email, cv_summary, note):
    """Stage 5's "one-tap apply" -- reply_to is the applicant's own email
    (same convention as backend/contact/routes/contact.py), so the employer
    can just hit reply."""
    resend, from_header = _client()
    parts = [f'<p><strong>{escape(applicant_name)}</strong> applied to <strong>{escape(job_title)}</strong> via GUT Money\'s Job Board.</p>']
    if note:
        parts.append(f'<p>{escape(note)}</p>')
    if cv_summary:
        parts.append(f'<div style="margin-top:12px;padding:12px;background:#f2f5f2;border-radius:8px;white-space:pre-wrap;">{escape(cv_summary)}</div>')
    parts.append(f'<p style="margin-top:16px;color:#5b6b63;font-size:13px;">Reply to this email to reach {escape(applicant_name)} directly.</p>')
    html = _wrap(''.join(parts))

    resend.Emails.send({
        'from': from_header, 'to': [employer_email], 'reply_to': applicant_email,
        'subject': f'Application: {job_title}',
        'html': html,
    })
