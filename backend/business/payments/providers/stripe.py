"""Stripe Connect -- the only real implementation of this package's
provider interface today. Standard Connect OAuth: a business links their
OWN Stripe account, we charge it directly (stripe_account=<id>) with this
platform's own secret key, skimming a fee via application_fee_amount --
the money lands in the business's account, never ours first.

Ported from the shape of a separate reference app's stripe_service.py
(FastAPI, different codebase) with one deliberate addition that reference
didn't have: application_fee_amount, since taking a platform cut is the
whole point of using Connect here.
"""
import os
from urllib.parse import urlencode

import stripe as _stripe

OAUTH_AUTHORIZE_URL = 'https://connect.stripe.com/oauth/authorize'


def _api_key():
    return os.environ.get('STRIPE_SECRET_KEY')


def is_configured():
    return bool(_api_key() and os.environ.get('STRIPE_CLIENT_ID'))


def get_connect_url(state, redirect_uri):
    """Where to send the owner to link their Stripe account. scope=
    read_write is Standard Connect (they keep full control of their own
    account, same as logging into Stripe directly) -- not Express/Custom,
    which would make US responsible for their onboarding/compliance."""
    params = {
        'response_type': 'code',
        'client_id': os.environ.get('STRIPE_CLIENT_ID'),
        'scope': 'read_write',
        'redirect_uri': redirect_uri,
        'state': state,
    }
    return f'{OAUTH_AUTHORIZE_URL}?{urlencode(params)}'


def exchange_code(code):
    """Returns the connected account id, or raises stripe.error.StripeError
    on failure. Deliberately discards the access/refresh token the OAuth
    response also includes -- see PaymentAccount's own docstring for why
    nothing here needs to persist a credential at all."""
    _stripe.api_key = _api_key()
    resp = _stripe.OAuth.token(grant_type='authorization_code', code=code)
    return resp['stripe_user_id']


def get_account_details(account_id):
    """Non-secret display metadata -- fetched with the PLATFORM's own key
    directly against the connected account id (no token needed for this
    call on a Connect account)."""
    _stripe.api_key = _api_key()
    account = _stripe.Account.retrieve(account_id)
    return {
        'charges_enabled': account.get('charges_enabled'),
        'payouts_enabled': account.get('payouts_enabled'),
        'business_name': (account.get('business_profile') or {}).get('name'),
        'email': account.get('email'),
        'country': account.get('country'),
    }


def create_checkout_session(account, line_items, currency, success_url, cancel_url,
                             platform_fee_cents=0, metadata=None, discount_cents=0):
    """A direct charge on the connected account -- stripe_account=<id>
    alongside the PLATFORM's own secret key, no access token involved.
    Money settles directly to the business; application_fee_amount is
    this platform's cut, transferred out automatically by Stripe.

    line_items: [{name, unit_amount_cents, quantity}, ...] -- a real cart,
    not a single combined line, so the Stripe checkout page itself shows
    the customer exactly what they're buying.

    discount_cents (a PromoCode's effect, already computed server-side in
    business_site_public.py): Stripe Checkout line items can't carry a
    negative amount, so a promo code is applied as a one-off Coupon
    instead -- created fresh per checkout (duration='once', never reused)
    on the CONNECTED account, same as the line items themselves."""
    _stripe.api_key = _api_key()
    kwargs = dict(
        mode='payment',
        line_items=[{
            'price_data': {
                'currency': currency,
                'unit_amount': item['unit_amount_cents'],
                'product_data': {'name': item['name']},
            },
            'quantity': item['quantity'],
        } for item in line_items],
        payment_intent_data={
            'application_fee_amount': platform_fee_cents,
            'metadata': metadata or {},
        },
        success_url=success_url,
        cancel_url=cancel_url,
        stripe_account=account.external_account_id,
    )
    if discount_cents:
        coupon = _stripe.Coupon.create(
            amount_off=discount_cents, currency=currency, duration='once',
            stripe_account=account.external_account_id,
        )
        kwargs['discounts'] = [{'coupon': coupon.id}]
    return _stripe.checkout.Session.create(**kwargs)


def construct_webhook_event(payload, signature):
    """Verifies against the RAW request body -- caller must pass
    request.get_data(), never a re-serialized/parsed body, or the
    signature check fails even for a legitimate event."""
    _stripe.api_key = _api_key()
    return _stripe.Webhook.construct_event(payload, signature, os.environ.get('STRIPE_WEBHOOK_SECRET'))
