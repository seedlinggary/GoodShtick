"""Admin-facing dynamic form builder + response management. The public
side (fetching an open form, submitting a response) lives in
nonprofit_public.py -- this file is everything a staff member does with
Forms before and after that: building/editing the form itself, and
reviewing/editing/exporting/soft-deleting its responses.
"""
from datetime import datetime

from flask import Blueprint, jsonify, request

from config import db
from security import token_required
from backend.business.modals.business import Business
from backend.business.modals.nonprofit import (
    NonprofitForm, NonprofitFormField, NonprofitFormResponse, FORM_FIELD_TYPES, FIELD_CONDITION_MODES,
)
from backend.business.nonprofit_auth import staff_required
from backend.business.routes.nonprofit_audit import record_audit_log
from backend.business.routes.nonprofit_import_helpers import csv_response

nonprofit_forms_api = Blueprint('nonprofit_forms_api', __name__, url_prefix='/nonprofit')


def _owner_can_manage(business, user):
    if not user:
        return False
    if user.is_boss:
        return True
    if business.owner_user_id:
        return business.owner_user_id == user.public_id
    return business.created_by == user.public_id


@nonprofit_forms_api.route('/businesses/<int:business_id>/forms/for-picker', methods=['GET'])
@token_required
def list_forms_for_picker(current_user, business_id):
    """Owner-authenticated (the regular community-User token, NOT the
    separate nonprofit staff token) -- the page builder's BlockInspector
    runs under the OWNER's own login, same as every other owner-tools
    route, so the dynamic_form block's form picker can't go through the
    staff-gated list_forms() above. Minimal fields only (id/slug/title,
    no responses/field data) -- this is just enough for a <select>."""
    business = db.session.get(Business, business_id)
    if not business:
        return jsonify({'message': 'Business not found'}), 404
    if not _owner_can_manage(business, current_user):
        return jsonify({'message': 'Not authorized'}), 403
    rows = NonprofitForm.query.filter_by(business_id=business_id).order_by(NonprofitForm.title).all()
    return jsonify({'forms': [{'id': f.id, 'slug': f.slug, 'title': f.title, 'is_open': f.is_open} for f in rows]})

# Best-effort keyword lists for guessing a form response's identity from
# the FORM'S OWN field labels (a FormResponse has no fixed identity
# columns -- see modals/nonprofit.py:NonprofitFormResponse's docstring).
_IDENTITY_KEYWORDS = {
    'name': ('name',), 'email': ('email',), 'phone': ('phone', 'mobile', 'cell'),
    'address': ('address', 'street'), 'city': ('city',),
}


def _check_business(staff, business_id):
    if staff.business_id != business_id:
        return jsonify({'message': 'Not authorized for this organization'}), 403
    return None


def _serialize_field(f):
    return {
        'id': f.id, 'label': f.label, 'type': f.type, 'required': f.required, 'options': f.options,
        'help_text': f.help_text, 'order': f.order, 'archived': f.archived_at is not None,
        'condition_field_id': f.condition_field_id, 'condition_value': f.condition_value,
        'condition_mode': f.condition_mode, 'alt_label': f.alt_label,
    }


def _serialize_form(form, include_fields=True):
    data = {
        'id': form.id, 'slug': form.slug, 'title': form.title, 'description': form.description,
        'thank_you_message': form.thank_you_message, 'is_open': form.is_open,
        'response_count': NonprofitFormResponse.query.filter_by(form_id=form.id, deleted_at=None).count(),
    }
    if include_fields:
        data['fields'] = [_serialize_field(f) for f in form.fields]
    return data


@nonprofit_forms_api.route('/businesses/<int:business_id>/forms', methods=['GET'])
@staff_required
def list_forms(staff, business_id):
    err = _check_business(staff, business_id)
    if err:
        return err
    rows = NonprofitForm.query.filter_by(business_id=business_id).order_by(NonprofitForm.created_at.desc()).all()
    return jsonify({'forms': [_serialize_form(f, include_fields=False) for f in rows]})


