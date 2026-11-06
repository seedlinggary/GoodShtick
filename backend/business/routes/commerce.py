"""Owner-facing product catalog + order management (Phase 4 of the site
builder). The public-facing half -- browsing products and checking out --
lives in business_site_public.py instead, same owner/public route-file
split this feature already uses for pages (site_pages.py vs.
business_site_public.py)."""
from flask import Blueprint, jsonify, request

from datetime import datetime

from config import db
from security import token_required
from backend.business.modals.business import Business
from backend.business.modals.commerce import Product, Order, PromoCode, PROMO_DISCOUNT_TYPES

commerce_api = Blueprint('commerce_api', __name__, url_prefix='/business')

NAME_MAX = 150
MAX_IMAGES = 8
CODE_MAX = 40


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


def _serialize_product(p):
    # images are stored as already-resolved, ready-to-render URLs (same
    # convention the page builder's image/gallery blocks use, via
    # /business/upload + /business/upload-url) -- no resolution step
    # needed here.
    return {
        'id': p.id,
        'business_id': p.business_id,
        'name': p.name,
        'description': p.description,
        'price_cents': p.price_cents,
        'compare_at_price_cents': p.compare_at_price_cents,
        'on_sale': p.on_sale,
        'currency': p.currency,
        'images': p.images or [],
        'sku': p.sku,
        'inventory_count': p.inventory_count,
        'active': p.active,
        'position': p.position,
    }


def _validate_product_body(body):
    name = (body.get('name') or '').strip()
    if not name or len(name) > NAME_MAX:
        return None, f'name is required (max {NAME_MAX} characters)'
    try:
        price_cents = int(body.get('price_cents'))
    except (TypeError, ValueError):
        return None, 'price_cents must be a whole number of cents'
    if price_cents <= 0:
        return None, 'price_cents must be greater than 0'
    compare_at_price_cents = body.get('compare_at_price_cents')
    if compare_at_price_cents not in (None, ''):
        try:
            compare_at_price_cents = int(compare_at_price_cents)
        except (TypeError, ValueError):
            return None, 'compare_at_price_cents must be a whole number of cents, or omitted'
        if compare_at_price_cents <= 0:
            return None, 'compare_at_price_cents must be greater than 0'
    else:
        compare_at_price_cents = None
    images = body.get('images') or []
    if not isinstance(images, list) or len(images) > MAX_IMAGES:
        return None, f'images must be a list of at most {MAX_IMAGES} items'
    inventory_count = body.get('inventory_count')
    if inventory_count is not None:
        try:
            inventory_count = int(inventory_count)
        except (TypeError, ValueError):
            return None, 'inventory_count must be a whole number, or omitted for unlimited stock'
    return {
        'name': name,
        'description': (body.get('description') or '').strip() or None,
        'price_cents': price_cents,
        'compare_at_price_cents': compare_at_price_cents,
        'currency': (body.get('currency') or 'usd').lower(),
        'images': images,
        'sku': (body.get('sku') or '').strip() or None,
        'inventory_count': inventory_count,
        'active': bool(body.get('active', True)),
    }, None


@commerce_api.route('/businesses/<int:business_id>/products', methods=['GET'])
@token_required
def list_products(current_user, business_id):
    business, err = _owned_business_or_error(business_id, current_user)
    if err:
        return err
    products = Product.query.filter_by(business_id=business.id).order_by(Product.position, Product.id).all()
    return jsonify({'products': [_serialize_product(p) for p in products]})


@commerce_api.route('/businesses/<int:business_id>/products', methods=['POST'])
@token_required
def create_product(current_user, business_id):
    business, err = _owned_business_or_error(business_id, current_user)
    if err:
        return err
    fields, error = _validate_product_body(request.get_json() or {})
    if error:
        return jsonify({'message': error}), 400

    position = Product.query.filter_by(business_id=business.id).count()
    product = Product(business_id=business.id, position=position, **fields)
    db.session.add(product)
    db.session.commit()
    return jsonify(_serialize_product(product)), 201


