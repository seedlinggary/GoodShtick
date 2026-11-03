"""Alert emails -- sends via Resend, same pattern as backend/contact/routes/
contact.py (the only other place this project sends real email). Kept
separate from routes/alert.py so the matching/digest logic there isn't
tangled up with HTML string-building.

Styling lives entirely in _wrap()/_button()/_kicker()/_section() below --
every email in this file is built from those four pieces, so the whole
family's look (logo, card, spacing, footer) stays consistent as one thing
to maintain rather than N near-duplicated templates."""
import os
from html import escape

SITE_NAMES = {'estates': 'Gut Estates', 'tachlis': 'Gut Money'}

MAIN_SITE_URL = os.environ.get('MAIN_SITE_URL', 'https://www.gutshtick.com')
LOGO_URL = f'{MAIN_SITE_URL}/logo192.png'

# Brand palette for outbound email specifically -- deliberately its own
# small set of constants (not imported from the frontend's CSS variables,
# which an email client can't read anyway) since this is the one neutral
# "GUT" identity shown regardless of which site (Estates/Money/etc.) the
# alert itself came from.
ACCENT = '#15332c'
ACCENT_SOFT = '#eef3f0'
BORDER = '#e5e1d6'
PAGE_BG = '#f4f1ea'
TEXT = '#1f2a26'
MUTED = '#5b6b63'
FAINT = '#96a39c'
FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"


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
        '<table role="presentation" cellpadding="0" cellspacing="0" style="margin:20px 0 4px;">'
        f'<tr><td style="border-radius:9px;background:{ACCENT};">'
        f'<a href="{url}" style="display:inline-block;padding:13px 28px;color:#ffffff;text-decoration:none;'
        f'font-weight:600;font-size:14.5px;font-family:{FONT};border-radius:9px;">{text}</a>'
        '</td></tr></table>'
    )


def _kicker(text):
    """Small uppercase eyebrow label above an email's main line -- same
    "kicker" pattern the site itself uses above a page title (e.g.
    est-masthead-kicker), so an email reads as the same product, not a
    generic transactional template bolted on afterward."""
    return (
        f'<p style="margin:0 0 14px;font-size:11px;font-weight:700;text-transform:uppercase;'
        f'letter-spacing:0.08em;color:{ACCENT};">{escape(text)}</p>'
    )


def _section(inner_html):
    """A single bordered, tinted block -- used for a list of matches, a
    quoted post preview, etc. One consistent "card within the card" shape
    instead of each email function inventing its own."""
    return (
        f'<div style="margin:18px 0;padding:16px 18px;background:{ACCENT_SOFT};'
        f'border:1px solid {BORDER};border-radius:10px;">{inner_html}</div>'
    )


def _footer_link(url, text):
    return f'<a href="{url}" style="color:{FAINT};text-decoration:underline;">{text}</a>'


def _wrap(inner_html, preheader=''):
    """The shared shell every email in this file renders inside: a muted
    page background, a centered logo/wordmark, one white card holding the
    actual message plus a signed closing line, and a quiet footer -- built
    with <table> for the layout skeleton since that's what renders
    predictably across Outlook/older email clients, not just modern webmail.
    `preheader` is the one-line preview text shown next to the subject in
    an inbox list (Gmail/Apple Mail etc.) -- hidden in the body itself via
    zero height/opacity, same standard email trick everywhere else uses."""
    preheader_html = (
        f'<div style="display:none;max-height:0;overflow:hidden;opacity:0;mso-hide:all;">{escape(preheader)}</div>'
        if preheader else ''
    )
    return (
        f'{preheader_html}'
        f'<div style="background:{PAGE_BG};padding:36px 16px;font-family:{FONT};">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:520px;margin:0 auto;">'
        '<tr><td style="padding-bottom:22px;text-align:center;">'
        f'<img src="{LOGO_URL}" width="40" height="40" alt="GUT" style="border-radius:50%;vertical-align:middle;">'
        f'<span style="display:inline-block;vertical-align:middle;margin-left:10px;font-size:19px;'
        f'font-weight:700;color:{ACCENT};letter-spacing:0.01em;">GUT</span>'
        '</td></tr>'
        f'<tr><td style="background:#ffffff;border:1px solid {BORDER};border-radius:14px;'
        'padding:34px 32px;">'
        f'<div style="color:{TEXT};font-size:14.5px;line-height:1.65;">{inner_html}</div>'
        f'<p style="margin:28px 0 0;padding-top:18px;border-top:1px solid {BORDER};'
        f'color:{MUTED};font-size:13px;">Respectfully,<br>The GUT Team</p>'
        '</td></tr>'
        '<tr><td style="padding-top:20px;text-align:center;">'
        f'<p style="margin:0;color:{FAINT};font-size:11.5px;">'
        f'You\'re receiving this because of activity on a GUT site &middot; {_footer_link(MAIN_SITE_URL, "gutshtick.com")}'
        '</p>'
        '</td></tr>'
        '</table>'
        '</div>'
    )


