"""Stripe Connect onboarding for a business's own storefront/booking
checkout (Phase 3 of the site builder -- Phase 4/5 wire the actual
checkout sessions this unlocks). State-signing/OAuth-callback shape
mirrors backend/business/routes/social.py's exactly (same _sign_state/
_read_state/_frontend_return_url pattern) -- kept local rather than
imported to avoid a circular import between the two route modules, same
reasoning social.py itself gives for duplicating _can_manage.
"""
import os
from datetime import datetime, timedelta

import jwt as pyjwt
from flask import Blueprint, jsonify, redirect, request

from config import application, db
from security import token_required
from backend.notifications.helpers import notify
from backend.user.modals.user import User
from backend.business.modals.business import Business
from backend.business.modals.payment_account import PaymentAccount
from backend.business.modals.commerce import Order
from backend.business.payments.providers import get_payment_provider
from backend.business.payments.providers.stripe import is_configured as stripe_is_configured

payments_api = Blueprint('payments_api', __name__, url_prefix='/business')

STATE_TTL_MINUTES = 15


# TEMPORARY, prod-testing-only restriction -- see business_site.py's
# _can_manage for why (site builder is super-admin-only while testing on
# prod, not the usual is_boss-or-owner check).
def _can_manage(business, user):
    return bool(user and user.is_super_admin)


def _sign_state(payload):
    payload = {**payload, 'exp': datetime.utcnow() + timedelta(minutes=STATE_TTL_MINUTES)}
    return pyjwt.encode(payload, application.config['SECRET_KEY'], algorithm='HS256')


def _read_state(token):
    try:
        return pyjwt.decode(token, application.config['SECRET_KEY'], algorithms=['HS256'])
    except pyjwt.PyJWTError:
        return None


def _redirect_uri():
    base = os.environ.get('BACKEND_PUBLIC_URL', request.host_url.rstrip('/'))
    return f'{base}/business/payments/oauth/stripe/callback'


def _frontend_return_url(business_id, ok, message=None):
    base = os.environ.get('FRONTEND_BUSINESS_URL', 'http://localhost:3000')
    status = 'connected' if ok else 'error'
    msg = f'&message={message}' if message else ''
    return f'{base}/business/{business_id}/tools?tab=site&payments={status}{msg}'


def _serialize_account(account):
    if not account:
        return None
    return {
        'provider': account.provider,
        'status': account.status,
        'details': account.details or {},
        'connected_at': account.connected_at.isoformat() if account.connected_at else None,
    }


@payments_api.route('/businesses/<int:business_id>/payments/status', methods=['GET'])
@token_required
def payments_status(current_user, business_id):
    business = db.session.get(Business, business_id)
    if not business or not _can_manage(business, current_user):
        return jsonify({'message': 'Not authorized'}), 403
    account = PaymentAccount.query.filter_by(business_id=business_id).first()
    return jsonify({
        'account': _serialize_account(account),
        'stripe_configured': stripe_is_configured(),
    })


@payments_api.route('/businesses/<int:business_id>/payments/connect/start', methods=['POST'])
@token_required
def start_connect(current_user, business_id):
    business = db.session.get(Business, business_id)
    if not business or not _can_manage(business, current_user):
        return jsonify({'message': 'Not authorized'}), 403
    if not stripe_is_configured():
        return jsonify({'message': "Payments aren't configured on this deployment yet"}), 501

    account = PaymentAccount.query.filter_by(business_id=business_id).first()
    if not account:
        account = PaymentAccount(business_id=business_id, provider='stripe')
        db.session.add(account)
        db.session.commit()

    state = _sign_state({'business_id': business_id, 'user_id': current_user.public_id})
    provider = get_payment_provider(account)
    authorize_url = provider.get_connect_url(state, _redirect_uri())
    return jsonify({'authorize_url': authorize_url})