@commerce_api.route('/products/<int:product_id>', methods=['PUT'])
@token_required
def update_product(current_user, product_id):
    product = db.session.get(Product, product_id)
    if not product:
        return jsonify({'message': 'Product not found'}), 404
    business, err = _owned_business_or_error(product.business_id, current_user)
    if err:
        return err

    fields, error = _validate_product_body({**_serialize_product(product), **(request.get_json() or {})})
    if error:
        return jsonify({'message': error}), 400
    for key, value in fields.items():
        setattr(product, key, value)
    db.session.commit()
    return jsonify(_serialize_product(product))


@commerce_api.route('/products/<int:product_id>', methods=['DELETE'])
@token_required
def delete_product(current_user, product_id):
    product = db.session.get(Product, product_id)
    if not product:
        return jsonify({'message': 'Product not found'}), 404
    _, err = _owned_business_or_error(product.business_id, current_user)
    if err:
        return err
    db.session.delete(product)
    db.session.commit()
    return jsonify({'message': 'Deleted'})


def _serialize_order(order):
    return {
        'id': order.id,
        'status': order.status,
        'customer_label': order.customer_label,
        'subtotal_cents': order.subtotal_cents,
        'discount_cents': order.discount_cents,
        'promo_code': order.promo_code.code if order.promo_code else None,
        'platform_fee_cents': order.platform_fee_cents,
        'total_cents': order.total_cents,
        'currency': order.currency,
        'created_at': order.created_at.isoformat() if order.created_at else None,
        'items': [{
            'product_id': i.product_id,
            'product_name': i.product_name,
            'unit_price_cents': i.unit_price_cents,
            'quantity': i.quantity,
        } for i in order.items],
    }


@commerce_api.route('/businesses/<int:business_id>/orders', methods=['GET'])
@token_required
def list_orders(current_user, business_id):
    business, err = _owned_business_or_error(business_id, current_user)
    if err:
        return err
    orders = (Order.query.filter_by(business_id=business.id)
              .order_by(Order.created_at.desc()).limit(200).all())
    return jsonify({'orders': [_serialize_order(o) for o in orders]})


@commerce_api.route('/orders/<int:order_id>/fulfill', methods=['PATCH'])
@token_required
def fulfill_order(current_user, order_id):
    order = db.session.get(Order, order_id)
    if not order:
        return jsonify({'message': 'Order not found'}), 404
    _, err = _owned_business_or_error(order.business_id, current_user)
    if err:
        return err
    if order.status != 'paid':
        return jsonify({'message': f'Only a paid order can be marked fulfilled (this one is {order.status})'}), 400
    order.status = 'fulfilled'
    db.session.commit()
    return jsonify(_serialize_order(order))


# ── Discount codes ──────────────────────────────────────────────────────────

def _serialize_promo(promo):
    return {
        'id': promo.id,
        'business_id': promo.business_id,
        'code': promo.code,
        'discount_type': promo.discount_type,
        'amount': promo.amount,
        'active': promo.active,
        'max_redemptions': promo.max_redemptions,
        'redemption_count': promo.redemption_count,
        'min_subtotal_cents': promo.min_subtotal_cents,
        'expires_at': promo.expires_at.isoformat() if promo.expires_at else None,
    }


