"""Super-admin-editable site-wide announcement banner, shown above the
navbar on every one of GUT's 5 sites (one shared React bundle/backend) --
dismissible per-visitor via localStorage on the frontend (see
good-shtick/src/SiteBanner.js), edited from SuperAdminDashboard with no
redeploy, same shape as AlertDigestSchedule in backend/alerts."""
from datetime import datetime

from flask import Blueprint, jsonify, request

from config import db
from security import super_admin_required
from backend.banner.modals.banner import SiteBanner, BANNER_STYLES
from backend.banner.schemas.banner import site_banner_schema

banner_api = Blueprint('banner_api', __name__, url_prefix='/banner')

MESSAGE_MAX = 500
LINK_TEXT_MAX = 60


def _get_banner():
    """Get-or-create the single banner row (id=1) -- lazy, same pattern as
    alerts/routes/alert.py's _get_schedule(), so a fresh/test DB never needs
    seeding."""
    row = db.session.get(SiteBanner, 1)
    if not row:
        row = SiteBanner(id=1)
        db.session.add(row)
        db.session.commit()
    return row


@banner_api.route('', methods=['GET'])
def get_banner():
    """Public, unauthenticated -- every visitor on every site checks this
    once on load. Always 200 with enabled=false rather than 404 when
    there's nothing configured yet, so the frontend never has to
    special-case "no banner" differently from "banner turned off"."""
    return jsonify(site_banner_schema.dump(_get_banner()))


@banner_api.route('/admin', methods=['GET'])
@super_admin_required
def get_banner_admin(_current_user):
    return jsonify(site_banner_schema.dump(_get_banner()))


@banner_api.route('/admin', methods=['PATCH'])
@super_admin_required
def update_banner(_current_user):
    body = request.get_json(silent=True) or {}
    row = _get_banner()

    if 'message' in body:
        message = (body['message'] or '').strip()[:MESSAGE_MAX]
        row.message = message or None
    if 'link_url' in body:
        link_url = (body['link_url'] or '').strip()
        row.link_url = link_url or None
    if 'link_text' in body:
        link_text = (body['link_text'] or '').strip()[:LINK_TEXT_MAX]
        row.link_text = link_text or None
    if 'style' in body:
        if body['style'] not in BANNER_STYLES:
            return jsonify({'message': f'style must be one of {BANNER_STYLES}'}), 400
        row.style = body['style']
    if 'enabled' in body:
        row.enabled = bool(body['enabled'])

    if row.enabled and not row.message:
        return jsonify({'message': 'Add a message before turning the banner on.'}), 400

    row.updated_at = datetime.utcnow()
    db.session.commit()
    return jsonify(site_banner_schema.dump(row))
