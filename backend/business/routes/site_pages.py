"""Owner-facing CRUD for a business site's pages (Phase 2 of the site
builder -- see business_site.py for the module-flag gate this sits behind
and the BLOCK_TYPES schema every draft save is validated against).

Deliberately NOT gated by BusinessSite.enabled_modules['pages'] the way
the public fetch route is (see business_site_public.py) -- disabling the
module hides the owner-dashboard tab and blocks public access, but an
owner can still edit draft content while the module is off, same as any
other "feature flag" that controls visibility, not data access.
"""
import re

from flask import Blueprint, jsonify, request

from config import db
from security import token_required
from backend.business.modals.business import Business
from backend.business.modals.business_site import BusinessSite, BLOCK_TYPES
from backend.business.modals.site_page import SitePage, SitePageVersion

site_pages_api = Blueprint('site_pages_api', __name__, url_prefix='/business')

SLUG_RE = re.compile(r'^[a-z0-9](?:[a-z0-9-]{0,78}[a-z0-9])?$')
MAX_SECTIONS = 40
MAX_BLOCKS_PER_SECTION = 60
TITLE_MAX = 150
# src/siteMode.js matches /cart and /order/:orderId/confirmation BEFORE the
# generic /:slug catch-all for a business's own pages -- a page slug of
# "cart" or "order" would never actually be reachable, just silently
# shadowed by the storefront's own fixed routes, which would look like a
# bug in this feature rather than a naming collision with a different one.
RESERVED_PAGE_SLUGS = {'cart', 'order'}


# TEMPORARY, prod-testing-only restriction -- see business_site.py's
# _can_manage for why (site builder is super-admin-only while testing on
# prod, not the usual is_boss-or-owner check).
def _can_manage(business, user):
    return bool(user and user.is_super_admin)


def _owned_site_or_error(business_id, user):
    """Returns (business, site, None) or (None, None, (response, status))."""
    business = db.session.get(Business, business_id)
    if not business:
        return None, None, (jsonify({'message': 'Business not found'}), 404)
    if not _can_manage(business, user):
        return None, None, (jsonify({'message': 'Not authorized'}), 403)
    site = BusinessSite.query.filter_by(business_id=business_id).first()
    if not site:
        return None, None, (jsonify({'message': 'Set up the site first (GET /business/businesses/<id>/site)'}), 409)
    return business, site, None


def _owned_page_or_error(page_id, user):
    """Returns (page, None) or (None, (response, status))."""
    page = db.session.get(SitePage, page_id)
    if not page:
        return None, (jsonify({'message': 'Page not found'}), 404)
    business = db.session.get(Business, page.site.business_id)
    if not business or not _can_manage(business, user):
        return None, (jsonify({'message': 'Not authorized'}), 403)
    return page, None


def _validate_sections(sections):
    """Returns an error string, or None if valid. Structural validation
    only (types, bounds, the block-type whitelist) -- there's no raw-HTML
    block type in this schema at all, so there's nothing here that gets
    interpreted as markup on render, only ever assigned as plain text/
    attribute data through React. See BLOCK_TYPES's own docstring."""
    if not isinstance(sections, list):
        return 'sections must be a list'
    if len(sections) > MAX_SECTIONS:
        return f'a page can have at most {MAX_SECTIONS} sections'

    for section in sections:
        if not isinstance(section, dict) or not isinstance(section.get('id'), str) or not section['id']:
            return 'each section must be an object with a string id'
        blocks = section.get('blocks')
        if not isinstance(blocks, list):
            return 'each section needs a blocks list'
        if len(blocks) > MAX_BLOCKS_PER_SECTION:
            return f'a section can have at most {MAX_BLOCKS_PER_SECTION} blocks'

        for block in blocks:
            if not isinstance(block, dict) or not isinstance(block.get('id'), str) or not block['id']:
                return 'each block must be an object with a string id'
            if block.get('type') not in BLOCK_TYPES:
                return f"unknown block type: {block.get('type')!r}"
            for key in ('x', 'y', 'w', 'h'):
                val = block.get(key)
                if not isinstance(val, (int, float)) or isinstance(val, bool) or val < 0 or val > 100:
                    return f'block.{key} must be a number between 0 and 100'
            content = block.get('content')
            if content is not None and not isinstance(content, dict):
                return 'block.content must be an object'
            mobile_layout = block.get('mobileLayout')
            if mobile_layout is not None and not isinstance(mobile_layout, dict):
                return 'block.mobileLayout must be an object or null'
    return None


def _serialize_page(page):
    versions = page.versions  # already ordered newest-first
    published = next((v for v in versions if v.is_published), None)
    return {
        'id': page.id,
        'business_site_id': page.business_site_id,
        'slug': page.slug,
        'title': page.title,
        'is_home': page.is_home,
        'status': page.status,
        'seo_title': page.seo_title,
        'seo_description': page.seo_description,
        'seo_og_image': page.seo_og_image,
        'has_draft_changes': bool(versions and (not published or versions[0].id != published.id)),
        'updated_at': page.updated_at.isoformat() if page.updated_at else None,
    }


@site_pages_api.route('/businesses/<int:business_id>/site-pages', methods=['GET'])
@token_required
def list_site_pages(current_user, business_id):
    _, site, err = _owned_site_or_error(business_id, current_user)
    if err:
        return err
    pages = SitePage.query.filter_by(business_site_id=site.id).order_by(SitePage.is_home.desc(), SitePage.title).all()
    return jsonify({'pages': [_serialize_page(p) for p in pages]})