def _validate_promo_body(body):
    code = (body.get('code') or '').strip().upper()
    if not code or len(code) > CODE_MAX:
        return None, f'code is required (max {CODE_MAX} characters)'
    discount_type = (body.get('discount_type') or '').strip()
    if discount_type not in PROMO_DISCOUNT_TYPES:
        return None, f'discount_type must be one of {PROMO_DISCOUNT_TYPES}'
    try:
        amount = int(body.get('amount'))
    except (TypeError, ValueError):
        return None, 'amount must be a whole number'
    if amount <= 0:
        return None, 'amount must be greater than 0'
    if discount_type == 'percent' and amount > 100:
        return None, 'a percent discount cannot exceed 100'

    max_redemptions = body.get('max_redemptions')
    if max_redemptions not in (None, ''):
        try:
            max_redemptions = int(max_redemptions)
        except (TypeError, ValueError):
            return None, 'max_redemptions must be a whole number, or omitted for unlimited'
    else:
        max_redemptions = None

    min_subtotal_cents = body.get('min_subtotal_cents')
    if min_subtotal_cents not in (None, ''):
        try:
            min_subtotal_cents = int(min_subtotal_cents)
        except (TypeError, ValueError):
            return None, 'min_subtotal_cents must be a whole number of cents, or omitted'
    else:
        min_subtotal_cents = None

    expires_at = None
    if body.get('expires_at'):
        try:
            expires_at = datetime.strptime(body['expires_at'][:10], '%Y-%m-%d')
        except ValueError:
            return None, 'expires_at must be a date like YYYY-MM-DD'

    return {
        'code': code,
        'discount_type': discount_type,
        'amount': amount,
        'active': bool(body.get('active', True)),
        'max_redemptions': max_redemptions,
        'min_subtotal_cents': min_subtotal_cents,
        'expires_at': expires_at,
    }, None


@commerce_api.route('/businesses/<int:business_id>/promo-codes', methods=['GET'])
@token_required
def list_promo_codes(current_user, business_id):
    business, err = _owned_business_or_error(business_id, current_user)
    if err:
        return err
    promos = PromoCode.query.filter_by(business_id=business.id).order_by(PromoCode.created_at.desc()).all()
    return jsonify({'promo_codes': [_serialize_promo(p) for p in promos]})


@commerce_api.route('/businesses/<int:business_id>/promo-codes', methods=['POST'])
@token_required
def create_promo_code(current_user, business_id):
    business, err = _owned_business_or_error(business_id, current_user)
    if err:
        return err
    fields, error = _validate_promo_body(request.get_json() or {})
    if error:
        return jsonify({'message': error}), 400
    if PromoCode.query.filter_by(business_id=business.id, code=fields['code']).first():
        return jsonify({'message': 'You already have a code with that name'}), 409

    promo = PromoCode(business_id=business.id, code=fields['code'], discount_type=fields['discount_type'],
                       amount=fields['amount'], active=fields['active'], max_redemptions=fields['max_redemptions'],
                       min_subtotal_cents=fields['min_subtotal_cents'], expires_at=fields['expires_at'])
    db.session.add(promo)
    db.session.commit()
    return jsonify(_serialize_promo(promo)), 201


@commerce_api.route('/promo-codes/<int:promo_id>', methods=['PUT'])
@token_required
def update_promo_code(current_user, promo_id):
    promo = db.session.get(PromoCode, promo_id)
    if not promo:
        return jsonify({'message': 'Code not found'}), 404
    business, err = _owned_business_or_error(promo.business_id, current_user)
    if err:
        return err

    merged = {**_serialize_promo(promo), **(request.get_json() or {})}
    fields, error = _validate_promo_body(merged)
    if error:
        return jsonify({'message': error}), 400
    if fields['code'] != promo.code and PromoCode.query.filter_by(business_id=business.id, code=fields['code']).first():
        return jsonify({'message': 'You already have a code with that name'}), 409

    for key in ('code', 'discount_type', 'amount', 'active', 'max_redemptions', 'min_subtotal_cents', 'expires_at'):
        setattr(promo, key, fields[key])
    db.session.commit()
    return jsonify(_serialize_promo(promo))


@commerce_api.route('/promo-codes/<int:promo_id>', methods=['DELETE'])
@token_required
def delete_promo_code(current_user, promo_id):
    promo = db.session.get(PromoCode, promo_id)
    if not promo:
        return jsonify({'message': 'Code not found'}), 404
    _, err = _owned_business_or_error(promo.business_id, current_user)
    if err:
        return err
    db.session.delete(promo)
    db.session.commit()
    return jsonify({'message': 'Deleted'})
