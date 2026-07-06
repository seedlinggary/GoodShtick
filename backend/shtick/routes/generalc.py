from flask import Blueprint, jsonify, request
from config import db
from security import super_admin_required
from backend.shtick.modals.generalc import Generalc
from backend.shtick.modals.shtick import Shtick, shtick_categories
from backend.shtick.schemas.generalc import generalc_schema, generalcs_schema

generalc_api = Blueprint('generalc_api', __name__, url_prefix='/generalc')

NAME_MAX = 20


@generalc_api.route('', methods=['GET'])
def get_generalcs():
    all_generalc = Generalc.query.order_by(Generalc.name.asc()).all()
    result = generalcs_schema.dump(all_generalc)
    return jsonify(result)


@generalc_api.route('', methods=['POST'])
@super_admin_required
def create_generalc(_current_user):
    body = request.get_json() or {}
    name = (body.get('name') or '').strip()
    if not name:
        return jsonify({'message': 'Category name is required'}), 400
    if len(name) > NAME_MAX:
        return jsonify({'message': f'Category name must be {NAME_MAX} characters or fewer'}), 400
    if Generalc.query.filter(db.func.lower(Generalc.name) == name.lower()).first():
        return jsonify({'message': f'"{name}" already exists'}), 409

    cat = Generalc(name)
    db.session.add(cat)
    db.session.commit()
    return jsonify(generalc_schema.dump(cat)), 201


@generalc_api.route('/<int:generalc_id>', methods=['DELETE'])
@super_admin_required
def delete_generalc(_current_user, generalc_id):
    cat = db.session.get(Generalc, generalc_id)
    if not cat:
        return jsonify({'message': 'Category not found'}), 404

    used_as_primary = Shtick.query.filter_by(generalc_id=generalc_id).first() is not None
    used_as_tag = db.session.query(shtick_categories).filter_by(generalc_id=generalc_id).first() is not None
    if used_as_primary or used_as_tag:
        return jsonify({'message': 'This category is used by existing posts and cannot be deleted.'}), 409

    db.session.delete(cat)
    db.session.commit()
    return jsonify({'message': 'deleted'})
