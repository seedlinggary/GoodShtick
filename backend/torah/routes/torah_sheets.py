"""Source sheets -- a rabbi curates an ordered list of sources (+ free-text
notes) and can share it. Sharing is copy-on-use, not live shared editing
(see TorahSourceSheet's docstring): anyone who can view a public sheet can
copy it into their own sheets and edit that copy freely, but can never
touch the original author's sheet -- so two people "using the same sheet"
can never clobber each other's changes."""
import io
import re
from datetime import datetime

from flask import Blueprint, jsonify, request, send_file

from config import db
from security import token_required, token_optional
from backend.torah.modals.torah import TorahSourceSheet, TorahSourceSheetItem, SHEET_ITEM_TYPES
from backend.torah.schemas.torah import SourceSheetCardSchema, make_sheet_schema
from backend.torah.routes.torah_sefaria import fetch_sefaria_text
from backend.torah.export import build_pdf, build_docx

torah_sheets_api = Blueprint('torah_sheets_api', __name__, url_prefix='/torah/sheets')

TITLE_MAX = 200
NOTE_MAX = 4000


def _safe_filename(title):
    base = re.sub(r'[^A-Za-z0-9 _-]+', '', title).strip() or 'source-sheet'
    return base[:80]


def _can_view(sheet, user):
    return sheet.is_public or bool(user and sheet.created_by == user.public_id)


def _can_edit(sheet, user):
    return bool(user and sheet.created_by == user.public_id)


def _next_position(sheet_id):
    max_pos = db.session.query(db.func.max(TorahSourceSheetItem.position)).filter_by(sheet_id=sheet_id).scalar()
    return (max_pos + 1) if max_pos is not None else 0


@torah_sheets_api.route('', methods=['GET'])
@token_required
def list_my_sheets(current_user):
    rows = (TorahSourceSheet.query.filter_by(created_by=current_user.public_id)
            .order_by(TorahSourceSheet.updated_at.desc()).all())
    return jsonify({'sheets': SourceSheetCardSchema(many=True).dump(rows)})


@torah_sheets_api.route('/sitemap-data', methods=['GET'])
def sheets_sitemap_data():
    """Minimal {id, updated} rows for every PUBLIC sheet -- same lean-query
    pattern as the other sites' own sitemap_data(). Private sheets are never
    worth a URL in the sitemap (a crawler would just get a 404, since
    _can_view gates the detail route on is_public/ownership)."""
    rows = (db.session.query(TorahSourceSheet.id, TorahSourceSheet.updated_at)
            .filter(TorahSourceSheet.is_public.is_(True)).all())
    return jsonify({
        'sheets': [{'id': sid, 'updated': updated.isoformat() if updated else None} for sid, updated in rows],
    })


@torah_sheets_api.route('/public', methods=['GET'])
def list_public_sheets():
    """Browse others' shared sheets -- no login required to browse, only to
    copy one (see copy_sheet)."""
    q = (request.args.get('q') or '').strip()
    query = TorahSourceSheet.query.filter_by(is_public=True)
    if q:
        query = query.filter(TorahSourceSheet.title.ilike(f'%{q}%'))
    rows = query.order_by(TorahSourceSheet.updated_at.desc()).limit(50).all()
    return jsonify({'sheets': SourceSheetCardSchema(many=True).dump(rows)})


@torah_sheets_api.route('', methods=['POST'])
@token_required
def create_sheet(current_user):
    body = request.get_json() or {}
    title = (body.get('title') or '').strip()
    if not title:
        return jsonify({'message': 'Title is required'}), 400
    if len(title) > TITLE_MAX:
        return jsonify({'message': f'Title must be {TITLE_MAX} characters or fewer'}), 400
    sheet = TorahSourceSheet(title=title, created_by=current_user.public_id)
    db.session.add(sheet)
    db.session.commit()
    return jsonify(make_sheet_schema(current_user).dump(sheet)), 201


@torah_sheets_api.route('/<int:sheet_id>', methods=['GET'])
@token_optional
def get_sheet(current_user, sheet_id):
    sheet = db.session.get(TorahSourceSheet, sheet_id)
    if not sheet or not _can_view(sheet, current_user):
        return jsonify({'message': 'Sheet not found'}), 404
    return jsonify(make_sheet_schema(current_user).dump(sheet))