@nonprofit_forms_api.route('/businesses/<int:business_id>/forms', methods=['POST'])
@staff_required
def create_form(staff, business_id):
    err = _check_business(staff, business_id)
    if err:
        return err
    body = request.get_json() or {}
    slug = (body.get('slug') or '').strip().lower()
    title = (body.get('title') or '').strip()
    if not slug or not title:
        return jsonify({'message': 'slug and title are required'}), 400
    if NonprofitForm.query.filter_by(business_id=business_id, slug=slug).first():
        return jsonify({'message': 'A form with that slug already exists'}), 409

    form = NonprofitForm(business_id=business_id, slug=slug, title=title, description=body.get('description'))
    db.session.add(form)
    db.session.flush()
    record_audit_log(business_id, staff.email, 'form_create', 'NonprofitForm', form.id, None)
    db.session.commit()
    return jsonify(_serialize_form(form)), 201


@nonprofit_forms_api.route('/forms/<int:form_id>', methods=['GET'])
@staff_required
def get_form(staff, form_id):
    form = NonprofitForm.query.get(form_id)
    if not form or form.business_id != staff.business_id:
        return jsonify({'message': 'Form not found'}), 404
    return jsonify(_serialize_form(form))


@nonprofit_forms_api.route('/forms/<int:form_id>', methods=['PATCH'])
@staff_required
def save_form(staff, form_id):
    """Saves the form's own metadata + its whole field list in one call
    (same shape the builder UI edits in). A field present in the
    incoming list with an `id` gets updated in place; one with no `id`
    is new; any EXISTING field not present in the incoming list gets
    ARCHIVED (archived_at set), never hard-deleted -- so a response that
    already answered it stays resolvable, and re-adding a field with the
    same label later doesn't silently inherit an old field's responses."""
    form = NonprofitForm.query.get(form_id)
    if not form or form.business_id != staff.business_id:
        return jsonify({'message': 'Form not found'}), 404

    body = request.get_json() or {}
    if 'title' in body:
        form.title = (body['title'] or '').strip() or form.title
    if 'slug' in body:
        new_slug = (body['slug'] or '').strip().lower()
        if new_slug and new_slug != form.slug:
            if NonprofitForm.query.filter_by(business_id=form.business_id, slug=new_slug).first():
                return jsonify({'message': 'A form with that slug already exists'}), 409
            form.slug = new_slug
    for field in ('description', 'thank_you_message'):
        if field in body:
            setattr(form, field, body[field])
    if 'is_open' in body:
        form.is_open = bool(body['is_open'])

    if 'fields' in body:
        incoming = body['fields'] or []
        seen_ids = set()
        for i, field_data in enumerate(incoming):
            ftype = field_data.get('type')
            if ftype not in FORM_FIELD_TYPES:
                return jsonify({'message': f'Unknown field type: {ftype!r}'}), 400
            condition_mode = field_data.get('condition_mode')
            if condition_mode and condition_mode not in FIELD_CONDITION_MODES:
                return jsonify({'message': f'condition_mode must be one of {FIELD_CONDITION_MODES}'}), 400

            field_id = field_data.get('id')
            if field_id:
                existing_field = NonprofitFormField.query.filter_by(id=field_id, form_id=form.id).first()
                if not existing_field:
                    continue
                existing_field.label = field_data.get('label', existing_field.label)
                existing_field.type = ftype
                existing_field.required = bool(field_data.get('required', existing_field.required))
                existing_field.options = field_data.get('options')
                existing_field.help_text = field_data.get('help_text')
                existing_field.order = i
                existing_field.condition_field_id = field_data.get('condition_field_id')
                existing_field.condition_value = field_data.get('condition_value')
                existing_field.condition_mode = condition_mode
                existing_field.alt_label = field_data.get('alt_label')
                existing_field.archived_at = None
                seen_ids.add(existing_field.id)
            else:
                new_field = NonprofitFormField(
                    form_id=form.id, label=field_data.get('label', ''), type=ftype,
                    required=bool(field_data.get('required')), options=field_data.get('options'),
                    help_text=field_data.get('help_text'), order=i,
                    condition_field_id=field_data.get('condition_field_id'), condition_value=field_data.get('condition_value'),
                    condition_mode=condition_mode, alt_label=field_data.get('alt_label'),
                )
                db.session.add(new_field)
                db.session.flush()
                seen_ids.add(new_field.id)

        for existing_field in form.fields:
            if existing_field.id not in seen_ids and not existing_field.archived_at:
                existing_field.archived_at = datetime.utcnow()

    record_audit_log(form.business_id, staff.email, 'form_save', 'NonprofitForm', form.id, None)
    db.session.commit()
    return jsonify(_serialize_form(form))


