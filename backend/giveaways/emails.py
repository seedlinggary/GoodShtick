"""Giveaway participant emails -- built from the exact same shared shell as
backend/alerts/emails.py (_wrap/_button/_kicker/_section/_client), reused
directly rather than duplicating the HTML-email scaffolding."""
from html import escape

from backend.alerts.emails import _client, _wrap, _button, _kicker, _section, _footer_link, MUTED


def send_giveaway_verify_email(email, campaign_name, verify_url):
    resend, from_header = _client()
    html = _wrap(
        _kicker('Confirm your entry') +
        f'<p style="margin:0 0 4px;">You\'re almost entered in <strong>{escape(campaign_name)}</strong>.</p>'
        '<p style="margin:0;">One more step -- confirm your email to lock in your entry:</p>'
        f'{_button(verify_url, "Confirm my entry")}'
        f'<p style="margin:14px 0 0;color:{MUTED};font-size:13px;">'
        'Didn\'t enter this giveaway? Ignore this email and nothing happens.</p>',
        preheader=f'Confirm your entry in {campaign_name}',
    )
    resend.Emails.send({
        'from': from_header, 'to': [email],
        'subject': f'Confirm your entry: {campaign_name}',
        'html': html,
    })


def send_giveaway_confirmed_email(email, campaign_name, entry_count, referral_url, unsubscribe_url=None):
    resend, from_header = _client()
    unsubscribe_html = (
        f'<p style="margin:14px 0 0;">{_footer_link(unsubscribe_url, "Stop marketing emails for this giveaway")}'
        ' (this never affects your entry).</p>' if unsubscribe_url else ''
    )
    html = _wrap(
        _kicker('Entry confirmed') +
        f'<p style="margin:0 0 4px;">You\'re in! You currently have <strong>{entry_count}</strong> '
        f'{"entry" if entry_count == 1 else "entries"} in <strong>{escape(campaign_name)}</strong>.</p>' +
        _section(
            '<p style="margin:0 0 8px;font-weight:700;">Want more entries?</p>'
            '<p style="margin:0;">Share your personal link -- every friend who enters through it earns you more:</p>'
            f'<p style="margin:10px 0 0;word-break:break-all;"><a href="{escape(referral_url)}" '
            f'style="color:#15332c;font-weight:600;">{escape(referral_url)}</a></p>'
        ) +
        f'<p style="margin:14px 0 0;color:{MUTED};font-size:13px;">'
        'We\'ll email you if you win. Good luck!</p>' + unsubscribe_html,
        preheader=f'You have {entry_count} {"entry" if entry_count == 1 else "entries"} in {campaign_name}',
    )
    resend.Emails.send({
        'from': from_header, 'to': [email],
        'subject': f'You\'re entered: {campaign_name}',
        'html': html,
    })


def send_giveaway_winner_email(email, campaign_name, prize_details):
    resend, from_header = _client()
    html = _wrap(
        _kicker('You won!') +
        f'<p style="margin:0 0 4px;">Congratulations -- you\'ve been selected as the winner of '
        f'<strong>{escape(campaign_name)}</strong>!</p>' +
        (_section(f'<div style="white-space:pre-wrap;">{escape(prize_details)}</div>') if prize_details else '') +
        f'<p style="margin:14px 0 0;color:{MUTED};font-size:13px;">'
        'We\'ll be in touch at this email address with next steps.</p>',
        preheader=f'You won: {campaign_name}',
    )
    resend.Emails.send({
        'from': from_header, 'to': [email],
        'subject': f'You won! {campaign_name}',
        'html': html,
    })