def send_confirmation_email(alert, confirm_url):
    resend, from_header = _client()
    site = SITE_NAMES.get(alert.search_type, 'GUT')
    label = escape(alert.label or 'your search')
    html = _wrap(
        _kicker('Confirm your alert') +
        f'<p style="margin:0 0 4px;">You asked to get alerts for <strong>{label}</strong> on {site}.</p>'
        '<p style="margin:0;">One more step -- nothing is sent until you confirm:</p>'
        f'{_button(confirm_url, "Confirm this alert")}'
        f'<p style="margin:14px 0 0;color:{MUTED};font-size:13px;">'
        'Didn\'t ask for this? Ignore this email and nothing happens -- the alert stays unconfirmed and nothing is ever sent.</p>',
        preheader=f'Confirm your {site} alert for {alert.label or "your search"}',
    )
    resend.Emails.send({
        'from': from_header, 'to': [alert.email],
        'subject': f'Confirm your {site} alert',
        'html': html,
    })


def send_guest_submission_email(email, content_label, title, manage_url):
    """Sent once, at guest-submission time, for any no-account post across
    the site (a job, a listing, a business, a comment, ...) -- `content_label`
    is a short human phrase like "your job post" or "your Estates listing",
    kept generic/parameterized rather than one near-identical function per
    content type. `manage_url` is the one-time private link (see
    backend/guest/modals/guest_throttle.py's sibling token-generation
    convention, duplicated per domain the same way still_available_token
    already is) that lets the poster check status/edit/renew without ever
    needing an account -- same "the link IS the credential" shape as
    send_still_available_email's confirm_url below."""
    resend, from_header = _client()
    html = _wrap(
        _kicker('Pending review') +
        f'<p style="margin:0 0 4px;">Thanks for posting {escape(content_label)} -- <strong>{escape(title)}</strong>.</p>'
        '<p style="margin:0;">It\'s in for review now; you\'ll see it go live once approved.</p>'
        f'{_button(manage_url, "Manage your post")}'
        f'<p style="margin:14px 0 0;color:{MUTED};font-size:13px;">'
        'Keep this link -- it\'s the only way to edit, renew, or take down this post later, since no account was '
        'created. Didn\'t post this? Ignore this email.</p>',
        preheader=f'"{title}" is in for review',
    )
    resend.Emails.send({
        'from': from_header, 'to': [email],
        'subject': f'Your post is pending review: {title}',
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
            f'<li style="margin-bottom:7px;">'
            f'<a href="{escape(item["url"])}" style="color:{ACCENT};font-weight:600;text-decoration:none;">{escape(item["title"])}</a>'
            f'<span style="color:{MUTED};">{subtitle_html}</span>'
            '</li>'
        )

    parts = [
        _kicker('New matches') +
        f'<p style="margin:0;">{total} new match{"es" if total != 1 else ""} since your last update:</p>'
    ]
    for s in sections:
        items_html = ''.join(_item_li(it) for it in s['items'])
        parts.append(_section(
            f'<p style="margin:0 0 10px;font-weight:700;">{escape(s["label"])} '
            f'<span style="font-weight:400;color:{MUTED};">on {s["site_name"]}</span></p>'
            f'<ul style="margin:0;padding-left:20px;">{items_html}</ul>'
            f'<p style="margin:12px 0 0;">{_footer_link(s["unsubscribe_url"], "Unsubscribe from this alert")}</p>'
        ))
    html = _wrap(''.join(parts), preheader=f'{total} new match{"es" if total != 1 else ""} waiting for you')

    resend.Emails.send({
        'from': from_header, 'to': [email],
        'subject': f'{total} new match{"es" if total != 1 else ""} on GUT',
        'html': html,
    })


def send_weekly_digest_email(email, nearby_items, price_move_items, unsubscribe_url, detected_move=None):
    """Stage 4's "Your week" digest -- `nearby_items`: [{title, subtitle,
    url}], `price_move_items`: [{message, url}] (straight from Notification
    rows). Either list can be empty; the email still sends if at least one
    of the two has something, since "nothing new" isn't worth an email.

    `detected_move`: optional {city, jobs, businesses} from
    backend/alerts/routes/alert.py's _detected_move_for_user -- the passive
    "moving to a new area" section, `jobs`/`businesses` each shaped like
    `nearby_items`. None (the default) skips the section entirely, same as
    an empty nearby_items/price_move_items list skips those."""
    resend, from_header = _client()

    def _item_li(item):
        subtitle_html = f' &mdash; {escape(item["subtitle"])}' if item.get('subtitle') else ''
        return (
            f'<li style="margin-bottom:7px;">'
            f'<a href="{escape(item["url"])}" style="color:{ACCENT};font-weight:600;text-decoration:none;">{escape(item["title"])}</a>'
            f'<span style="color:{MUTED};">{subtitle_html}</span>'
            '</li>'
        )

    def _move_li(item):
        return (
            f'<li style="margin-bottom:7px;">'
            f'<a href="{escape(item["url"])}" style="color:{ACCENT};font-weight:600;text-decoration:none;">{escape(item["message"])}</a>'
            '</li>'
        )

    parts = [_kicker('Your week on GUT')]
    if nearby_items:
        parts.append(_section(
            '<p style="margin:0 0 10px;font-weight:700;">New near you</p>'
            f'<ul style="margin:0;padding-left:20px;">{"".join(_item_li(i) for i in nearby_items)}</ul>'
        ))
    if price_move_items:
        parts.append(_section(
            '<p style="margin:0 0 10px;font-weight:700;">Price moves on things you saved</p>'
            f'<ul style="margin:0;padding-left:20px;">{"".join(_move_li(i) for i in price_move_items)}</ul>'
        ))
    if detected_move and (detected_move.get('jobs') or detected_move.get('businesses')):
        city = escape(detected_move['city'])
        sub_sections = []
        if detected_move.get('jobs'):
            sub_sections.append(
                '<p style="margin:14px 0 8px;font-weight:600;">Jobs there</p>'
                f'<ul style="margin:0;padding-left:20px;">{"".join(_item_li(i) for i in detected_move["jobs"])}</ul>'
            )
        if detected_move.get('businesses'):
            sub_sections.append(
                '<p style="margin:14px 0 8px;font-weight:600;">Local essentials</p>'
                f'<ul style="margin:0;padding-left:20px;">{"".join(_item_li(i) for i in detected_move["businesses"])}</ul>'
            )
        parts.append(_section(
            f'<p style="margin:0;font-weight:700;">Looks like you might be exploring {city} &mdash; here\'s what\'s there</p>'
            f'{"".join(sub_sections)}'
        ))
    parts.append(f'<p style="margin:16px 0 0;">{_footer_link(unsubscribe_url, "Stop getting this weekly email")}</p>')
    html = _wrap(''.join(parts), preheader='Your week on GUT')

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
        _kicker('Quick check') +
        f'<p style="margin:0;">Is <strong>{escape(item_title)}</strong> still available on {escape(site_name)}?</p>'
        f'{_button(confirm_url, "Yes, still available")}'
        f'<p style="margin:14px 0 0;color:{MUTED};font-size:13px;">'
        'If we don\'t hear back in a few days, it\'ll be hidden from search so people aren\'t contacting you about '
        'something that\'s gone. You can always re-list it.</p>',
        preheader=f'Is "{item_title}" still available?',
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
        _kicker('New deal') +
        f'<p style="margin:0;"><strong>{escape(business_name)}</strong> just posted a new deal:</p>' +
        _section(
            f'<p style="margin:0 0 8px;font-weight:700;">{escape(post_title)}</p>'
            f'<p style="margin:0;color:{MUTED};white-space:pre-wrap;">{escape(preview)}</p>'
        ) +
        f'{_button(post_url, "View deal")}'
        f'<p style="margin:14px 0 0;">{_footer_link(unsubscribe_url, f"Unfollow {escape(business_name)} to stop these emails")}</p>',
        preheader=f'{business_name}: {post_title}',
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
    subtitle_html = f'<p style="margin:0;color:{MUTED};">{escape(subtitle)}</p>' if subtitle else ''
    html = _wrap(
        _kicker('Job match') +
        '<p style="margin:0;">A new job post on Gut Money looks like a fit for you:</p>' +
        _section(
            f'<p style="margin:0 0 8px;font-weight:700;">{escape(post["title"])}</p>'
            f'{subtitle_html}'
        ) +
        f'{_button(post["url"], "View job")}'
        f'<p style="margin:14px 0 0;">{_footer_link(unsubscribe_url, "Stop getting these match emails")}</p>',
        preheader=post['title'],
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
    parts = [
        _kicker('New application') +
        f'<p style="margin:0;"><strong>{escape(applicant_name)}</strong> applied to <strong>{escape(job_title)}</strong> via GUT Money\'s Job Board.</p>'
    ]
    if note:
        parts.append(f'<p style="margin:14px 0 0;">{escape(note)}</p>')
    if cv_summary:
        parts.append(_section(f'<div style="white-space:pre-wrap;">{escape(cv_summary)}</div>'))
    parts.append(f'<p style="margin:14px 0 0;color:{MUTED};font-size:13px;">Reply to this email to reach {escape(applicant_name)} directly.</p>')
    html = _wrap(''.join(parts), preheader=f'{applicant_name} applied to {job_title}')

    resend.Emails.send({
        'from': from_header, 'to': [employer_email], 'reply_to': applicant_email,
        'subject': f'Application: {job_title}',
        'html': html,
    })
