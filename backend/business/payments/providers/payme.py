"""PayMe -- not implemented yet. Exists purely so PaymentAccount.provider
can already be set to 'payme' without this package's dispatch shape
(get_payment_provider() in __init__.py) needing to change once it is."""

_NOT_IMPLEMENTED = 'PayMe is not supported yet for storefront checkout'


def is_configured():
    return False


def get_connect_url(state, redirect_uri):
    raise NotImplementedError(_NOT_IMPLEMENTED)


def exchange_code(code):
    raise NotImplementedError(_NOT_IMPLEMENTED)


def get_account_details(account_id):
    raise NotImplementedError(_NOT_IMPLEMENTED)


def create_checkout_session(account, line_items, currency, success_url, cancel_url,
                             platform_fee_cents=0, metadata=None, discount_cents=0):
    raise NotImplementedError(_NOT_IMPLEMENTED)


def construct_webhook_event(payload, signature):
    raise NotImplementedError(_NOT_IMPLEMENTED)
