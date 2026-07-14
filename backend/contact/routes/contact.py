"""Contact form -- sends via Resend.

Previously Contact.js just built a mailto: link (no backend route existed at
all, and nothing ever sent server-side email in this project -- Flask-Mail
was configured but never invoked). This is a real backend endpoint now.
"""
import os
import re

from flask import Blueprint, jsonify, request

contact_api = Blueprint('contact_api', __name__, url_prefix='/contact')

# The public-facing contact identity shown across the site (Contact.js,
# Disclaimer.js, ContentGuidelines.js) -- this is where messages land.
RECIPIENT = 'orders@kolstock.com'

NAME_MAX = 100
EMAIL_MAX = 200
MESSAGE_MAX = 5000
_EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


@contact_api.route('', methods=['POST'])
def send_contact_message():
    body = request.get_json(silent=True) or {}
    name = (body.get('name') or '').strip()
    email = (body.get('email') or '').strip()
    message = (body.get('message') or '').strip()

    if not name or not email or not message:
        return jsonify({'message': 'Name, email, and message are all required.'}), 400
    if not _EMAIL_RE.match(email):
        return jsonify({'message': 'Please enter a valid email address.'}), 400
    if len(name) > NAME_MAX or len(email) > EMAIL_MAX or len(message) > MESSAGE_MAX:
        return jsonify({'message': 'One of the fields is too long.'}), 400

    api_key = os.environ.get('RESEND_API_KEY')
    if not api_key:
        return jsonify({'message': 'Email is not configured on the server.'}), 500

    # Imported lazily so the module still imports cleanly even if the resend
    # package or key is missing in some environment -- only this route needs it.
    import resend
    resend.api_key = api_key

    from_name = os.environ.get('EMAIL_FROM_NAME', 'Gut Shtick')
    from_addr = os.environ.get('EMAIL_FROM')
    if not from_addr:
        return jsonify({'message': 'Email is not configured on the server.'}), 500

    try:
        resend.Emails.send({
            'from': f'{from_name} <{from_addr}>',
            'to': [RECIPIENT],
            'reply_to': email,
            'subject': f'Contact form: {name}',
            'html': (
                f'<p><strong>From:</strong> {name} ({email})</p>'
                f'<p style="white-space: pre-wrap;">{message}</p>'
            ),
        })
    except Exception as exc:  # noqa: BLE001 -- surface a clean error, don't leak internals
        return jsonify({'message': f'Failed to send: {exc}'}), 502

    return jsonify({'message': 'Message sent.'})
