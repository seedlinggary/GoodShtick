"""Immutable audit trail for the nonprofit module -- every mutating staff
action (mark-paid, cancel, reactivate, freehand override, form edits,
follow-up actions, LIVE Nedarim Plus writes, family merges/unlinks,
soft-deletes) and every webhook-driven change calls record_audit_log.
staff_email='system' means a webhook made the change, not a human.
"""
from flask import Blueprint, jsonify, request

from config import db
from backend.business.modals.nonprofit import NonprofitAuditLog
from backend.business.nonprofit_auth import staff_required
from backend.business.routes.nonprofit_import_helpers import csv_response

nonprofit_audit_api = Blueprint('nonprofit_audit_api', __name__, url_prefix='/nonprofit')


def diff_fields(before, after):
    """Returns {field: {before, after}} only for fields that actually
    changed -- an edit that changed nothing produces an empty dict, and
    record_audit_log below turns that into a no-op (no audit row at all)."""
    changes = {}
    for key, new_value in after.items():
        old_value = before.get(key)
        if old_value != new_value:
            changes[key] = {'before': old_value, 'after': new_value}
    return changes


def record_audit_log(business_id, staff_email, action, record_type, record_id, changes):
    if changes is not None and not changes:
        return
    db.session.add(NonprofitAuditLog(
        business_id=business_id, staff_email=staff_email, action=action,
        record_type=record_type, record_id=record_id, changes=changes,
    ))


def _serialize(entry):
    return {
        'id': entry.id, 'staff_email': entry.staff_email, 'action': entry.action,
        'record_type': entry.record_type, 'record_id': entry.record_id, 'changes': entry.changes,
        'created_at': entry.created_at.isoformat() if entry.created_at else None,
        # Any write that actually touched the real Nedarim Plus account
        # (not just this app's own DB) gets flagged so staff can
        # immediately tell the two apart in the UI.
        'is_live_nedarim_write': entry.action.startswith('nedarim_'),
    }


@nonprofit_audit_api.route('/businesses/<int:business_id>/audit-log', methods=['GET'])
@staff_required
def list_audit_log(staff, business_id):
    if staff.business_id != business_id:
        return jsonify({'message': 'Not authorized for this organization'}), 403

    query = NonprofitAuditLog.query.filter_by(business_id=business_id)
    record_type = request.args.get('record_type')
    record_id = request.args.get('record_id')
    if record_type:
        query = query.filter_by(record_type=record_type)
    if record_id:
        query = query.filter_by(record_id=int(record_id))

    page = max(1, int(request.args.get('page', 1)))
    per_page = min(200, max(1, int(request.args.get('per_page', 50))))
    rows = query.order_by(NonprofitAuditLog.created_at.desc()).offset((page - 1) * per_page).limit(per_page).all()
    return jsonify({'entries': [_serialize(e) for e in rows]})


@nonprofit_audit_api.route('/businesses/<int:business_id>/audit-log/export', methods=['GET'])
@staff_required
def export_audit_log(staff, business_id):
    if staff.business_id != business_id:
        return jsonify({'message': 'Not authorized for this organization'}), 403

    query = NonprofitAuditLog.query.filter_by(business_id=business_id)
    record_type = request.args.get('record_type')
    record_id = request.args.get('record_id')
    if record_type:
        query = query.filter_by(record_type=record_type)
    if record_id:
        query = query.filter_by(record_id=int(record_id))

    # Capped, same reasoning as Nedarim Plus's own history exports --
    # an unbounded export is the one way a reporting endpoint can turn
    # into an accidental denial-of-service against this app's own DB.
    rows = query.order_by(NonprofitAuditLog.created_at.desc()).limit(5000).all()
    header = ['When', 'Staff', 'Action', 'Record type', 'Record ID', 'Live Nedarim write', 'Changes']
    data = []
    for e in rows:
        changes_text = '; '.join(f'{k}: {v["before"]} -> {v["after"]}' for k, v in (e.changes or {}).items())
        data.append([e.created_at.isoformat() if e.created_at else '', e.staff_email, e.action,
                     e.record_type, e.record_id, 'Yes' if e.action.startswith('nedarim_') else 'No', changes_text])
    return csv_response(header, data, 'audit-log.csv')
