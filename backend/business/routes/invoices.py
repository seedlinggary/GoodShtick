"""PDF receipts + the invoice list (Phase 6 of the site builder). Builds
straight off Order/OrderItem -- see commerce.py's Order.invoice_number
docstring for why there's no separate Invoice table duplicating data an
Order already holds. Uses reportlab's Platypus (same library already in
requirements.txt for backend/torah/export.py, same io.BytesIO + send_file
pattern that file's own PDF route uses), not a new PDF dependency.
"""
import io
import secrets
from datetime import datetime

from flask import Blueprint, jsonify, request, send_file
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

from config import db
from security import token_required
from backend.business.modals.business import Business
from backend.business.modals.commerce import Order
from backend.business.modals.green_invoice_account import GreenInvoiceAccount
from backend.business.payments.green_invoice import create_credit_note, validate_credentials, GreenInvoiceError
from backend.business.social.crypto import encrypt_token

invoices_api = Blueprint('invoices_api', __name__, url_prefix='/business')

INVOICEABLE_STATUSES = ('paid', 'fulfilled', 'refunded')


# TEMPORARY, prod-testing-only restriction -- see business_site.py's
# _can_manage for why (site builder is super-admin-only while testing on
# prod, not the usual is_boss-or-owner check).
def _can_manage(business, user):
    return bool(user and user.is_super_admin)


def _owned_business_or_error(business_id, user):
    business = db.session.get(Business, business_id)
    if not business:
        return None, (jsonify({'message': 'Business not found'}), 404)
    if not _can_manage(business, user):
        return None, (jsonify({'message': 'Not authorized'}), 403)
    return business, None


def ensure_invoice_number(order):
    """Assigns one the first time an order becomes invoiceable; never
    reassigns after. Callers must still db.session.commit()."""
    if order.invoice_number:
        return order.invoice_number
    order.invoice_number = f'INV-{order.business_id:04d}-{order.id:06d}-{secrets.token_hex(2).upper()}'
    return order.invoice_number


def build_receipt_pdf(business, order):
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, topMargin=0.75 * inch, bottomMargin=0.75 * inch,
                             leftMargin=0.75 * inch, rightMargin=0.75 * inch)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('Title', parent=styles['Title'], alignment=0, fontSize=20)
    muted_style = ParagraphStyle('Muted', parent=styles['Normal'], textColor=colors.HexColor('#6b5f53'))

    story = [
        Paragraph(business.name, title_style),
        Paragraph('Receipt', muted_style),
        Spacer(1, 16),
        Paragraph(f"Invoice #: {order.invoice_number}", styles['Normal']),
        Paragraph(f"Date: {order.created_at.strftime('%B %d, %Y') if order.created_at else ''}", styles['Normal']),
        Paragraph(f"Billed to: {order.customer_label}", styles['Normal']),
        Spacer(1, 16),
    ]

    rows = [['Item', 'Qty', 'Price', 'Total']]
    for item in order.items:
        rows.append([
            item.product_name, str(item.quantity),
            f'${item.unit_price_cents / 100:.2f}', f'${item.line_total_cents / 100:.2f}',
        ])
    rows.append(['', '', 'Subtotal', f'${order.subtotal_cents / 100:.2f}'])
    rows.append(['', '', 'Total', f'${order.total_cents / 100:.2f}'])

    table = Table(rows, colWidths=[3 * inch, 0.7 * inch, 1.2 * inch, 1.2 * inch])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#eef3f0')),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTNAME', (2, -2), (-1, -1), 'Helvetica-Bold'),
        ('ALIGN', (1, 0), (-1, -1), 'RIGHT'),
        ('GRID', (0, 0), (-1, -3), 0.5, colors.HexColor('#e5e1d6')),
        ('LINEABOVE', (2, -2), (-1, -2), 0.5, colors.HexColor('#e5e1d6')),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    story.append(table)

    doc.build(story)
    return buf.getvalue()


@invoices_api.route('/businesses/<int:business_id>/invoices', methods=['GET'])
@token_required
def list_invoices(current_user, business_id):
    business, err = _owned_business_or_error(business_id, current_user)
    if err:
        return err
    orders = (Order.query.filter(Order.business_id == business.id, Order.status.in_(INVOICEABLE_STATUSES))
              .order_by(Order.created_at.desc()).limit(300).all())
    return jsonify({'invoices': [{
        'order_id': o.id,
        'invoice_number': o.invoice_number,
        'customer_label': o.customer_label,
        'total_cents': o.total_cents,
        'currency': o.currency,
        'status': o.status,
        'created_at': o.created_at.isoformat() if o.created_at else None,
        'green_invoice_doc_id': o.green_invoice_doc_id,
        'green_invoice_pdf_url': o.green_invoice_pdf_url,
    } for o in orders]})


# ── Green Invoice settings ───────────────────────────────────────────────────