@torah_sheets_api.route('/<int:sheet_id>', methods=['PATCH'])
@token_required
def edit_sheet(current_user, sheet_id):
    sheet = db.session.get(TorahSourceSheet, sheet_id)
    if not sheet:
        return jsonify({'message': 'Sheet not found'}), 404
    if not _can_edit(sheet, current_user):
        return jsonify({'message': 'Not authorized'}), 403

    body = request.get_json() or {}
    if 'title' in body:
        title = (body.get('title') or '').strip()
        if not title:
            return jsonify({'message': 'Title is required'}), 400
        if len(title) > TITLE_MAX:
            return jsonify({'message': f'Title must be {TITLE_MAX} characters or fewer'}), 400
        sheet.title = title
    if 'is_public' in body:
        sheet.is_public = bool(body.get('is_public'))
    sheet.updated_at = datetime.utcnow()
    db.session.commit()
    return jsonify(make_sheet_schema(current_user).dump(sheet))


@torah_sheets_api.route('/<int:sheet_id>', methods=['DELETE'])
@token_required
def delete_sheet(current_user, sheet_id):
    sheet = db.session.get(TorahSourceSheet, sheet_id)
    if not sheet:
        return jsonify({'message': 'Sheet not found'}), 404
    if not _can_edit(sheet, current_user):
        return jsonify({'message': 'Not authorized'}), 403
    db.session.delete(sheet)
    db.session.commit()
    return jsonify({'message': 'Deleted'})


@torah_sheets_api.route('/<int:sheet_id>/items', methods=['POST'])
@token_required
def add_item(current_user, sheet_id):
    """body: either {item_type: 'source', ref, custom_title?, note_text?}
    -- ref is fetched from Sefaria right now and its he/text snapshotted
    onto the item (see TorahSourceSheetItem's docstring for why) -- or
    {item_type: 'note', note_text, custom_title?} for a free-text header."""
    sheet = db.session.get(TorahSourceSheet, sheet_id)
    if not sheet:
        return jsonify({'message': 'Sheet not found'}), 404
    if not _can_edit(sheet, current_user):
        return jsonify({'message': 'Not authorized'}), 403

    body = request.get_json() or {}
    item_type = (body.get('item_type') or 'source').strip()
    if item_type not in SHEET_ITEM_TYPES:
        return jsonify({'message': f'item_type must be one of: {", ".join(SHEET_ITEM_TYPES)}'}), 400
    custom_title = (body.get('custom_title') or '').strip()[:TITLE_MAX] or None
    note_text = (body.get('note_text') or '').strip()[:NOTE_MAX] or None
    position = _next_position(sheet.id)

    if item_type == 'note':
        if not note_text:
            return jsonify({'message': 'note_text is required for a note item'}), 400
        item = TorahSourceSheetItem(
            sheet_id=sheet.id, position=position, item_type='note',
            custom_title=custom_title, note_text=note_text,
        )
    else:
        ref = (body.get('ref') or '').strip()
        if not ref:
            return jsonify({'message': 'ref is required for a source item'}), 400
        # Defaults True so existing callers that never send this (older
        # frontend builds, direct API use) keep today's behavior exactly.
        include_translation = body.get('include_translation', True)
        try:
            text_data = fetch_sefaria_text(ref)
        except RuntimeError as e:
            return jsonify({'message': f'Could not load this source from Sefaria: {e}'}), 502
        item = TorahSourceSheetItem(
            sheet_id=sheet.id, position=position, item_type='source',
            custom_title=custom_title, ref=text_data.get('ref', ref),
            he_text=text_data.get('he') or [],
            en_text=(text_data.get('text') or []) if include_translation else [],
            note_text=note_text,
        )
    db.session.add(item)
    sheet.updated_at = datetime.utcnow()
    db.session.commit()
    return jsonify(make_sheet_schema(current_user).dump(sheet)), 201


@torah_sheets_api.route('/<int:sheet_id>/items/<int:item_id>', methods=['PATCH'])
@token_required
def edit_item(current_user, sheet_id, item_id):
    """Edits only an item's own label/note -- not its underlying text, which
    stays exactly what was snapshotted when it was added (re-add it to
    pick up a since-updated Sefaria text, rather than silently drifting)."""
    sheet = db.session.get(TorahSourceSheet, sheet_id)
    if not sheet:
        return jsonify({'message': 'Sheet not found'}), 404
    if not _can_edit(sheet, current_user):
        return jsonify({'message': 'Not authorized'}), 403
    item = TorahSourceSheetItem.query.filter_by(id=item_id, sheet_id=sheet.id).first()
    if not item:
        return jsonify({'message': 'Item not found'}), 404

    body = request.get_json() or {}
    if 'custom_title' in body:
        item.custom_title = (body.get('custom_title') or '').strip()[:TITLE_MAX] or None
    if 'note_text' in body:
        item.note_text = (body.get('note_text') or '').strip()[:NOTE_MAX] or None
    sheet.updated_at = datetime.utcnow()
    db.session.commit()
    return jsonify(make_sheet_schema(current_user).dump(sheet))


