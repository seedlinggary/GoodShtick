"""Starter templates (Phase 10 of the site builder): a catalog an owner
picks from instead of starting their site from a blank canvas, plus
SuperAdmin routes to grow that catalog beyond the 5 seeded defaults.
"""
import json

from flask import Blueprint, jsonify, request

from config import db
from security import token_required, super_admin_required
from backend.business.modals.business import Business
from backend.business.modals.business_site import BusinessSite
from backend.business.modals.site_page import SitePage, SitePageVersion
from backend.business.modals.site_template import SiteTemplate

site_templates_api = Blueprint('site_templates_api', __name__, url_prefix='/business')

# A template's text is authored with these tokens instead of a fixed
# business name/category/etc. baked in -- applying a template to a real
# business substitutes its real data in, the same spirit as an AI-built
# page never inventing a photo (see api/_businessSiteMeta.js's own
# comment on that convention): a template's copy should read as written
# FOR this business, not as a generic placeholder the owner has to hunt
# through and replace by hand.
def _template_tokens(business):
    return {
        '{{business_name}}': business.name or 'Your Business',
        '{{business_category}}': (business.category or 'business').replace('_', ' '),
    }


def _apply_tokens_to_sections(sections, business):
    tokens = _template_tokens(business)
    # Round-trip through JSON instead of a recursive deepcopy-and-mutate --
    # simplest way to guarantee every nested string gets the substitution
    # (section backgrounds, block content, everything) with no risk of a
    # missed branch as new block shapes get added later.
    raw = json.dumps(sections)
    for token, replacement in tokens.items():
        raw = raw.replace(token, replacement.replace('"', '\\"'))
    return json.loads(raw)

NAME_MAX, DESCRIPTION_MAX = 100, 300


# TEMPORARY, prod-testing-only restriction -- see business_site.py's
# _can_manage for why (site builder is super-admin-only while testing on
# prod, not the usual is_boss-or-owner check).
def _can_manage(business, user):
    return bool(user and user.is_super_admin)


def _serialize_template(t):
    # Always the full shape, including home_sections -- there's no
    # lightweight/full distinction here (there was in an earlier pass;
    # removed once FreeBuilder.js (Phase 11) needed home_sections from the
    # very same public list TemplatesPanel.js already used just for its
    # picker cards). A template catalog is small (tens of rows at most),
    # so there's no real bandwidth case for trimming this.
    return {
        'id': t.id, 'name': t.name, 'description': t.description, 'category': t.category,
        'preview_image': t.preview_image, 'theme': t.theme or {},
        'home_sections': t.home_sections or [], 'extra_pages': t.extra_pages or [],
        'nav_links': t.nav_links or [], 'footer_text': t.footer_text,
        'is_system_default': t.is_system_default, 'active': t.active,
    }


@site_templates_api.route('/site-templates', methods=['GET'])
def list_site_templates():
    """Public -- just inspirational content, same openness as
    /business/site-modules and /business/site-themes."""
    templates = SiteTemplate.query.filter_by(active=True).order_by(SiteTemplate.position, SiteTemplate.id).all()
    return jsonify({'templates': [_serialize_template(t) for t in templates]})


@site_templates_api.route('/businesses/<int:business_id>/site/apply-template', methods=['POST'])
@token_required
def apply_template(current_user, business_id):
    business = db.session.get(Business, business_id)
    if not business:
        return jsonify({'message': 'Business not found'}), 404
    if not _can_manage(business, current_user):
        return jsonify({'message': 'Not authorized'}), 403

    site = BusinessSite.query.filter_by(business_id=business_id).first()
    if not site:
        return jsonify({'message': 'Set up the site first (GET /business/businesses/<id>/site)'}), 409

    template_id = (request.get_json() or {}).get('template_id')
    template = db.session.get(SiteTemplate, template_id) if template_id else None
    if not template or not template.active:
        return jsonify({'message': 'Template not found'}), 404

    # Theme: a full overwrite of the template's own keys, merged over
    # whatever the site already has -- picking a template is explicitly
    # "make me look like this", unlike ThemePanel's picker-by-picker PATCH.
    if template.theme:
        merged_theme = dict(site.theme or {})
        merged_theme.update(template.theme)
        site.theme = merged_theme

    # nav_links/footer_text: only fill in if the owner hasn't already set
    # their own -- a template shouldn't clobber real edits on a site that
    # already has content, only give a fresh site a sensible starting point.
    if template.nav_links and not site.nav_links:
        site.nav_links = template.nav_links
    if template.footer_text and not site.footer_text:
        site.footer_text = template.footer_text

    page = SitePage.query.filter_by(business_site_id=site.id, is_home=True).first()
    if not page:
        page = SitePage(business_site_id=site.id, slug='home', title='Home', is_home=True)
        db.session.add(page)
        db.session.flush()

    home_sections = _apply_tokens_to_sections(template.home_sections, business)
    # A new draft version, same as any owner-initiated save -- never
    # touches what's currently published until the owner hits Publish.
    db.session.add(SitePageVersion(page_id=page.id, sections=home_sections, created_by=current_user.public_id))

    # extra_pages (Phase 10.1): a template that's a real complete site,
    # not just a home page -- About/Services/Contact etc, each created
    # (or updated with a new draft, if the owner already has a page at
    # that slug) the same "new draft, never touches what's published"
    # way as home above.
    created_pages = 1
    for extra in (template.extra_pages or []):
        slug = (extra.get('slug') or '').strip().lower()
        if not slug:
            continue
        extra_page = SitePage.query.filter_by(business_site_id=site.id, slug=slug).first()
        if not extra_page:
            extra_page = SitePage(business_site_id=site.id, slug=slug, title=extra.get('title') or slug.title(), is_home=False)
            db.session.add(extra_page)
            db.session.flush()
        extra_sections = _apply_tokens_to_sections(extra.get('sections') or [], business)
        db.session.add(SitePageVersion(page_id=extra_page.id, sections=extra_sections, created_by=current_user.public_id))
        created_pages += 1

    db.session.commit()

    return jsonify({'message': 'Template applied', 'page_id': page.id, 'pages_created': created_pages})


