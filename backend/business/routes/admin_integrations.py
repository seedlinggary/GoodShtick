"""Lets an admin configure the Social Desk's platform-wide OAuth app
credentials (Meta, Google, X, LinkedIn) from the UI instead of needing
hosting/shell access to set environment variables -- see
social/publishers.py's get_credentials() for how these are read back."""
from flask import Blueprint, jsonify, request

from config import db
from security import admin_required
from backend.business.modals.platform_credential import PlatformCredential
from backend.business.social.crypto import encrypt_token
from backend.business.social.publishers import platform_credentials_configured

admin_integrations_api = Blueprint('admin_integrations_api', __name__, url_prefix='/business/admin')

PLATFORMS = ('facebook', 'google', 'x', 'linkedin')
PLATFORM_LABELS = {
    'facebook': 'Meta (Facebook + Instagram)', 'google': 'Google Business Profile',
    'x': 'X (Twitter)', 'linkedin': 'LinkedIn',
}


@admin_integrations_api.route('/integrations', methods=['GET'])
@admin_required
def list_integrations(_current_user):
    rows = {r.platform: r for r in PlatformCredential.query.all()}
    configured = platform_credentials_configured()
    result = []
    for platform in PLATFORMS:
        row = rows.get(platform)
        result.append({
            'platform': platform,
            'label': PLATFORM_LABELS[platform],
            # facebook/instagram share one row -- configured flag reflects
            # either connect button on the owner side.
            'configured': configured['facebook'] if platform == 'facebook' else configured[platform],
            'client_id': row.client_id if row else None,
            'source': 'database' if row else ('environment' if configured.get(platform) else None),
            'updated_at': row.updated_at.isoformat() if row and row.updated_at else None,
        })
    return jsonify(result)


@admin_integrations_api.route('/integrations/<platform>', methods=['PUT'])
@admin_required
def set_integration(current_user, platform):
    if platform not in PLATFORMS:
        return jsonify({'message': f'platform must be one of: {", ".join(PLATFORMS)}'}), 400
    body = request.get_json() or {}
    client_id = (body.get('client_id') or '').strip()
    client_secret = (body.get('client_secret') or '').strip()
    if not client_id or not client_secret:
        return jsonify({'message': 'client_id and client_secret are both required'}), 400

    row = PlatformCredential.query.filter_by(platform=platform).first()
    if row:
        row.client_id = client_id
        row.client_secret_enc = encrypt_token(client_secret)
        row.updated_by = current_user.public_id
    else:
        row = PlatformCredential(platform=platform, client_id=client_id,
                                  client_secret_enc=encrypt_token(client_secret),
                                  updated_by=current_user.public_id)
        db.session.add(row)
    db.session.commit()
    return jsonify({'message': 'Saved', 'platform': platform})


@admin_integrations_api.route('/integrations/<platform>', methods=['DELETE'])
@admin_required
def clear_integration(_current_user, platform):
    row = PlatformCredential.query.filter_by(platform=platform).first()
    if row:
        db.session.delete(row)
        db.session.commit()
    return jsonify({'message': 'Cleared'})
