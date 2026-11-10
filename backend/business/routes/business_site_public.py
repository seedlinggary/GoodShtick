"""Public, no-auth lookup for a business's own site -- what the wildcard
subdomain infra (api/shell.js + src/siteMode.js on the frontend) calls to
turn "shmuelsbakery.gutcommunity.com" into an actual business to render.
Only ever serves a published site; a draft site or an unclaimed subdomain
both look identical from here (404) -- there is nothing for the public to
distinguish between "doesn't exist" and "not published yet".
"""
import os
import re
import secrets
from datetime import date, datetime, time, timedelta
from html import escape
from urllib.parse import urlparse

import requests
from flask import Blueprint, jsonify, request

from config import db
from security import token_optional
from upload import get_public_url
from backend.guest.modals.guest_throttle import check_and_record_guest_submission
from backend.notifications.helpers import notify
from backend.user.modals.user import User
from backend.business.modals.business import Business
from backend.business.modals.business_site import BusinessSite, DEFAULT_THEME
from backend.business.modals.site_page import SitePage, SitePageVersion
from backend.business.modals.commerce import Product, Order, OrderItem, PromoCode
from backend.business.modals.booking import ServiceType, AvailabilityRule, Appointment, RecurrenceRule
from backend.business.modals.payment_account import PaymentAccount
from backend.business.payments.providers import get_payment_provider

business_site_public_api = Blueprint('business_site_public_api', __name__, url_prefix='/business-site')

CONTACT_NAME_MAX, CONTACT_MESSAGE_MAX = 150, 2000
CONTACT_EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')
# The Contact form block's own fields (ContactFormBlock.js / BlockInspector.js)
# are now owner-editable -- any label beyond the always-required name/email,
# each optionally required -- so the server can no longer assume a single
# fixed "message" field. CONTACT_EXTRA_MAX/_LABEL_MAX/_VALUE_MAX cap that
# list the same way CONTACT_NAME_MAX/CONTACT_MESSAGE_MAX always capped the
# one fixed field, so an owner-authored form (or a crafted request) can't
# balloon a notification/email arbitrarily.
CONTACT_EXTRA_MAX, CONTACT_EXTRA_LABEL_MAX, CONTACT_EXTRA_VALUE_MAX = 10, 80, CONTACT_MESSAGE_MAX

# schema.org JSON-LD structured data, auto-generated server-side from the
# business's own real data (name/address/phone/logo/category, plus the
# rating from a google_reviews_badge block on THIS page if the owner
# placed one) -- never owner-authored HTML, so this carries none of the
# XSS risk a raw-HTML block would (see BLOCK_TYPES's own docstring on why
# there isn't one). Invisible to visitors; read only by search engines,
# to produce rich results (star ratings, business info in a knowledge
# panel) instead of making a crawler guess from visible page text.
# api/_businessSiteMeta.js injects this verbatim as a <script
# type="application/ld+json"> tag -- this function returns the complete,
# ready-to-serialize dict so that Node file has zero business logic of
# its own to keep in sync here.
SCHEMA_TYPE_BY_CATEGORY = {
    'shul': 'PlaceOfWorship', 'kollel': 'PlaceOfWorship', 'mikvah': 'PlaceOfWorship',
    'nonprofit': 'NGO', 'gemach': 'NGO',
    'restaurant': 'Restaurant', 'grocery': 'GroceryStore', 'retail': 'Store',
    'health_beauty': 'HealthAndBeautyBusiness', 'home_services': 'HomeAndConstructionBusiness',
    'automotive': 'AutomotiveBusiness', 'education': 'EducationalOrganization',
    'entertainment': 'EntertainmentBusiness', 'attraction': 'TouristAttraction',
    'professional_services': 'ProfessionalService',
}
DEFAULT_SCHEMA_TYPE = 'LocalBusiness'


def _rating_block_content(sections):
    """First google_reviews_badge block's content on this page, or None --
    there's no site-wide "the" rating to fall back to (a badge is owner-
    placed per page, like every other block), so a page with none just
    gets no aggregateRating rather than a guessed/stale one."""
    for section in sections or []:
        for block in section.get('blocks', []) or []:
            if block.get('type') == 'google_reviews_badge':
                return block.get('content') or {}
    return None


