"""Owner-facing CRUD for a business's own website (Phase 0 of the site
builder: just the BusinessSite record + its module flags/theme/subdomain.
Pages, products, bookings, payments etc. are all separate, later route
files gated through BusinessSite.enabled_modules -- this file only manages
that gate itself.
"""
import os
import re
import secrets

import requests
from flask import Blueprint, jsonify, request

from config import db
from security import token_required
from upload import get_public_url
from backend.business.modals.business import Business
from backend.business.modals.business_site import (
    BusinessSite, MODULE_REGISTRY, DEFAULT_ENABLED_MODULES, SITE_STATUSES,
    default_subdomain_for, THEME_PALETTES, FONT_PAIRINGS, BUTTON_STYLES,
    FORM_STYLES, NAV_STYLES, FOOTER_STYLES, DEFAULT_THEME, validate_theme,
)

business_site_api = Blueprint('business_site_api', __name__, url_prefix='/business')

SUBDOMAIN_RE = re.compile(r'^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$')
RESERVED_SUBDOMAINS = {'www', 'api', 'admin', 'app', 'mail', 'static'}

# Custom (foreign) domain support. A bare domain/subdomain, lowercase,
# labels of letters/digits/hyphens, at least one dot -- deliberately not
# validating it's a real, resolvable, non-reserved domain beyond this
# shape; DNS verification below is what actually proves the owner
# controls it, not this regex.
CUSTOM_DOMAIN_RE = re.compile(r'^(?=.{1,255}$)[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+$')
VERIFY_TXT_PREFIX = '_goodshtick-verify'
GOOGLE_DOH_URL = 'https://dns.google/resolve'


def _dns_txt_values(name):
    """TXT record values for `name`, via Google's DNS-over-HTTPS JSON API
    -- avoids adding a DNS-resolution dependency (dnspython) just for this
    one lookup; `requests` is already a dependency everywhere else in this
    file's sibling public routes. Returns [] on any lookup failure
    (NXDOMAIN, timeout, malformed response) rather than raising -- the
    caller treats "no answer" and "wrong answer" identically anyway."""
    try:
        resp = requests.get(GOOGLE_DOH_URL, params={'name': name, 'type': 'TXT'}, timeout=6)
        if not resp.ok:
            return []
        data = resp.json()
        values = []
        for record in data.get('Answer', []) or []:
            # Google's DoH returns the TXT value quoted (and sometimes
            # split across adjacent quoted chunks) -- strip the quotes
            # rather than parse the chunking, since the token we compare
            # against is a single short hex string that'll always land in
            # one chunk.
            raw = (record.get('data') or '').strip()
            values.append(raw.strip('"'))
        return values
    except (requests.RequestException, ValueError):
        return []


# TEMPORARY, prod-testing-only restriction: the whole site builder feature
# is super-admin-only right now (not even the business's own owner), so it
# can be tested on production without any real business owner being able
# to reach it -- deliberately NOT the usual is_boss-or-owner check every
# other business-tools route file uses. Revert to that usual check (see
# e.g. backend/business/routes/business_owner_tools.py's own _can_manage)
# once this is ready to open up to real owners.
def _can_manage(business, user):
    return bool(user and user.is_super_admin)


def _unique_subdomain(preferred):
    """preferred, or preferred-2/-3/... if taken -- same collision-suffix
    idea as Business.slug generation, just scoped to this table."""
    candidate = preferred
    suffix = 2
    while BusinessSite.query.filter_by(subdomain=candidate).first() is not None:
        candidate = f'{preferred}-{suffix}'
        suffix += 1
    return candidate


def _serialize(site):
    # Looked up here (not passed in) so every call site -- GET, PATCH, the
    # auto-create path -- gets name/logo for free, same reasoning
    # business_site_public.py's own _serialize-equivalent already uses this
    # for the published-only chrome payload. The owner editor (PageEditor.js)
    # reads name/logo from THIS endpoint instead of that public one now,
    # specifically so the canvas's nav/footer preview, and the theme it's
    # rendered with, work during Draft too -- the public endpoint 404s for
    # anything not yet published, which is correct for a stranger but was
    # also silently starving the owner's own in-progress preview.
    business = db.session.get(Business, site.business_id)
    return {
        'id': site.id,
        'business_id': site.business_id,
        'name': business.name if business else None,
        'logo': get_public_url(business.logo) if business and business.logo else None,
        'subdomain': site.subdomain,
        'status': site.status,
        'enabled_modules': site.enabled_modules or {},
        # Merged over DEFAULT_THEME so the frontend never has to fill in
        # missing keys itself -- a freshly-created site (theme=None) comes
        # back fully populated with the real defaults, not an empty object.
        'theme': {**DEFAULT_THEME, **(site.theme or {})},
        'nav_links': site.nav_links or [],
        'footer_text': site.footer_text,
        'footer_links': site.footer_links or [],
        'custom_domain': site.custom_domain,
        'custom_domain_status': site.custom_domain_status,
        # Only meaningful while status is 'pending' -- the frontend uses it
        # to render the TXT record the owner still needs to publish.
        'custom_domain_verify_record': {
            'host': f'{VERIFY_TXT_PREFIX}.{site.custom_domain}',
            'type': 'TXT',
            'value': site.custom_domain_token,
        } if site.custom_domain and site.custom_domain_token else None,
        'share_products_with_community': site.share_products_with_community,
        'share_deals_with_community': site.share_deals_with_community,
        'created_at': site.created_at.isoformat() if site.created_at else None,
        'updated_at': site.updated_at.isoformat() if site.updated_at else None,
        'published_at': site.published_at.isoformat() if site.published_at else None,
    }


