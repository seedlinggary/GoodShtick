"""Owner-authenticated custom form builder -- the same underlying
NonprofitForm/NonprofitFormField/NonprofitFormResponse models and the same
field types/conditional-logic engine as nonprofit_forms.py (the nonprofit
module's staff-portal form builder), but reachable by any business's own
owner login instead of requiring a separate nonprofit staff account.

Why a second route file instead of just opening nonprofit_forms.py's
existing routes up to owner auth too: that file's whole reason to exist is
NonprofitStaff being a DELIBERATELY separate account system from the
platform's community User accounts (see modals/nonprofit.py's own
docstring -- a volunteer staffer isn't necessarily the business owner, and
shouldn't need to be). A plain retail business has no such staff concept
at all -- its forms are managed the exact same way its Products/Bookings/
CRM/Invoices panels already are, by the owner's own login
(backend/business/routes/payments.py and siblings). Keeping these as two
route files (rather than merging auth types into one) means neither a
nonprofit's staff accounts nor its existing /staff-portal workflow change
at all.

Deliberately NOT gated by BusinessSite.enabled_modules['custom_forms'] at
the route level -- same "module controls visibility/public access, not
whether the owner can edit" split every other site-builder route file
uses (see site_pages.py's own note). The module flag is what the owner-
dashboard tab and the public /forms/:slug route check.
"""
from datetime import datetime

from flask import Blueprint, jsonify, request

from config import db
from security import token_required
from backend.business.modals.business import Business
from backend.business.modals.nonprofit import (
    NonprofitForm, NonprofitFormField, NonprofitFormResponse, FORM_FIELD_TYPES, FIELD_CONDITION_MODES,
)
from backend.business.routes.nonprofit_forms import _serialize_form, guess_identity_from_response
from backend.business.routes.nonprofit_import_helpers import csv_response

site_forms_api = Blueprint('site_forms_api', __name__, url_prefix='/business')


def _can_manage(business, user):
    if not user:
        return False
    if user.is_boss:
        return True
    if business.owner_user_id:
        return business.owner_user_id == user.public_id
    return business.created_by == user.public_id


def _owned_business_or_error(business_id, user):
    business = db.session.get(Business, business_id)
    if not business:
        return None, (jsonify({'message': 'Business not found'}), 404)
    if not _can_manage(business, user):
        return None, (jsonify({'message': 'Not authorized'}), 403)
    return business, None


def _owned_form_or_error(form_id, user):
    form = db.session.get(NonprofitForm, form_id)
    if not form:
        return None, (jsonify({'message': 'Form not found'}), 404)
    business = db.session.get(Business, form.business_id)
    if not business or not _can_manage(business, user):
        return None, (jsonify({'message': 'Form not found'}), 404)
    return form, None


@site_forms_api.route('/businesses/<int:business_id>/custom-forms', methods=['GET'])
@token_required
def list_forms(current_user, business_id):
    _, err = _owned_business_or_error(business_id, current_user)
    if err:
        return err
    rows = NonprofitForm.query.filter_by(business_id=business_id).order_by(NonprofitForm.created_at.desc()).all()
    return jsonify({'forms': [_serialize_form(f, include_fields=False) for f in rows]})


@site_forms_api.route('/businesses/<int:business_id>/custom-forms', methods=['POST'])
@token_required
def create_form(current_user, business_id):
    _, err = _owned_business_or_error(business_id, current_user)
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
    db.session.commit()
    return jsonify(_serialize_form(form)), 201


@site_forms_api.route('/custom-forms/<int:form_id>', methods=['GET'])
@token_required
def get_form(current_user, form_id):
    form, err = _owned_form_or_error(form_id, current_user)
    if err:
        return err
    return jsonify(_serialize_form(form))


@site_forms_api.route('/custom-forms/<int:form_id>', methods=['PATCH'])
@token_required
def save_form(current_user, form_id):
    """Same save-everything-at-once shape as nonprofit_forms.py's
    save_form (metadata + the whole field list in one call) -- see that
    function's own docstring for the archive-don't-delete field-sync
    logic, identical here."""
    form, err = _owned_form_or_error(form_id, current_user)
    if err:
        return err

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

    db.session.commit()
    return jsonify(_serialize_form(form))


@site_forms_api.route('/custom-forms/<int:form_id>', methods=['DELETE'])
@token_required
def delete_form(current_user, form_id):
    form, err = _owned_form_or_error(form_id, current_user)
    if err:
        return err
    db.session.delete(form)
    db.session.commit()
    return jsonify({'message': 'Deleted'})


@site_forms_api.route('/custom-forms/<int:form_id>/responses', methods=['GET'])
@token_required
def list_responses(current_user, form_id):
    form, err = _owned_form_or_error(form_id, current_user)
    if err:
        return err
    rows = NonprofitFormResponse.query.filter_by(form_id=form_id, deleted_at=None).order_by(NonprofitFormResponse.created_at.desc()).all()
    return jsonify({'responses': [
        {'id': r.id, 'answers': r.answers,
         'guessed_identity': guess_identity_from_response(form, r.answers),
         'created_at': r.created_at.isoformat() if r.created_at else None}
        for r in rows
    ]})


@site_forms_api.route('/custom-forms/<int:form_id>/responses/export', methods=['GET'])
@token_required
def export_responses(current_user, form_id):
    form, err = _owned_form_or_error(form_id, current_user)
    if err:
        return err
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


@site_forms_api.route('/custom-forms/<int:form_id>/responses/<int:response_id>', methods=['DELETE'])
@token_required
def delete_response(current_user, form_id, response_id):
    form, err = _owned_form_or_error(form_id, current_user)
    if err:
        return err
    response = NonprofitFormResponse.query.filter_by(id=response_id, form_id=form_id).first()
    if not response:
        return jsonify({'message': 'Response not found'}), 404
    response.deleted_at = datetime.utcnow()
    db.session.commit()
    return jsonify({'message': 'Deleted'})