def _structured_data(business, site, sections=None):
    loc = None
    if business.locations:
        loc = next((l for l in business.locations if l.is_primary), business.locations[0])

    data = {
        '@context': 'https://schema.org',
        '@type': SCHEMA_TYPE_BY_CATEGORY.get(business.category, DEFAULT_SCHEMA_TYPE),
        'name': business.name,
    }
    if business.logo:
        data['image'] = get_public_url(business.logo)
    if business.about:
        data['description'] = business.about
    if loc:
        address = {
            k: v for k, v in {
                'streetAddress': loc.address, 'addressLocality': loc.city,
                'addressRegion': loc.state, 'postalCode': loc.zip_code, 'addressCountry': loc.country,
            }.items() if v
        }
        if address:
            data['address'] = {'@type': 'PostalAddress', **address}
        if loc.phone:
            data['telephone'] = loc.phone

    base = os.environ.get('BUSINESS_SITE_BASE_DOMAIN')
    if base:
        data['url'] = f'https://{site.subdomain}.{base}'

    rating = _rating_block_content(sections)
    if rating and rating.get('rating'):
        agg = {'@type': 'AggregateRating', 'ratingValue': rating['rating']}
        if rating.get('reviewCount'):
            agg['reviewCount'] = rating['reviewCount']
        data['aggregateRating'] = agg

    return data
MAX_CART_ITEMS = 25
MAX_ITEM_QUANTITY = 50


TURNSTILE_VERIFY_URL = 'https://challenges.cloudflare.com/turnstile/v0/siteverify'


def _verify_captcha(token, remote_ip):
    """Cloudflare Turnstile -- the one CAPTCHA this codebase integrates,
    chosen for checkout/booking specifically because this session's own
    security review flagged zero rate-limiting or bot defense existing
    anywhere else in this app (the DB-backed guest throttle is the other
    half of that). Same "not configured yet -> skip, don't block" pattern
    as Stripe: returns True with no TURNSTILE_SECRET_KEY set, so this is
    safe to ship before that env var exists. A verification-service outage
    fails CLOSED (returns False), not open -- unlike a missing config,
    which is a deliberate choice, a timeout/5xx from Cloudflare is not
    something to silently treat as "fine"."""
    secret = os.environ.get('TURNSTILE_SECRET_KEY')
    if not secret:
        return True
    if not token:
        return False
    try:
        resp = requests.post(TURNSTILE_VERIFY_URL, data={'secret': secret, 'response': token, 'remoteip': remote_ip}, timeout=5)
        return bool(resp.ok and resp.json().get('success'))
    except requests.RequestException:
        return False


def _published_site_and_business(subdomain):
    """Returns (site, business) or (None, None) -- shared by every public
    route below so "draft site" and "unclaimed subdomain" keep looking
    identical (404) from every one of them, not just this file's first
    route."""
    subdomain = (subdomain or '').strip().lower()
    site = BusinessSite.query.filter_by(subdomain=subdomain, status='published').first()
    if not site:
        return None, None
    business = db.session.get(Business, site.business_id)
    if not business:
        # Orphaned row (business deleted without cascading).
        return None, None
    return site, business


def _site_chrome(site):
    """theme + nav/footer content -- the parts of a site that apply on
    every page, included in every public response below so a page view
    never needs a second round trip just to render its own chrome."""
    return {
        'theme': {**DEFAULT_THEME, **(site.theme or {})},
        'nav_links': site.nav_links or [],
        'footer_text': site.footer_text,
        'footer_links': site.footer_links or [],
    }


@business_site_public_api.route('/public/by-domain/<domain>', methods=['GET'])
def resolve_custom_domain(domain):
    """Turns a verified foreign domain (www.shmuelsbakery.com) into the
    internal subdomain the rest of this API already knows how to serve --
    the frontend calls this once per unrecognized host, then reuses the
    resolved subdomain for every other business-site call exactly as if
    the visitor had landed on the wildcard subdomain directly. Only ever
    resolves a 'verified' domain on a published site -- a domain an owner
    merely typed in (status='pending') is exactly as inert as if the
    column were empty."""
    domain = (domain or '').strip().lower().rstrip('.')
    site = BusinessSite.query.filter_by(custom_domain=domain, custom_domain_status='verified', status='published').first()
    if not site:
        return jsonify({'message': 'Domain not found'}), 404
    return jsonify({'subdomain': site.subdomain})