@torah_sheets_api.route('/<int:sheet_id>/items/<int:item_id>', methods=['DELETE'])
@token_required
def delete_item(current_user, sheet_id, item_id):
    sheet = db.session.get(TorahSourceSheet, sheet_id)
    if not sheet:
        return jsonify({'message': 'Sheet not found'}), 404
    if not _can_edit(sheet, current_user):
        return jsonify({'message': 'Not authorized'}), 403
    item = TorahSourceSheetItem.query.filter_by(id=item_id, sheet_id=sheet.id).first()
    if not item:
        return jsonify({'message': 'Item not found'}), 404
    db.session.delete(item)
    sheet.updated_at = datetime.utcnow()
    db.session.commit()
    return jsonify(make_sheet_schema(current_user).dump(sheet))


@torah_sheets_api.route('/<int:sheet_id>/reorder', methods=['POST'])
@token_required
def reorder_items(current_user, sheet_id):
    sheet = db.session.get(TorahSourceSheet, sheet_id)
    if not sheet:
        return jsonify({'message': 'Sheet not found'}), 404
    if not _can_edit(sheet, current_user):
        return jsonify({'message': 'Not authorized'}), 403

    body = request.get_json() or {}
    order = body.get('item_ids')
    if not isinstance(order, list) or not order:
        return jsonify({'message': 'item_ids must be a non-empty list'}), 400
    items_by_id = {item.id: item for item in sheet.items}
    if set(order) != set(items_by_id.keys()):
        return jsonify({'message': "item_ids must contain exactly this sheet's item ids, each once"}), 400
    for position, item_id in enumerate(order):
        items_by_id[item_id].position = position
    sheet.updated_at = datetime.utcnow()
    db.session.commit()
    return jsonify(make_sheet_schema(current_user).dump(sheet))


@torah_sheets_api.route('/<int:sheet_id>/copy', methods=['POST'])
@token_required
def copy_sheet(current_user, sheet_id):
    """Copy-on-use sharing (see module docstring) -- clones a public (or
    the caller's own) sheet into a brand new, fully independent sheet owned
    by the caller, tagged forked_from_id for attribution."""
    source = db.session.get(TorahSourceSheet, sheet_id)
    if not source or not _can_view(source, current_user):
        return jsonify({'message': 'Sheet not found'}), 404

    copy = TorahSourceSheet(
        title=f'{source.title} (copy)', created_by=current_user.public_id,
        is_public=False, forked_from_id=source.id,
    )
    db.session.add(copy)
    db.session.flush()
    for item in source.items:
        db.session.add(TorahSourceSheetItem(
            sheet_id=copy.id, position=item.position, item_type=item.item_type,
            custom_title=item.custom_title, ref=item.ref,
            he_text=item.he_text, en_text=item.en_text, note_text=item.note_text,
        ))
    db.session.commit()
    return jsonify(make_sheet_schema(current_user).dump(copy)), 201


@torah_sheets_api.route('/<int:sheet_id>/export.pdf', methods=['GET'])
@token_optional
def export_pdf(current_user, sheet_id):
    """No ?download=1 -> inline (the browser's native PDF viewer renders it
    right there, i.e. "view before downloading"); with it, forces a save-as."""
    sheet = db.session.get(TorahSourceSheet, sheet_id)
    if not sheet or not _can_view(sheet, current_user):
        return jsonify({'message': 'Sheet not found'}), 404
    pdf_bytes = build_pdf(sheet)
    return send_file(
        io.BytesIO(pdf_bytes), mimetype='application/pdf',
        as_attachment=request.args.get('download') == '1',
        download_name=f'{_safe_filename(sheet.title)}.pdf',
    )


@torah_sheets_api.route('/<int:sheet_id>/export.docx', methods=['GET'])
@token_optional
def export_docx(current_user, sheet_id):
    sheet = db.session.get(TorahSourceSheet, sheet_id)
    if not sheet or not _can_view(sheet, current_user):
        return jsonify({'message': 'Sheet not found'}), 404
    docx_bytes = build_docx(sheet)
    return send_file(
        io.BytesIO(docx_bytes),
        mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        as_attachment=request.args.get('download') == '1',
        download_name=f'{_safe_filename(sheet.title)}.docx',
    )