@payments_api.route('/businesses/<int:business_id>/payments/connect/manual', methods=['POST'])
@token_required
def manual_connect(current_user, business_id):
    """Fallback to OAuth -- paste an existing acct_... id directly. Same
    tolerance for a platform key that can't fully read an account it
    doesn't own as the reference this was ported from: the id's shape and
    Stripe actually recognizing it are what's verified, not full read
    access to the account's details."""
    business = db.session.get(Business, business_id)
    if not business or not _can_manage(business, current_user):
        return jsonify({'message': 'Not authorized'}), 403
    if not stripe_is_configured():
        return jsonify({'message': "Payments aren't configured on this deployment yet"}), 501

    account_id = ((request.get_json() or {}).get('account_id') or '').strip()
    if not account_id.startswith('acct_'):
        return jsonify({'message': "Invalid Stripe account id -- must start with 'acct_'"}), 400

    import stripe as _stripe
    _stripe.api_key = os.environ.get('STRIPE_SECRET_KEY')
    try:
        _stripe.Account.retrieve(account_id)
    except _stripe.error.PermissionError:
        pass  # a test-mode platform key can't retrieve an account it doesn't own -- the id is still valid
    except _stripe.error.InvalidRequestError:
        return jsonify({'message': 'That Stripe account could not be found'}), 400
    except Exception:  # noqa: BLE001 -- surface a clean error, never a stack trace
        return jsonify({'message': 'Could not verify that Stripe account -- try again'}), 502

    account = PaymentAccount.query.filter_by(business_id=business_id).first()
    if not account:
        account = PaymentAccount(business_id=business_id, provider='stripe')
        db.session.add(account)
    account.external_account_id = account_id
    account.status = 'active'
    account.connected_by = current_user.public_id
    account.connected_at = datetime.utcnow()
    db.session.commit()
    return jsonify(_serialize_account(account))


@payments_api.route('/payments/oauth/stripe/callback', methods=['GET'])
def stripe_oauth_callback():
    state = _read_state(request.args.get('state', ''))
    if not state:
        return redirect(_frontend_return_url(0, False, 'That connection link expired -- try again'))

    business_id = state['business_id']
    code = request.args.get('code')
    if not code:
        return redirect(_frontend_return_url(business_id, False, 'Connection was cancelled'))

    account = PaymentAccount.query.filter_by(business_id=business_id).first()
    if not account:
        return redirect(_frontend_return_url(business_id, False, 'Could not find that business'))

    provider = get_payment_provider(account)
    try:
        external_account_id = provider.exchange_code(code)
        details = provider.get_account_details(external_account_id)
    except Exception:  # noqa: BLE001 -- surface a clean redirect, never a stack trace to the browser
        return redirect(_frontend_return_url(business_id, False, 'Could not complete that connection'))

    account.external_account_id = external_account_id
    account.details = details
    account.status = 'active'
    account.connected_by = state['user_id']
    account.connected_at = datetime.utcnow()
    db.session.commit()

    return redirect(_frontend_return_url(business_id, True))


@payments_api.route('/businesses/<int:business_id>/payments/disconnect', methods=['DELETE'])
@token_required
def disconnect(current_user, business_id):
    business = db.session.get(Business, business_id)
    if not business or not _can_manage(business, current_user):
        return jsonify({'message': 'Not authorized'}), 403

    account = PaymentAccount.query.filter_by(business_id=business_id).first()
    if account:
        account.external_account_id = None
        account.details = None
        account.status = 'disabled'
        db.session.commit()
    return jsonify({'message': 'Disconnected'})


def _receipt_email_address(order):
    if order.customer_user_id:
        user = db.session.get(User, order.customer_user_id)
        return user.email if user else None
    return order.guest_email


def _send_receipt_email(business, order, pdf_bytes):
    """Best-effort, same reasoning as business_site_public.py's
    _send_contact_email -- the in-app Notification to the owner is the
    guaranteed side of this, a Resend outage here never blocks marking
    the order paid."""
    to_email = _receipt_email_address(order)
    api_key = os.environ.get('RESEND_API_KEY')
    from_addr = os.environ.get('EMAIL_FROM')
    if not to_email or not api_key or not from_addr:
        return
    try:
        import resend
        resend.api_key = api_key
        from_name = os.environ.get('EMAIL_FROM_NAME', 'Gut Shtick')
        resend.Emails.send({
            'from': f'{from_name} <{from_addr}>',
            'to': [to_email],
            'subject': f'Your receipt from {business.name}',
            'html': f'<p>Thanks for your order from {business.name}. Your receipt ({order.invoice_number}) is attached.</p>',
            'attachments': [{'filename': f'{order.invoice_number}.pdf', 'content': list(pdf_bytes)}],
        })
    except Exception:
        pass