@business_site_public_api.route('/public/by-subdomain/<subdomain>', methods=['GET'])
def get_site_by_subdomain(subdomain):
    site, business = _published_site_and_business(subdomain)
    if not site:
        return jsonify({'message': 'Site not found'}), 404

    return jsonify({
        'subdomain': site.subdomain,
        'business_id': business.id,
        'business_slug': business.slug,
        'name': business.name,
        'about': business.about,
        'logo': get_public_url(business.logo) if business.logo else None,
        'favicon_url': site.favicon_url,
        'enabled_modules': site.enabled_modules or {},
        **_site_chrome(site),
    })


@business_site_public_api.route('/public/<subdomain>/sitemap-data', methods=['GET'])
def get_sitemap_data(subdomain):
    """Lean {slug, is_home, updated} rows for every published page on this
    site -- api/sitemap.js's business-site branch uses this the same way
    it already uses /business/sitemap-data etc. for the 5 built-in sites,
    so each business's own storefront gets indexed as its own site rather
    than silently falling through to the main consumer site's sitemap."""
    site, business = _published_site_and_business(subdomain)
    if not site:
        return jsonify({'pages': []})
    if not site.has_module('pages'):
        return jsonify({'pages': []})

    pages = (SitePage.query
             .filter_by(business_site_id=site.id, status='published')
             .all())
    return jsonify({'pages': [
        {'slug': p.slug, 'is_home': p.is_home, 'updated': p.updated_at.isoformat() if p.updated_at else None}
        for p in pages
    ]})


@business_site_public_api.route('/public/<subdomain>/pages/<slug>', methods=['GET'])
def get_public_page(subdomain, slug):
    site, business = _published_site_and_business(subdomain)
    if not site:
        return jsonify({'message': 'Site not found'}), 404
    if not site.has_module('pages'):
        return jsonify({'message': 'Site not found'}), 404

    page = SitePage.query.filter_by(business_site_id=site.id, slug=(slug or '').strip().lower()).first()
    if not page:
        return jsonify({'message': 'Page not found'}), 404

    version = SitePageVersion.query.filter_by(page_id=page.id, is_published=True).first()
    if not version:
        return jsonify({'message': 'Page not found'}), 404

    return jsonify({
        'business_id': business.id,
        'name': business.name,
        'page': {
            'slug': page.slug,
            'title': page.title,
            'is_home': page.is_home,
            'seo_title': page.seo_title,
            'seo_description': page.seo_description,
            'seo_og_image': page.seo_og_image,
        },
        'sections': version.sections,
        'enabled_modules': site.enabled_modules or {},
        'favicon_url': site.favicon_url,
        'structured_data': _structured_data(business, site, version.sections),
        **_site_chrome(site),
    })


@business_site_public_api.route('/public/<subdomain>/home', methods=['GET'])
def get_public_home_page(subdomain):
    """Convenience lookup for "whichever page is this site's home" -- a
    thin wrapper around get_public_page() so callers (BusinessSitePublic.js)
    don't need to already know a slug. 404 the same way get_public_page()
    does if there's no home page published yet, rather than ever falling
    back to some other page silently."""
    site, _business = _published_site_and_business(subdomain)
    if not site or not site.has_module('pages'):
        return jsonify({'message': 'Site not found'}), 404

    page = SitePage.query.filter_by(business_site_id=site.id, is_home=True).first()
    if not page:
        return jsonify({'message': 'Page not found'}), 404
    return get_public_page(subdomain, page.slug)


def _send_contact_email(to_email, business_name, sender_name, sender_email, message):
    """Best-effort -- the in-app Notification created by the caller is the
    guaranteed delivery channel (always works, no config needed); this is
    a nice-to-have on top of it, same reasoning contact.py's own send has,
    so a Resend outage never blocks the submission itself."""
    api_key = os.environ.get('RESEND_API_KEY')
    from_addr = os.environ.get('EMAIL_FROM')
    if not api_key or not from_addr:
        return
    try:
        import resend
        resend.api_key = api_key
        from_name = os.environ.get('EMAIL_FROM_NAME', 'Gut Shtick')
        resend.Emails.send({
            'from': f'{from_name} <{from_addr}>',
            'to': [to_email],
            'reply_to': sender_email,
            'subject': f'New message via your {business_name} site',
            'html': (
                f'<p><strong>From:</strong> {escape(sender_name)} ({escape(sender_email)})</p>'
                f'<p style="white-space: pre-wrap;">{escape(message)}</p>'
            ),
        })
    except Exception:
        pass


