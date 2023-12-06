from flask import Blueprint, jsonify, request
from backend.shtick.modals.generalc import Generalc
from backend.shtick.schemas.generalc import generalcs_schema

generalc_api = Blueprint('generalc_api', __name__,url_prefix='/generalc') 


@generalc_api.route('', methods=['GET'])
def get_generalcs():
    all_generalc = Generalc.query.all()
    result = generalcs_schema.dump(all_generalc)
    return jsonify(result)