def _mark_order_paid(session_id):
    """Idempotent on purpose -- Stripe retries webhook deliveries, so this
    must be safe to run twice for the same event. Only ever moves an order
    OUT of 'pending'; a webhook arriving late for an order a customer
    somehow already got refunded/cancelled by other means is a no-op, not
    an overwrite."""
    order = Order.query.filter_by(external_payment_id=session_id).first()
    if not order or order.status != 'pending':
        return
    order.status = 'paid'
    for item in order.items:
        if item.product and item.product.inventory_count is not None:
            item.product.inventory_count = max(0, item.product.inventory_count - item.quantity)
    if order.promo_code:
        # Only counted once a checkout actually completes, never at
        # session-creation time -- an abandoned checkout must not use up
        # a limited-use code.
        order.promo_code.redemption_count += 1

    business = db.session.get(Business, order.business_id)
    from backend.business.routes.invoices import ensure_invoice_number, build_receipt_pdf
    ensure_invoice_number(order)
    db.session.commit()

    if business and business.owner_user_id:
        notify(business.owner_user_id, f'New paid order from {order.customer_label} -- {order.total_cents / 100:.2f} {order.currency.upper()}',
               type='order_paid', link=f'/business/{business.slug}/tools')
    if business:
        try:
            pdf_bytes = build_receipt_pdf(business, order)
            _send_receipt_email(business, order, pdf_bytes)
        except Exception:
            pass  # a receipt email failure must never undo the order being marked paid

        try:
            _issue_green_invoice_document(business, order)
        except Exception:
            pass  # same convention -- a Green Invoice failure never undoes the order being marked paid

        try:
            _push_appointment_to_calendar(business, order)
        except Exception:
            pass  # same convention -- a Calendar failure never undoes the order being marked paid


def _issue_green_invoice_document(business, order):
    from backend.business.modals.green_invoice_account import GreenInvoiceAccount
    from backend.business.payments.green_invoice import create_receipt_invoice, GreenInvoiceError

    account = GreenInvoiceAccount.query.filter_by(business_id=business.id, enabled=True).first()
    if not account:
        return
    try:
        doc_id, pdf_url, _vat = create_receipt_invoice(account, order)
    except GreenInvoiceError as exc:
        account.last_error = str(exc)
        db.session.commit()
        return
    order.green_invoice_doc_id = doc_id
    order.green_invoice_pdf_url = pdf_url
    account.last_error = None
    db.session.commit()


def _push_appointment_to_calendar(business, order):
    from backend.business.modals.booking import Appointment
    from backend.business.calendar.google import push_new_appointment

    appointment = Appointment.query.filter_by(order_id=order.id).first()
    if appointment:
        push_new_appointment(business, appointment)


@payments_api.route('/payments/webhook/stripe', methods=['POST'])
def stripe_webhook():
    """Signature-verified against the RAW body -- request.get_data() must
    be read before anything else touches the request, since re-serializing
    a parsed-then-reconstructed body breaks the signature check even for a
    genuine event."""
    payload = request.get_data()
    signature = request.headers.get('Stripe-Signature', '')
    try:
        from backend.business.payments.providers.stripe import construct_webhook_event
        event = construct_webhook_event(payload, signature)
    except Exception:  # noqa: BLE001 -- invalid/unverifiable signature
        return jsonify({'message': 'Invalid signature'}), 400

    event_type = event.get('type')
    if event_type == 'checkout.session.completed':
        session = event['data']['object']
        _mark_order_paid(session['id'])

    return jsonify({'received': True, 'type': event_type})