@business_site_public_api.route('/public/<subdomain>/contact', methods=['POST'])
def submit_site_contact(subdomain):
    """A business's own "Contact" form block, independent of the (still
    being tested, super-admin-only for now) Leads feature on
    business_lead.py -- this needs to actually work for a real anonymous
    visitor today. Delivery is the in-app Notification (always works) plus
    a best-effort email if the owner has one on file.

    name/email stay structurally required here (there's no way to notify
    "someone" or reply to no address), but everything past them is now a
    free-form `extra` list of {label, value} pairs -- the owner's own
    field list (BlockInspector.js), each independently optional, instead
    of one fixed, always-required `message` string. `message` is still
    read directly too, purely for backward compatibility with a block
    saved before this change (or a request from a stale frontend bundle
    mid-deploy) -- folded into the same extra list rather than handled
    separately."""
    site, business = _published_site_and_business(subdomain)
    if not site or not site.has_module('pages'):
        return jsonify({'message': 'Site not found'}), 404
    if not business.owner_user_id:
        return jsonify({'message': 'This business has no owner set up to receive messages yet'}), 409

    if not check_and_record_guest_submission(request):
        return jsonify({'message': 'Too many submissions today -- try again tomorrow'}), 429

    body = request.get_json() or {}
    name = (body.get('name') or '').strip()
    email = (body.get('email') or '').strip()

    if not name or len(name) > CONTACT_NAME_MAX:
        return jsonify({'message': f'Name is required (max {CONTACT_NAME_MAX} characters)'}), 400
    if not email or not CONTACT_EMAIL_RE.match(email):
        return jsonify({'message': 'A valid email is required'}), 400

    extra = body.get('extra')
    extra_lines = []
    if isinstance(extra, list):
        for item in extra[:CONTACT_EXTRA_MAX]:
            if not isinstance(item, dict):
                continue
            label = (item.get('label') or '').strip()[:CONTACT_EXTRA_LABEL_MAX]
            value = (item.get('value') or '').strip()[:CONTACT_EXTRA_VALUE_MAX]
            if label and value:
                extra_lines.append(f'{label}: {value}')

    legacy_message = (body.get('message') or '').strip()[:CONTACT_MESSAGE_MAX]
    if legacy_message:
        extra_lines.insert(0, f'Message: {legacy_message}')

    if not extra_lines:
        return jsonify({'message': 'Please fill in at least one field below your contact info'}), 400

    message = '\n'.join(extra_lines)

    notify(business.owner_user_id, f"New message from {name} via your site",
           type='site_contact_form', link=f'/business/{business.slug}/tools')

    owner = db.session.get(User, business.owner_user_id)
    if owner and owner.email:
        _send_contact_email(owner.email, business.name, name, email, message)

    db.session.commit()
    return jsonify({'message': 'Message sent'})


# ── Storefront: products + checkout (Phase 4) ──────────────────────────────

def _public_product(p):
    return {
        'id': p.id,
        'name': p.name,
        'description': p.description,
        'price_cents': p.price_cents,
        'compare_at_price_cents': p.compare_at_price_cents,
        'on_sale': p.on_sale,
        'currency': p.currency,
        'images': p.images or [],
        'sku': p.sku,
        'in_stock': p.inventory_count is None or p.inventory_count > 0,
    }


def _check_promo_code(business, raw_code, subtotal_cents):
    """Returns (promo_or_None, discount_cents, error_or_None). Shared by
    the cart-preview endpoint below and submit_checkout itself, so a code
    that validates in the cart is guaranteed to validate the same way at
    checkout (both read the same live PromoCode row, never a client-
    supplied discount amount)."""
    code = (raw_code or '').strip().upper()
    if not code:
        return None, 0, None
    promo = PromoCode.query.filter_by(business_id=business.id, code=code).first()
    if not promo:
        return None, 0, 'That code was not found'
    error = promo.error_for(subtotal_cents)
    if error:
        return None, 0, error
    return promo, promo.discount_for(subtotal_cents), None


