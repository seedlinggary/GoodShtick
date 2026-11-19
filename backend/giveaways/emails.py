"""Giveaway participant emails -- built from the exact same shared shell as
backend/alerts/emails.py (_wrap/_button/_kicker/_section/_client), reused
directly rather than duplicating the HTML-email scaffolding."""
from html import escape
from urllib.parse import quote

from backend.alerts.emails import _client, _wrap, _button, _kicker, _section, _footer_link, MUTED, ACCENT


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


def send_giveaway_confirmed_email(email, campaign_name, entry_count, referral_url, unsubscribe_url=None,
                                   my_giveaways_url=None):
    """The one email most entrants will actually read start to finish, so
    it leads with a big, celebratory "Thank You!" rather than a dry
    "entry confirmed" line, then immediately hands them the one thing
    that gets them more entries -- their referral link -- with one-tap
    share buttons for WhatsApp and Facebook (both support a real web
    share-intent URL) plus a plain instruction for Instagram, which has
    no equivalent link-based intent and has to be a manual "paste this"
    step."""
    resend, from_header = _client()
    share_text = f"I just entered to win {campaign_name} -- you can too!"
    whatsapp_url = f'https://wa.me/?text={quote(share_text + " " + referral_url)}'
    facebook_url = f'https://www.facebook.com/sharer/sharer.php?u={quote(referral_url)}'

    my_giveaways_html = (
        f'<p style="margin:14px 0 0;">Log in to Gut Shtick with <strong>this email address</strong> and head to '
        f'{_footer_link(my_giveaways_url, "My Giveaways")} in your profile to see your live entry count, exactly '
        'who\'s signed up through your link so far, and your referral clicks.</p>'
        if my_giveaways_url else ''
    )
    unsubscribe_html = (
        f'<p style="margin:10px 0 0;">{_footer_link(unsubscribe_url, "Stop marketing emails for this giveaway")}'
        ' (this never affects your entry).</p>' if unsubscribe_url else ''
    )

    html = _wrap(
        f'<h1 style="margin:0 0 10px;font-size:30px;font-weight:800;color:{ACCENT};">Thank You! 🎉</h1>'
        f'<p style="margin:0 0 4px;font-size:15px;">You\'re officially entered in '
        f'<strong>{escape(campaign_name)}</strong> with <strong>{entry_count}</strong> '
        f'{"entry" if entry_count == 1 else "entries"} so far.</p>' +
        _section(
            '<p style="margin:0 0 8px;font-weight:700;">Want to win? Get active!</p>'
            '<p style="margin:0 0 10px;">Every friend who enters through YOUR link adds to your entries -- '
            'the more you share, the better your odds. Here\'s your personal link:</p>'
            f'<p style="margin:0 0 14px;word-break:break-all;background:#fff;border-radius:8px;padding:10px 12px;">'
            f'<a href="{escape(referral_url)}" style="color:{ACCENT};font-weight:600;">{escape(referral_url)}</a></p>'
            '<p style="margin:0 0 10px;font-weight:700;">Share it the fun way:</p>'
            '<table role="presentation" cellpadding="0" cellspacing="0"><tr>'
            f'<td style="padding-right:8px;"><a href="{whatsapp_url}" '
            'style="display:inline-block;padding:9px 16px;border-radius:7px;background:#25D366;color:#fff;'
            'text-decoration:none;font-weight:600;font-size:13.5px;">WhatsApp</a></td>'
            f'<td><a href="{facebook_url}" '
            'style="display:inline-block;padding:9px 16px;border-radius:7px;background:#1877F2;color:#fff;'
            'text-decoration:none;font-weight:600;font-size:13.5px;">Facebook</a></td>'
            '</tr></table>'
            f'<p style="margin:12px 0 0;font-size:13px;color:{MUTED};">On Instagram: paste your link into your '
            'Story or your bio, then post about it -- Instagram doesn\'t allow direct share links like WhatsApp '
            'and Facebook do.</p>'
            '<p style="margin:10px 0 0;font-size:13px;color:#8a6d00;">💡 Posting your link to your WhatsApp '
            'Status reaches everyone in your contacts at once -- one of the fastest ways to rack up entries.</p>'
        ) +
        my_giveaways_html +
        f'<p style="margin:14px 0 0;color:{MUTED};font-size:13px;">'
        'We\'ll email you at this address if you win. Good luck!</p>' + unsubscribe_html,
        preheader=f'Thank you! You have {entry_count} {"entry" if entry_count == 1 else "entries"} in {campaign_name}',
    )
    resend.Emails.send({
        'from': from_header, 'to': [email],
        'subject': f'🎉 Thank you for entering {campaign_name}!',
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
