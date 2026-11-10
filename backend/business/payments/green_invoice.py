"""Green Invoice (greeninvoice.co.il / 'morning') real document issuance for
a paid Order. Ported from a reference implementation's
services/accounting/green_invoice.py (same doc-type codes, sandbox-vs-prod
base URL, receipt-first-then-fallback logic), reimplemented with `requests`
instead of `httpx` to match this codebase's existing convention (every
other external API call here -- social/publishers.py, routes/social.py --
already uses plain `requests`, never a dedicated HTTP client).

API reference: https://www.greeninvoice.co.il/api-docs
Auth: POST /account/token {id, secret} -> {token} -- a short-lived JWT,
fetched fresh per call here rather than cached, since this platform's
order volume per business doesn't warrant the extra state.

Document type codes used here:
  400 = Receipt (קבלה)
  320 = Tax Invoice + Receipt, combined (חשבונית מס קבלה)
  330 = Credit Invoice (חשבונית זיכוי) -- Green Invoice documents are
        immutable once issued; a credit note is the only way to void one.

Unlike a pre-payment-invoice billing flow (e.g. a therapist invoicing a
client, then getting paid later), every Order on this platform is paid at
checkout with nothing issued beforehand -- so there is never an existing
invoice doc to reference. create_receipt_invoice is accordingly the only
document-creation entry point this module needs: try the plain receipt
(400) first, and only fall back to the combined tax-invoice-and-receipt
(320) if that's rejected (some Green Invoice account types can't issue a
400 at all).

VAT is assumed at Israel's standard rate (18%) for every document -- this
platform has no per-order "tax exempt" flag the way the reference's
per-client therapist billing does, so there's nothing to branch on.
"""
import os

import requests

from backend.business.social.crypto import decrypt_token

_PROD_BASE = 'https://api.greeninvoice.co.il/api/v1'
_SANDBOX_BASE = 'https://sandbox.d.greeninvoice.co.il/api/v1'
IL_VAT_RATE = 0.18
REQUEST_TIMEOUT = 30

DOCTYPE_RECEIPT = 400
DOCTYPE_RECEIPT_INVOICE = 320
DOCTYPE_CREDIT_NOTE = 330


class GreenInvoiceError(Exception):
    def __init__(self, message, raw=None):
        super().__init__(message)
        self.raw = raw


def _base_url():
    return _PROD_BASE if os.environ.get('APP_ENV') == 'production' else _SANDBOX_BASE


def _token(account):
    secret = decrypt_token(account.api_secret_enc)
    try:
        resp = requests.post(
            f'{_base_url()}/account/token',
            json={'id': account.api_key_id, 'secret': secret},
            headers={'Content-Type': 'application/json', 'Accept': 'application/json'},
            timeout=REQUEST_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise GreenInvoiceError(f'Green Invoice auth request failed: {exc}')
    if resp.status_code >= 400:
        raise GreenInvoiceError('Green Invoice rejected those credentials', raw=resp.text)
    token = resp.json().get('token')
    if not token:
        raise GreenInvoiceError('Green Invoice auth returned no token')
    return token


def _post(account, path, body):
    token = _token(account)
    try:
        resp = requests.post(
            f'{_base_url()}/{path.lstrip("/")}', json=body,
            headers={'Content-Type': 'application/json', 'Accept': 'application/json', 'Authorization': f'Bearer {token}'},
            timeout=REQUEST_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise GreenInvoiceError(f'Green Invoice request failed ({path}): {exc}')
    try:
        result = resp.json()
    except ValueError:
        raise GreenInvoiceError('Green Invoice returned a non-JSON response', raw=resp.text)
    if resp.status_code >= 400:
        raise GreenInvoiceError(result.get('description') or result.get('message') or resp.text, raw=result)
    return result


def _document_body(order, doctype):
    description = f'Order #{order.id}' + (f' -- invoice {order.invoice_number}' if order.invoice_number else '')
    amount = order.total_cents / 100
    vat_amount = round(amount * IL_VAT_RATE / (1 + IL_VAT_RATE), 2)

    body = {
        'type': doctype,
        'client': {
            'name': order.customer_label,
            'emails': [order.customer.email] if order.customer else ([order.guest_email] if order.guest_email else []),
            'add': False,
        },
        'currency': order.currency.upper(),
        'vatType': 0,  # 0 = apply the business's own default VAT handling
        'lang': 'en',
        'signed': True,
        'sendByEmail': True,
        'rounding': False,
        'income': [{
            'description': description,
            'price': amount,
            'currency': order.currency.upper(),
            'quantity': 1,
            'vatType': 1,  # price already includes VAT
        }],
    }
    if doctype in (DOCTYPE_RECEIPT, DOCTYPE_RECEIPT_INVOICE):
        body['payment'] = [{'type': 4, 'price': amount, 'currency': order.currency.upper()}]  # 4 = bank transfer/online, collected externally via Stripe
    return body, vat_amount


def create_receipt_invoice(account, order):
    """The one document-creation entry point this platform needs (see
    module docstring) -- returns (doc_id, pdf_url, vat_amount) or raises
    GreenInvoiceError. Caller (routes/payments.py's _mark_order_paid)
    catches and logs; a failure here never blocks the order being marked
    paid."""
    body, vat_amount = _document_body(order, DOCTYPE_RECEIPT)
    try:
        result = _post(account, '/documents', body)
    except GreenInvoiceError:
        body, vat_amount = _document_body(order, DOCTYPE_RECEIPT_INVOICE)
        result = _post(account, '/documents', body)
    doc_id = str(result.get('id', ''))
    pdf_url = (result.get('url') or {}).get('origin')
    return doc_id, pdf_url, vat_amount


def create_credit_note(account, original_doc_id):
    """Issues a credit note (330) linked to an already-issued document --
    Green Invoice has no endpoint to cancel/void a document directly."""
    body = {
        'type': DOCTYPE_CREDIT_NOTE,
        'client': {'add': False},
        'currency': 'ILS',
        'lang': 'en',
        'signed': True,
        'rounding': False,
        'linkedDocumentIds': [original_doc_id],
    }
    result = _post(account, '/documents', body)
    doc_id = str(result.get('id', ''))
    pdf_url = (result.get('url') or {}).get('origin')
    return doc_id, pdf_url


def validate_credentials(account):
    """Used by the "Test connection" button -- raises GreenInvoiceError on
    bad credentials, returns nothing on success."""
    _token(account)
