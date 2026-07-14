from flask import Blueprint, jsonify, request
from config import db, cache
from security import super_admin_required
from backend.shtick.modals.generalc import Generalc
from backend.shtick.modals.shtick import Shtick, shtick_categories
from backend.shtick.schemas.generalc import generalc_schema, generalcs_schema

generalc_api = Blueprint('generalc_api', __name__, url_prefix='/generalc')

# Must match Generalc.name's actual column width (String(100), widened for
# longer AI-generated category names) -- this constant had drifted out of
# sync with the DB column and would wrongly reject valid long names.
NAME_MAX = 100


@generalc_api.route('', methods=['GET'])
@cache.cached(timeout=600)  # categories barely ever change; hit on every page load via Navbar
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
    cache.clear()
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
    cache.clear()
    return jsonify({'message': 'deleted'})