def _serialize_green_invoice(account):
    if not account:
        return {'connected': False, 'enabled': False, 'api_key_id': None}
    return {'connected': True, 'enabled': account.enabled, 'api_key_id': account.api_key_id, 'last_error': account.last_error}


@invoices_api.route('/businesses/<int:business_id>/green-invoice', methods=['GET'])
@token_required
def get_green_invoice(current_user, business_id):
    business, err = _owned_business_or_error(business_id, current_user)
    if err:
        return err
    account = GreenInvoiceAccount.query.filter_by(business_id=business.id).first()
    return jsonify(_serialize_green_invoice(account))


@invoices_api.route('/businesses/<int:business_id>/green-invoice', methods=['PATCH'])
@token_required
def update_green_invoice(current_user, business_id):
    """api_key_id/api_secret are both required the first time; api_secret
    can be omitted on a later save that's only toggling `enabled` (the
    secret is never sent back to the frontend to re-submit)."""
    business, err = _owned_business_or_error(business_id, current_user)
    if err:
        return err
    body = request.get_json() or {}
    account = GreenInvoiceAccount.query.filter_by(business_id=business.id).first()

    api_key_id = (body.get('api_key_id') or '').strip()
    api_secret = (body.get('api_secret') or '').strip()
    if not account and (not api_key_id or not api_secret):
        return jsonify({'message': 'api_key_id and api_secret are both required'}), 400

    if not account:
        account = GreenInvoiceAccount(business_id=business.id, api_key_id=api_key_id, api_secret_enc=encrypt_token(api_secret))
        db.session.add(account)
    else:
        if api_key_id:
            account.api_key_id = api_key_id
        if api_secret:
            account.api_secret_enc = encrypt_token(api_secret)
    if 'enabled' in body:
        account.enabled = bool(body['enabled'])
    account.connected_by = current_user.public_id
    account.connected_at = datetime.utcnow()
    db.session.commit()
    return jsonify(_serialize_green_invoice(account))


@invoices_api.route('/businesses/<int:business_id>/green-invoice/test', methods=['POST'])
@token_required
def test_green_invoice(current_user, business_id):
    business, err = _owned_business_or_error(business_id, current_user)
    if err:
        return err
    account = GreenInvoiceAccount.query.filter_by(business_id=business.id).first()
    if not account:
        return jsonify({'message': 'Green Invoice is not connected yet'}), 400
    try:
        validate_credentials(account)
    except GreenInvoiceError as exc:
        return jsonify({'message': str(exc)}), 400
    return jsonify({'message': 'Connection successful'})


@invoices_api.route('/businesses/<int:business_id>/green-invoice', methods=['DELETE'])
@token_required
def disconnect_green_invoice(current_user, business_id):
    business, err = _owned_business_or_error(business_id, current_user)
    if err:
        return err
    account = GreenInvoiceAccount.query.filter_by(business_id=business.id).first()
    if account:
        db.session.delete(account)
        db.session.commit()
    return jsonify({'message': 'Disconnected'})


@invoices_api.route('/orders/<int:order_id>/invoice.pdf', methods=['GET'])
@token_required
def get_invoice_pdf(current_user, order_id):
    order = db.session.get(Order, order_id)
    if not order:
        return jsonify({'message': 'Order not found'}), 404
    business, err = _owned_business_or_error(order.business_id, current_user)
    if err:
        return err
    if order.status not in INVOICEABLE_STATUSES:
        return jsonify({'message': 'This order has no invoice yet (nothing has been paid)'}), 400

    if not order.invoice_number:
        ensure_invoice_number(order)
        db.session.commit()

    pdf_bytes = build_receipt_pdf(business, order)
    return send_file(
        io.BytesIO(pdf_bytes), mimetype='application/pdf',
        as_attachment=request.args.get('download') == '1',
        download_name=f'{order.invoice_number}.pdf',
    )


@invoices_api.route('/orders/<int:order_id>/invoice/credit-note', methods=['POST'])
@token_required
def issue_credit_note(current_user, order_id):
    """Owner-triggered -- there's no refund webhook anywhere in this
    codebase today, so this is the only way a Green Invoice document gets
    voided. Green Invoice documents are immutable once issued; a credit
    note is the only way to cancel one (see payments/green_invoice.py)."""
    order = db.session.get(Order, order_id)
    if not order:
        return jsonify({'message': 'Order not found'}), 404
    business, err = _owned_business_or_error(order.business_id, current_user)
    if err:
        return err
    if not order.green_invoice_doc_id:
        return jsonify({'message': 'No Green Invoice document exists for this order'}), 400

    account = GreenInvoiceAccount.query.filter_by(business_id=business.id).first()
    if not account:
        return jsonify({'message': 'Green Invoice is no longer connected for this business'}), 409
    try:
        credit_doc_id, credit_pdf_url = create_credit_note(account, order.green_invoice_doc_id)
    except GreenInvoiceError as exc:
        return jsonify({'message': str(exc)}), 502

    return jsonify({'credit_note_doc_id': credit_doc_id, 'credit_note_pdf_url': credit_pdf_url})
