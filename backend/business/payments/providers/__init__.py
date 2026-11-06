"""Dispatch-by-provider-string, mirroring the reference billing app's own
get_payment_provider(therapist) pattern. Only backend.business.payments.
providers.stripe is a real implementation; the other three map to stub
modules whose functions all raise NotImplementedError -- so PICKING an
unsupported provider is never an error by itself (a business can already
be set to 'nedarim_plus' today), only actually trying to USE one is.
Adding a real implementation later means writing one new provider module
with this same function signature set and swapping it in below -- no
caller of get_payment_provider() changes."""
from backend.business.payments.providers import stripe as stripe_provider
from backend.business.payments.providers import nedarim_plus as nedarim_plus_provider
from backend.business.payments.providers import payme as payme_provider
from backend.business.payments.providers import paypal as paypal_provider

_PROVIDERS = {
    'stripe': stripe_provider,
    'nedarim_plus': nedarim_plus_provider,
    'payme': payme_provider,
    'paypal': paypal_provider,
}


def get_payment_provider(account_or_provider):
    """Takes either a PaymentAccount instance or a bare provider string."""
    provider = getattr(account_or_provider, 'provider', account_or_provider)
    module = _PROVIDERS.get(provider)
    if not module:
        raise ValueError(f'Unknown payment provider: {provider!r}')
    return module
