"""Starter templates (Phase 10 of the site builder): a catalog an owner
picks from instead of starting their site from a blank canvas, plus
SuperAdmin routes to grow that catalog beyond the 5 seeded defaults.
"""
from flask import Blueprint, jsonify, request

from config import db
from security import token_required, super_admin_required
from backend.business.modals.business import Business
from backend.business.modals.business_site import BusinessSite
from backend.business.modals.site_page import SitePage, SitePageVersion
from backend.business.modals.site_template import SiteTemplate

site_templates_api = Blueprint('site_templates_api', __name__, url_prefix='/business')

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
        'home_sections': t.home_sections or [], 'nav_links': t.nav_links or [], 'footer_text': t.footer_text,
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

    # A new draft version, same as any owner-initiated save -- never
    # touches what's currently published until the owner hits Publish.
    db.session.add(SitePageVersion(page_id=page.id, sections=template.home_sections, created_by=current_user.public_id))
    db.session.commit()

    return jsonify({'message': 'Template applied', 'page_id': page.id})


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

    position = SiteTemplate.query.count()
    template = SiteTemplate(
        name=name, home_sections=home_sections,
        description=(body.get('description') or '').strip()[:DESCRIPTION_MAX] or None,
        category=(body.get('category') or '').strip() or None,
        preview_image=body.get('preview_image') or None,
        theme=body.get('theme') or None,
        nav_links=body.get('nav_links') or None,
        footer_text=(body.get('footer_text') or '').strip() or None,
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