@business_site_public_api.route('/public/<subdomain>/promo-codes/validate', methods=['POST'])
def validate_promo_code(subdomain):
    """Cart-preview lookup -- lets the storefront show the discount before
    the customer commits to checkout. Not itself a mutation (redemption_count
    is only ever incremented once an order actually gets marked paid, in
    payments.py's _mark_order_paid)."""
    site, business = _published_site_and_business(subdomain)
    if not site or not site.has_module('products'):
        return jsonify({'message': 'Site not found'}), 404

    body = request.get_json() or {}
    try:
        subtotal_cents = int(body.get('subtotal_cents') or 0)
    except (TypeError, ValueError):
        return jsonify({'message': 'subtotal_cents must be a number'}), 400

    promo, discount_cents, error = _check_promo_code(business, body.get('code'), subtotal_cents)
    if error:
        return jsonify({'valid': False, 'message': error}), 400
    return jsonify({'valid': True, 'discount_cents': discount_cents, 'code': promo.code})


@business_site_public_api.route('/public/<subdomain>/products', methods=['GET'])
def list_public_products(subdomain):
    site, business = _published_site_and_business(subdomain)
    if not site or not site.has_module('products'):
        return jsonify({'message': 'Site not found'}), 404
    products = (Product.query.filter_by(business_id=business.id, active=True)
                .order_by(Product.position, Product.id).all())
    return jsonify({'products': [_public_product(p) for p in products]})


@business_site_public_api.route('/public/<subdomain>/products/<int:product_id>', methods=['GET'])
def get_public_product(subdomain, product_id):
    site, business = _published_site_and_business(subdomain)
    if not site or not site.has_module('products'):
        return jsonify({'message': 'Site not found'}), 404
    product = Product.query.filter_by(id=product_id, business_id=business.id, active=True).first()
    if not product:
        return jsonify({'message': 'Product not found'}), 404
    return jsonify(_public_product(product))


def _safe_storefront_origin(subdomain):
    """The absolute origin Stripe should bounce the customer back to after
    checkout. Prefers the browser's own Origin header (the real storefront
    page that initiated this fetch) over anything client-supplied in the
    request body -- a redirect target isn't something this endpoint lets
    the caller just name. When BUSINESS_SITE_BASE_DOMAIN is configured,
    the Origin's host must actually match this subdomain under it (or be
    localhost, for local dev); otherwise falls back to this backend's own
    public URL, which is always a valid, safe https target even if less
    useful UX."""
    origin = request.headers.get('Origin')
    allowed_base = os.environ.get('BUSINESS_SITE_BASE_DOMAIN')
    if origin:
        parsed = urlparse(origin)
        if parsed.scheme in ('http', 'https') and parsed.hostname:
            expected = f'{subdomain}.{allowed_base}' if allowed_base else None
            if parsed.hostname in ('localhost', '127.0.0.1') or (expected and parsed.hostname == expected) or not allowed_base:
                return f'{parsed.scheme}://{parsed.netloc}'
    return os.environ.get('BACKEND_PUBLIC_URL', request.host_url.rstrip('/'))