@nonprofit_forms_api.route('/forms/<int:form_id>', methods=['DELETE'])
@staff_required
def delete_form(staff, form_id):
    form = NonprofitForm.query.get(form_id)
    if not form or form.business_id != staff.business_id:
        return jsonify({'message': 'Form not found'}), 404
    db.session.delete(form)
    db.session.commit()
    return jsonify({'message': 'Deleted'})


def guess_identity_from_response(form, answers):
    """Best-effort name/email/phone/address/city extraction by matching
    THIS FORM's own field labels against keyword lists -- a FormResponse
    has no fixed identity columns, since every form's fields are
    different."""
    identity = {}
    for field in form.fields:
        label_lower = field.label.lower()
        for identity_key, keywords in _IDENTITY_KEYWORDS.items():
            if identity_key in identity:
                continue
            if any(kw in label_lower for kw in keywords):
                value = answers.get(str(field.id))
                if isinstance(value, str) and value.strip():
                    identity[identity_key] = value.strip()
    return identity


@nonprofit_forms_api.route('/forms/<int:form_id>/responses', methods=['GET'])
@staff_required
def list_responses(staff, form_id):
    form = NonprofitForm.query.get(form_id)
    if not form or form.business_id != staff.business_id:
        return jsonify({'message': 'Form not found'}), 404
    rows = NonprofitFormResponse.query.filter_by(form_id=form_id, deleted_at=None).order_by(NonprofitFormResponse.created_at.desc()).all()
    return jsonify({'responses': [
        {'id': r.id, 'answers': r.answers, 'family_id': r.family_id,
         'family_name': r.family.full_name if r.family else None,
         'guessed_identity': guess_identity_from_response(form, r.answers),
         'created_at': r.created_at.isoformat() if r.created_at else None}
        for r in rows
    ]})


@nonprofit_forms_api.route('/forms/<int:form_id>/responses/export', methods=['GET'])
@staff_required
def export_responses(staff, form_id):
    form = NonprofitForm.query.get(form_id)
    if not form or form.business_id != staff.business_id:
        return jsonify({'message': 'Form not found'}), 404
    rows = NonprofitFormResponse.query.filter_by(form_id=form_id, deleted_at=None).order_by(NonprofitFormResponse.created_at).all()
    fields = sorted(form.fields, key=lambda f: f.order)
    header = ['Submitted'] + [f.label for f in fields]
    data = []
    for r in rows:
        row = [r.created_at.isoformat() if r.created_at else '']
        for f in fields:
            value = r.answers.get(str(f.id), '')
            row.append(', '.join(value) if isinstance(value, list) else str(value))
        data.append(row)
    return csv_response(header, data, f'{form.slug}-responses.csv')


@nonprofit_forms_api.route('/forms/<int:form_id>/responses/<int:response_id>', methods=['PATCH'])
@staff_required
def update_response(staff, form_id, response_id):
    response = NonprofitFormResponse.query.filter_by(id=response_id, form_id=form_id).first()
    form = NonprofitForm.query.get(form_id)
    if not response or not form or form.business_id != staff.business_id:
        return jsonify({'message': 'Response not found'}), 404
    body = request.get_json() or {}
    if 'answers' in body and isinstance(body['answers'], dict):
        response.answers = body['answers']
    if 'family_id' in body:
        response.family_id = body['family_id']
    record_audit_log(form.business_id, staff.email, 'form_response_update', 'NonprofitFormResponse', response.id, None)
    db.session.commit()
    return jsonify({
        'id': response.id, 'answers': response.answers, 'family_id': response.family_id,
        'family_name': response.family.full_name if response.family else None,
    })


@nonprofit_forms_api.route('/forms/<int:form_id>/responses/<int:response_id>', methods=['DELETE'])
@staff_required
def delete_response(staff, form_id, response_id):
    response = NonprofitFormResponse.query.filter_by(id=response_id, form_id=form_id).first()
    form = NonprofitForm.query.get(form_id)
    if not response or not form or form.business_id != staff.business_id:
        return jsonify({'message': 'Response not found'}), 404
    response.deleted_at = datetime.utcnow()
    record_audit_log(form.business_id, staff.email, 'form_response_delete', 'NonprofitFormResponse', response.id, None)
    db.session.commit()
    return jsonify({'message': 'Deleted'})