@business_site_api.route('/site-modules', methods=['GET'])
def list_site_modules():
    """Static catalog of available modules + their labels, so the frontend
    doesn't hardcode what it's toggling."""
    return jsonify({'modules': MODULE_REGISTRY})


@business_site_api.route('/site-themes', methods=['GET'])
def list_site_themes():
    """Static catalog backing every theme picker (palette/font/button/
    form/nav/footer) -- the frontend renders options from this instead of
    hardcoding the registry a second time."""
    return jsonify({
        'palettes': THEME_PALETTES,
        'fontPairings': FONT_PAIRINGS,
        'buttonStyles': BUTTON_STYLES,
        'formStyles': FORM_STYLES,
        'navStyles': NAV_STYLES,
        'footerStyles': FOOTER_STYLES,
        'defaultTheme': DEFAULT_THEME,
    })


@business_site_api.route('/upload-url/<filename>', methods=['GET'])
@token_required
def resolve_upload_url(current_user, filename):
    """Turns a filename /business/upload just handed back into a
    displayable URL -- the page builder's image block needs the real URL
    immediately (for the canvas preview and to store in the page's own
    JSON, which is served to the public as-is, no further resolution
    step), not just the bare filename /business/upload itself returns.
    Same `@token_required`-only gating as /business/upload itself (not
    business-specific -- any logged-in user can already upload via that
    route today)."""
    return jsonify({'url': get_public_url(filename)})


@business_site_api.route('/businesses/<int:business_id>/site', methods=['GET'])
@token_required
def get_or_create_site(current_user, business_id):
    business = db.session.get(Business, business_id)
    if not business:
        return jsonify({'message': 'Business not found'}), 404
    if not _can_manage(business, current_user):
        return jsonify({'message': 'Not authorized'}), 403

    site = BusinessSite.query.filter_by(business_id=business_id).first()
    if not site:
        preferred = default_subdomain_for(business)
        site = BusinessSite(
            business_id=business_id,
            subdomain=_unique_subdomain(preferred),
            enabled_modules=dict(DEFAULT_ENABLED_MODULES),
        )
        db.session.add(site)
        db.session.commit()

    return jsonify(_serialize(site))


@business_site_api.route('/businesses/<int:business_id>/site', methods=['PATCH'])
@token_required
def update_site(current_user, business_id):
    business = db.session.get(Business, business_id)
    if not business:
        return jsonify({'message': 'Business not found'}), 404
    if not _can_manage(business, current_user):
        return jsonify({'message': 'Not authorized'}), 403

    site = BusinessSite.query.filter_by(business_id=business_id).first()
    if not site:
        return jsonify({'message': 'Create the site first (GET this endpoint once) before editing it'}), 409

    body = request.get_json() or {}

    if 'subdomain' in body:
        candidate = (body['subdomain'] or '').strip().lower()
        if not SUBDOMAIN_RE.match(candidate):
            return jsonify({'message': 'Subdomain must be lowercase letters, numbers, and hyphens only'}), 400
        if candidate in RESERVED_SUBDOMAINS:
            return jsonify({'message': 'That subdomain is reserved'}), 400
        existing = BusinessSite.query.filter_by(subdomain=candidate).first()
        if existing and existing.id != site.id:
            return jsonify({'message': 'That subdomain is already taken'}), 409
        site.subdomain = candidate

    if 'enabled_modules' in body:
        incoming = body['enabled_modules']
        if not isinstance(incoming, dict):
            return jsonify({'message': 'enabled_modules must be an object'}), 400
        unknown = [k for k in incoming if k not in MODULE_REGISTRY]
        if unknown:
            return jsonify({'message': f'Unknown module(s): {", ".join(unknown)}'}), 400
        merged = dict(site.enabled_modules or {})
        merged.update({k: bool(v) for k, v in incoming.items()})
        site.enabled_modules = merged

    if 'theme' in body:
        incoming_theme = body['theme']
        error = validate_theme(incoming_theme if incoming_theme is not None else {})
        if error:
            return jsonify({'message': error}), 400
        # Merged, like enabled_modules above -- a picker changing just
        # buttonStyle shouldn't silently reset palette/fontPairing back
        # to defaults.
        merged_theme = dict(site.theme or {})
        if incoming_theme:
            merged_theme.update(incoming_theme)
        site.theme = merged_theme

    if 'nav_links' in body:
        incoming = body['nav_links'] or []
        if not isinstance(incoming, list) or any(not isinstance(l, dict) or 'label' not in l or 'path' not in l for l in incoming):
            return jsonify({'message': 'nav_links must be a list of {label, path} objects'}), 400
        site.nav_links = incoming

    if 'footer_text' in body:
        site.footer_text = (body['footer_text'] or '').strip()[:300] or None

    if 'footer_links' in body:
        incoming = body['footer_links'] or []
        if not isinstance(incoming, list) or any(not isinstance(l, dict) or 'label' not in l or 'path' not in l for l in incoming):
            return jsonify({'message': 'footer_links must be a list of {label, path} objects'}), 400
        site.footer_links = incoming

    if 'share_products_with_community' in body:
        site.share_products_with_community = bool(body['share_products_with_community'])

    if 'share_deals_with_community' in body:
        site.share_deals_with_community = bool(body['share_deals_with_community'])

    if 'status' in body:
        if body['status'] not in SITE_STATUSES:
            return jsonify({'message': f'status must be one of {SITE_STATUSES}'}), 400
        site.status = body['status']
        if body['status'] == 'published' and not site.published_at:
            from datetime import datetime
            site.published_at = datetime.utcnow()

    db.session.commit()
    return jsonify(_serialize(site))