@business_site_public_api.route('/public/<subdomain>/checkout', methods=['POST'])
@token_optional
def submit_checkout(current_user, subdomain):
    site, business = _published_site_and_business(subdomain)
    if not site or not site.has_module('products'):
        return jsonify({'message': 'Site not found'}), 404

    payment_account = PaymentAccount.query.filter_by(business_id=business.id, status='active').first()
    if not payment_account:
        return jsonify({'message': 'This business has not set up payments yet'}), 409

    body = request.get_json() or {}
    if not _verify_captcha(body.get('captcha_token'), request.remote_addr):
        return jsonify({'message': 'Please complete the verification challenge and try again'}), 400

    if not check_and_record_guest_submission(request):
        return jsonify({'message': 'Too many requests today -- try again tomorrow'}), 429

    raw_items = body.get('items')
    if not isinstance(raw_items, list) or not raw_items:
        return jsonify({'message': 'Your cart is empty'}), 400
    if len(raw_items) > MAX_CART_ITEMS:
        return jsonify({'message': f'A cart can have at most {MAX_CART_ITEMS} different items'}), 400

    guest_email = (body.get('guest_email') or '').strip()
    guest_phone = (body.get('guest_phone') or '').strip() or None
    if not current_user and not guest_email:
        return jsonify({'message': 'An email is required to check out'}), 400
    if guest_email and not CONTACT_EMAIL_RE.match(guest_email):
        return jsonify({'message': 'A valid email is required'}), 400

    line_items, order_lines, subtotal_cents, currency = [], [], 0, None
    for raw in raw_items:
        try:
            product_id = int(raw.get('product_id'))
            quantity = int(raw.get('quantity', 1))
        except (TypeError, ValueError, AttributeError):
            return jsonify({'message': 'Invalid cart item'}), 400
        if quantity <= 0 or quantity > MAX_ITEM_QUANTITY:
            return jsonify({'message': f'Quantity must be between 1 and {MAX_ITEM_QUANTITY}'}), 400

        # Price and availability are always read fresh from the product
        # row here -- NEVER trust a client-supplied price or stock count.
        product = Product.query.filter_by(id=product_id, business_id=business.id, active=True).first()
        if not product:
            return jsonify({'message': 'One of the items in your cart is no longer available'}), 400
        if product.inventory_count is not None and product.inventory_count < quantity:
            return jsonify({'message': f'Only {product.inventory_count} left of "{product.name}"'}), 409
        if currency is None:
            currency = product.currency
        elif currency != product.currency:
            return jsonify({'message': 'All items in one order must use the same currency'}), 400

        subtotal_cents += product.price_cents * quantity
        order_lines.append((product, product.price_cents, quantity))
        line_items.append({'name': product.name, 'unit_amount_cents': product.price_cents, 'quantity': quantity})

    promo, discount_cents, promo_error = _check_promo_code(business, body.get('promo_code'), subtotal_cents)
    if promo_error:
        return jsonify({'message': promo_error}), 400
    total_cents = subtotal_cents - discount_cents

    # Fee is computed on what the customer actually pays (post-discount),
    # not the pre-discount subtotal -- otherwise a discount would come
    # entirely out of the owner's share rather than being shared the same
    # way between owner and platform as any other sale.
    fee_bps = int(os.environ.get('PLATFORM_FEE_BPS') or 0)
    platform_fee_cents = (total_cents * fee_bps) // 10000

    order = Order(
        business_id=business.id,
        subtotal_cents=subtotal_cents,
        total_cents=total_cents,
        currency=currency or 'usd',
        customer_user_id=current_user.public_id if current_user else None,
        guest_email=guest_email or None,
        guest_phone=guest_phone,
        guest_manage_token=None if current_user else secrets.token_urlsafe(32),
        platform_fee_cents=platform_fee_cents,
        payment_account_id=payment_account.id,
        promo_code_id=promo.id if promo else None,
        discount_cents=discount_cents,
    )
    db.session.add(order)
    db.session.flush()
    for product, unit_price_cents, quantity in order_lines:
        db.session.add(OrderItem(order_id=order.id, product_id=product.id, product_name=product.name,
                                  unit_price_cents=unit_price_cents, quantity=quantity))

    origin = _safe_storefront_origin(subdomain)
    provider = get_payment_provider(payment_account)
    try:
        session = provider.create_checkout_session(
            payment_account, line_items, currency or 'usd',
            success_url=f'{origin}/order/{order.id}/confirmation',
            cancel_url=f'{origin}/cart',
            platform_fee_cents=platform_fee_cents,
            metadata={'order_id': str(order.id), 'business_id': str(business.id)},
            discount_cents=discount_cents,
        )
    except Exception:  # noqa: BLE001 -- surface a clean error, never a stack trace to the browser
        db.session.rollback()
        return jsonify({'message': 'Could not start checkout -- try again'}), 502

    order.external_payment_id = session.id
    db.session.commit()

    return jsonify({'checkout_url': session.url, 'order_id': order.id})


# ── Storefront: booking (Phase 5) ───────────────────────────────────────────