@site_pages_api.route('/businesses/<int:business_id>/site-pages', methods=['POST'])
@token_required
def create_site_page(current_user, business_id):
    _, site, err = _owned_site_or_error(business_id, current_user)
    if err:
        return err

    body = request.get_json() or {}
    title = (body.get('title') or '').strip()
    slug = (body.get('slug') or '').strip().lower()
    is_home = bool(body.get('is_home'))

    if not title:
        return jsonify({'message': 'title is required'}), 400
    if not SLUG_RE.match(slug):
        return jsonify({'message': 'slug must be lowercase letters, numbers, and hyphens only'}), 400
    if slug in RESERVED_PAGE_SLUGS:
        return jsonify({'message': f'"{slug}" is reserved for your site\'s cart/checkout -- pick a different slug'}), 400
    if SitePage.query.filter_by(business_site_id=site.id, slug=slug).first():
        return jsonify({'message': 'A page with that slug already exists on this site'}), 409

    if is_home:
        SitePage.query.filter_by(business_site_id=site.id, is_home=True).update({'is_home': False})

    page = SitePage(business_site_id=site.id, slug=slug, title=title, is_home=is_home)
    db.session.add(page)
    db.session.flush()  # need page.id before the first version references it

    first_version = SitePageVersion(page_id=page.id, sections=[], created_by=current_user.public_id)
    db.session.add(first_version)
    db.session.commit()

    return jsonify(_serialize_page(page)), 201


@site_pages_api.route('/site-pages/<int:page_id>', methods=['PATCH'])
@token_required
def update_page(current_user, page_id):
    """Rename a page's title/slug, or flip which page is home -- split out
    from save_page_draft's PUT (which also always writes a brand new
    SitePageVersion) specifically so renaming a page doesn't require
    resending its whole sections tree, and doesn't create a redundant
    version every time the owner just wants to fix a typo in the title or
    change the URL slug. There was previously no way to change a slug at
    all, ever, after a page was created."""
    page, err = _owned_page_or_error(page_id, current_user)
    if err:
        return err

    body = request.get_json() or {}

    if 'title' in body:
        title = (body['title'] or '').strip()
        if not title or len(title) > TITLE_MAX:
            return jsonify({'message': f'title is required (max {TITLE_MAX} characters)'}), 400
        page.title = title

    if 'slug' in body:
        slug = (body['slug'] or '').strip().lower()
        if not SLUG_RE.match(slug):
            return jsonify({'message': 'slug must be lowercase letters, numbers, and hyphens only'}), 400
        if slug in RESERVED_PAGE_SLUGS:
            return jsonify({'message': f'"{slug}" is reserved for your site\'s cart/checkout -- pick a different slug'}), 400
        existing = SitePage.query.filter_by(business_site_id=page.business_site_id, slug=slug).first()
        if existing and existing.id != page.id:
            return jsonify({'message': 'A page with that slug already exists on this site'}), 409
        page.slug = slug

    if 'is_home' in body:
        is_home = bool(body['is_home'])
        if is_home and not page.is_home:
            SitePage.query.filter_by(business_site_id=page.business_site_id, is_home=True).update({'is_home': False})
        page.is_home = is_home

    db.session.commit()
    return jsonify(_serialize_page(page))


@site_pages_api.route('/site-pages/<int:page_id>/draft', methods=['GET'])
@token_required
def get_page_draft(current_user, page_id):
    page, err = _owned_page_or_error(page_id, current_user)
    if err:
        return err
    latest = page.versions[0] if page.versions else None
    return jsonify({
        'page': _serialize_page(page),
        'sections': latest.sections if latest else [],
    })


@site_pages_api.route('/site-pages/<int:page_id>/draft', methods=['PUT'])
@token_required
def save_page_draft(current_user, page_id):
    page, err = _owned_page_or_error(page_id, current_user)
    if err:
        return err

    body = request.get_json() or {}
    sections = body.get('sections')
    validation_error = _validate_sections(sections if sections is not None else [])
    if validation_error:
        return jsonify({'message': validation_error}), 400

    if 'title' in body:
        title = (body['title'] or '').strip()
        if not title:
            return jsonify({'message': 'title cannot be empty'}), 400
        page.title = title
    if 'seo_title' in body:
        page.seo_title = (body['seo_title'] or '').strip()[:70] or None
    if 'seo_description' in body:
        page.seo_description = (body['seo_description'] or '').strip()[:200] or None
    if 'seo_og_image' in body:
        page.seo_og_image = body['seo_og_image'] or None

    version = SitePageVersion(page_id=page.id, sections=sections or [], created_by=current_user.public_id)
    db.session.add(version)
    db.session.commit()

    return jsonify({'page': _serialize_page(page), 'sections': version.sections})


@site_pages_api.route('/site-pages/<int:page_id>/publish', methods=['POST'])
@token_required
def publish_page(current_user, page_id):
    page, err = _owned_page_or_error(page_id, current_user)
    if err:
        return err
    if not page.versions:
        return jsonify({'message': 'Nothing to publish yet -- save a draft first'}), 400

    latest = page.versions[0]
    for v in page.versions:
        v.is_published = (v.id == latest.id)
    page.status = 'published'
    db.session.commit()

    return jsonify(_serialize_page(page))


@site_pages_api.route('/site-pages/<int:page_id>/unpublish', methods=['POST'])
@token_required
def unpublish_page(current_user, page_id):
    page, err = _owned_page_or_error(page_id, current_user)
    if err:
        return err
    for v in page.versions:
        v.is_published = False
    page.status = 'draft'
    db.session.commit()
    return jsonify(_serialize_page(page))


@site_pages_api.route('/site-pages/<int:page_id>', methods=['DELETE'])
@token_required
def delete_page(current_user, page_id):
    page, err = _owned_page_or_error(page_id, current_user)
    if err:
        return err
    db.session.delete(page)
    db.session.commit()
    return jsonify({'message': 'Deleted'})