def _get_owned_site(current_user, business_id):
    """Shared lookup for the three domain routes below -- same 404/403
    shape as update_site above, just factored out since all three need it."""
    business = db.session.get(Business, business_id)
    if not business:
        return None, (jsonify({'message': 'Business not found'}), 404)
    if not _can_manage(business, current_user):
        return None, (jsonify({'message': 'Not authorized'}), 403)
    site = BusinessSite.query.filter_by(business_id=business_id).first()
    if not site:
        return None, (jsonify({'message': 'Create the site first (GET /site once) before editing it'}), 409)
    return site, None


@business_site_api.route('/businesses/<int:business_id>/site/domain', methods=['POST'])
@token_required
def set_custom_domain(current_user, business_id):
    """Starts (or restarts) ownership verification for a foreign domain --
    this alone never makes the domain live; see _published_site_and_business_by_domain
    in business_site_public.py, which only ever honors a 'verified' one.
    Setting a new domain always resets status back to 'pending' and issues
    a fresh token, even if a previous domain on this site was already
    verified -- verifying domain A is not evidence the owner controls
    domain B."""
    site, err = _get_owned_site(current_user, business_id)
    if err:
        return err

    domain = (request.get_json() or {}).get('domain', '').strip().lower().rstrip('.')
    if not domain:
        return jsonify({'message': 'Domain is required'}), 400
    if not CUSTOM_DOMAIN_RE.match(domain):
        return jsonify({'message': 'Enter a real domain, like www.yourbusiness.com'}), 400

    base = os.environ.get('BUSINESS_SITE_BASE_DOMAIN')
    if base and (domain == base.lower() or domain.endswith(f'.{base.lower()}')):
        return jsonify({'message': 'That domain is reserved for Good Shtick subdomains'}), 400

    existing = BusinessSite.query.filter_by(custom_domain=domain).first()
    if existing and existing.id != site.id:
        return jsonify({'message': 'That domain is already connected to another site'}), 409

    site.custom_domain = domain
    site.custom_domain_status = 'pending'
    site.custom_domain_token = secrets.token_hex(16)
    db.session.commit()
    return jsonify(_serialize(site))


@business_site_api.route('/businesses/<int:business_id>/site/domain/verify', methods=['POST'])
@token_required
def verify_custom_domain(current_user, business_id):
    """Checks the TXT record the owner was told to publish. Deliberately
    re-checkable any number of times (DNS propagation is the owner's
    waiting game, not ours) -- never locks out retries."""
    site, err = _get_owned_site(current_user, business_id)
    if err:
        return err

    if not site.custom_domain or not site.custom_domain_token:
        return jsonify({'message': 'No domain is connected yet'}), 400
    if site.custom_domain_status == 'verified':
        return jsonify(_serialize(site))

    record_host = f'{VERIFY_TXT_PREFIX}.{site.custom_domain}'
    values = _dns_txt_values(record_host)
    if site.custom_domain_token not in values:
        return jsonify({
            'message': 'That TXT record isn\'t showing up yet. DNS changes can take a few minutes to a day to take effect -- double check the record and try again shortly.',
            'verified': False,
        }), 409

    site.custom_domain_status = 'verified'
    db.session.commit()
    return jsonify(_serialize(site))


@business_site_api.route('/businesses/<int:business_id>/site/domain', methods=['DELETE'])
@token_required
def remove_custom_domain(current_user, business_id):
    site, err = _get_owned_site(current_user, business_id)
    if err:
        return err
    site.custom_domain = None
    site.custom_domain_status = None
    site.custom_domain_token = None
    db.session.commit()
    return jsonify(_serialize(site))