@business_site_public_api.route('/public/<subdomain>/booking/<int:service_type_id>/slots', methods=['GET'])
def get_booking_slots(subdomain, service_type_id):
    site, business = _published_site_and_business(subdomain)
    if not site or not site.has_module('bookings'):
        return jsonify({'message': 'Site not found'}), 404
    service = ServiceType.query.filter_by(id=service_type_id, business_id=business.id, active=True).first()
    if not service:
        return jsonify({'message': 'Service not found'}), 404

    try:
        target_date = datetime.strptime(request.args.get('date', ''), '%Y-%m-%d').date()
    except ValueError:
        return jsonify({'message': 'date=YYYY-MM-DD is required'}), 400
    if target_date < date.today():
        return jsonify({'slots': [], 'duration_minutes': service.duration_minutes, 'price_cents': service.price_cents})

    rules = AvailabilityRule.query.filter(
        AvailabilityRule.business_id == business.id,
        AvailabilityRule.weekday == target_date.weekday(),
        db.or_(AvailabilityRule.service_type_id == service.id, AvailabilityRule.service_type_id.is_(None)),
    ).all()

    day_start = datetime.combine(target_date, time.min)
    day_end = day_start + timedelta(days=1)
    existing = Appointment.query.filter(
        Appointment.business_id == business.id, Appointment.status == 'scheduled',
        Appointment.start_at >= day_start, Appointment.start_at < day_end,
    ).all()

    # Best-effort: also exclude anything busy on the owner's connected
    # Google Calendar (a personal appointment, a block-off, etc, not just
    # this platform's own Appointment rows) -- a Calendar API hiccup here
    # just falls back to the internal-only conflict check below, never
    # breaks slot listing.
    calendar_busy = []
    from backend.business.modals.calendar_account import CalendarAccount
    calendar_account = CalendarAccount.query.filter_by(business_id=business.id, status='active').first()
    if calendar_account:
        try:
            from backend.business.calendar.google import get_busy_periods
            calendar_busy = get_busy_periods(calendar_account, day_start, day_end)
        except Exception:
            calendar_busy = []

    duration = timedelta(minutes=service.duration_minutes)
    now = datetime.utcnow()
    seen, slots = set(), []
    for rule in rules:
        cursor = datetime.combine(target_date, rule.start_time)
        window_end = datetime.combine(target_date, rule.end_time)
        step = timedelta(minutes=rule.slot_interval_minutes)
        while cursor + duration <= window_end:
            if cursor not in seen and cursor > now:
                conflict = any(a.start_at < cursor + duration and a.end_at > cursor for a in existing)
                busy = any(b_start < cursor + duration and b_end > cursor for b_start, b_end in calendar_busy)
                if not conflict and not busy:
                    slots.append(cursor.strftime('%H:%M'))
                seen.add(cursor)
            cursor += step

    return jsonify({
        'slots': sorted(slots),
        'duration_minutes': service.duration_minutes,
        'price_cents': service.price_cents,
    })