# ── SuperAdmin: grow the catalog ────────────────────────────────────────────

@site_templates_api.route('/admin/site-templates', methods=['GET'])
@super_admin_required
def admin_list_site_templates(_current_user):
    templates = SiteTemplate.query.order_by(SiteTemplate.position, SiteTemplate.id).all()
    return jsonify({'templates': [_serialize_template(t) for t in templates]})


@site_templates_api.route('/admin/site-templates', methods=['POST'])
@super_admin_required
def admin_create_site_template(current_user):
    body = request.get_json() or {}
    name = (body.get('name') or '').strip()
    if not name or len(name) > NAME_MAX:
        return jsonify({'message': f'name is required (max {NAME_MAX} characters)'}), 400
    home_sections = body.get('home_sections')
    if not isinstance(home_sections, list):
        return jsonify({'message': 'home_sections must be a list of sections'}), 400
    extra_pages = body.get('extra_pages')
    if extra_pages is not None and not isinstance(extra_pages, list):
        return jsonify({'message': 'extra_pages must be a list of {slug, title, sections}'}), 400

    position = SiteTemplate.query.count()
    template = SiteTemplate(
        name=name, home_sections=home_sections,
        description=(body.get('description') or '').strip()[:DESCRIPTION_MAX] or None,
        category=(body.get('category') or '').strip() or None,
        preview_image=body.get('preview_image') or None,
        theme=body.get('theme') or None,
        nav_links=body.get('nav_links') or None,
        footer_text=(body.get('footer_text') or '').strip() or None,
        extra_pages=extra_pages,
        is_system_default=False, position=position, created_by=current_user.public_id,
    )
    db.session.add(template)
    db.session.commit()
    return jsonify(_serialize_template(template)), 201


@site_templates_api.route('/admin/site-templates/<int:template_id>', methods=['PATCH'])
@super_admin_required
def admin_update_site_template(_current_user, template_id):
    template = db.session.get(SiteTemplate, template_id)
    if not template:
        return jsonify({'message': 'Template not found'}), 404

    body = request.get_json() or {}
    if 'name' in body:
        name = (body['name'] or '').strip()
        if not name:
            return jsonify({'message': 'name cannot be empty'}), 400
        template.name = name
    if 'description' in body:
        template.description = (body['description'] or '').strip()[:DESCRIPTION_MAX] or None
    if 'category' in body:
        template.category = (body['category'] or '').strip() or None
    if 'preview_image' in body:
        template.preview_image = body['preview_image'] or None
    if 'theme' in body:
        template.theme = body['theme']
    if 'home_sections' in body:
        if not isinstance(body['home_sections'], list):
            return jsonify({'message': 'home_sections must be a list'}), 400
        template.home_sections = body['home_sections']
    if 'extra_pages' in body:
        if body['extra_pages'] is not None and not isinstance(body['extra_pages'], list):
            return jsonify({'message': 'extra_pages must be a list'}), 400
        template.extra_pages = body['extra_pages']
    if 'nav_links' in body:
        template.nav_links = body['nav_links']
    if 'footer_text' in body:
        template.footer_text = (body['footer_text'] or '').strip() or None
    if 'active' in body:
        template.active = bool(body['active'])

    db.session.commit()
    return jsonify(_serialize_template(template))


@site_templates_api.route('/admin/site-templates/<int:template_id>', methods=['DELETE'])
@super_admin_required
def admin_delete_site_template(_current_user, template_id):
    template = db.session.get(SiteTemplate, template_id)
    if not template:
        return jsonify({'message': 'Template not found'}), 404
    if template.is_system_default:
        return jsonify({'message': 'One of the 5 default templates can\'t be deleted -- deactivate it instead'}), 400
    db.session.delete(template)
    db.session.commit()
    return jsonify({'message': 'Deleted'})