@business_site_public_api.route('/public/<subdomain>/booking/checkout', methods=['POST'])
@token_optional
def submit_booking_checkout(current_user, subdomain):
    """Reserves the slot immediately (so two people can't double-book it
    while one of them is mid-checkout), then -- for a paid service -- goes
    through the exact same checkout dispatch Phase 4's product cart uses.
    An abandoned/failed Stripe checkout no longer holds the slot forever --
    see booking.py's _expire_unpaid_appointments, run on the same
    cron/opportunistic schedule as recurring-appointment generation."""
    site, business = _published_site_and_business(subdomain)
    if not site or not site.has_module('bookings'):
        return jsonify({'message': 'Site not found'}), 404

    body = request.get_json() or {}
    service = ServiceType.query.filter_by(id=body.get('service_type_id'), business_id=business.id, active=True).first()
    if not service:
        return jsonify({'message': 'Service not found'}), 404

    try:
        start_at = datetime.strptime(body.get('start_at') or '', '%Y-%m-%dT%H:%M')
    except ValueError:
        return jsonify({'message': 'A valid start_at (YYYY-MM-DDTHH:MM) is required'}), 400
    if start_at <= datetime.utcnow():
        return jsonify({'message': 'That time has already passed'}), 400
    end_at = start_at + timedelta(minutes=service.duration_minutes)

    guest_email = (body.get('guest_email') or '').strip()
    guest_phone = (body.get('guest_phone') or '').strip() or None
    if not current_user and not guest_email:
        return jsonify({'message': 'An email is required to book'}), 400
    if guest_email and not CONTACT_EMAIL_RE.match(guest_email):
        return jsonify({'message': 'A valid email is required'}), 400

    if not _verify_captcha(body.get('captcha_token'), request.remote_addr):
        return jsonify({'message': 'Please complete the verification challenge and try again'}), 400

    if not check_and_record_guest_submission(request):
        return jsonify({'message': 'Too many requests today -- try again tomorrow'}), 429

    conflict = Appointment.query.filter(
        Appointment.business_id == business.id, Appointment.status == 'scheduled',
        Appointment.start_at < end_at, Appointment.end_at > start_at,
    ).first()
    if conflict:
        return jsonify({'message': 'That time was just booked by someone else -- pick another slot'}), 409

    recurrence_id = None
    repeat_weeks = int(body.get('repeat_weeks') or 0)
    if repeat_weeks > 1:
        rule = RecurrenceRule(
            business_id=business.id, service_type_id=service.id, recurrence_type='weekly',
            start_date=start_at.date(), start_hour=start_at.hour, start_minute=start_at.minute,
            occurrence_count=min(repeat_weeks, 52),
            customer_user_id=current_user.public_id if current_user else None,
            guest_email=guest_email or None, guest_phone=guest_phone,
        )
        db.session.add(rule)
        db.session.flush()
        recurrence_id = rule.id

    appointment = Appointment(
        business_id=business.id, service_type_id=service.id, start_at=start_at, end_at=end_at,
        customer_user_id=current_user.public_id if current_user else None,
        guest_email=guest_email or None, guest_phone=guest_phone,
        guest_manage_token=None if current_user else secrets.token_urlsafe(32),
        recurrence_id=recurrence_id,
    )
    db.session.add(appointment)
    db.session.flush()

    if not service.price_cents:
        db.session.commit()
        try:
            from backend.business.calendar.google import push_new_appointment
            push_new_appointment(business, appointment)
        except Exception:
            pass  # a Calendar failure must never block a free booking
        notify(business.owner_user_id, f'New booking: {service.name} on {start_at.strftime("%b %d at %I:%M %p")}',
               type='booking', link=f'/business/{business.slug}/tools')
        return jsonify({'appointment_id': appointment.id, 'requires_payment': False})

    payment_account = PaymentAccount.query.filter_by(business_id=business.id, status='active').first()
    if not payment_account:
        db.session.rollback()
        return jsonify({'message': 'This business has not set up payments yet'}), 409

    fee_bps = int(os.environ.get('PLATFORM_FEE_BPS') or 0)
    platform_fee_cents = (service.price_cents * fee_bps) // 10000

    order = Order(
        business_id=business.id, subtotal_cents=service.price_cents, total_cents=service.price_cents,
        currency='usd', customer_user_id=current_user.public_id if current_user else None,
        guest_email=guest_email or None, guest_phone=guest_phone,
        guest_manage_token=None if current_user else secrets.token_urlsafe(32),
        platform_fee_cents=platform_fee_cents, payment_account_id=payment_account.id,
    )
    db.session.add(order)
    db.session.flush()
    db.session.add(OrderItem(order_id=order.id, product_id=None, product_name=f'Booking: {service.name}',
                              unit_price_cents=service.price_cents, quantity=1))
    appointment.order_id = order.id

    origin = _safe_storefront_origin(subdomain)
    provider = get_payment_provider(payment_account)
    try:
        session = provider.create_checkout_session(
            payment_account,
            [{'name': f'Booking: {service.name}', 'unit_amount_cents': service.price_cents, 'quantity': 1}],
            'usd',
            success_url=f'{origin}/order/{order.id}/confirmation',
            cancel_url=f'{origin}/book',
            platform_fee_cents=platform_fee_cents,
            metadata={'order_id': str(order.id), 'appointment_id': str(appointment.id)},
        )
    except Exception:  # noqa: BLE001 -- surface a clean error, never a stack trace to the browser
        db.session.rollback()
        return jsonify({'message': 'Could not start checkout -- try again'}), 502

    order.external_payment_id = session.id
    db.session.commit()
    return jsonify({'checkout_url': session.url, 'order_id': order.id, 'requires_payment': True})
