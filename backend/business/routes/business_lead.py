"""'Request a quote' lead form -- for service businesses (caterers,
contractors, photographers) where a phone call isn't the natural first step."""
import re

from flask import Blueprint, jsonify, request

from config import db
from security import super_admin_required
from backend.notifications.helpers import notify
from backend.business.modals.business import Business
from backend.business.modals.business_lead import BusinessLead
from backend.business.schemas.business_lead import LeadSchema

lead_api = Blueprint('lead_api', __name__, url_prefix='/business')

NAME_MAX, MESSAGE_MAX = 150, 2000
EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


def _can_manage(business, user):
    if not user:
        return False
    if user.is_boss:
        return True
    if business.owner_user_id:
        return business.owner_user_id == user.public_id
    return business.created_by == user.public_id


@lead_api.route('/businesses/<int:business_id>/leads', methods=['POST'])
@super_admin_required
def submit_lead(current_user, business_id):
    business = db.session.get(Business, business_id)
    if not business:
        return jsonify({'message': 'Business not found'}), 404

    body = request.get_json() or {}
    name = (body.get('name') or '').strip()
    email = (body.get('email') or '').strip()
    message = (body.get('message') or '').strip()
    phone = (body.get('phone') or '').strip() or None

    if not name or len(name) > NAME_MAX:
        return jsonify({'message': f'Name is required (max {NAME_MAX} characters)'}), 400
    if not email or not EMAIL_RE.match(email):
        return jsonify({'message': 'A valid email is required'}), 400
    if not message or len(message) > MESSAGE_MAX:
        return jsonify({'message': f'Message is required (max {MESSAGE_MAX} characters)'}), 400

    lead = BusinessLead(business_id=business_id, name=name, email=email, message=message,
                         phone=phone, user_id=current_user.public_id if current_user else None)
    db.session.add(lead)
    db.session.flush()
    if business.owner_user_id:
        notify(business.owner_user_id, f'New quote request on {business.name} from {name}',
               type='business_lead', link=f'/business/{business.slug}/edit')
    db.session.commit()
    return jsonify(LeadSchema().dump(lead)), 201


@lead_api.route('/businesses/<int:business_id>/leads', methods=['GET'])
@super_admin_required
def list_leads(current_user, business_id):
    business = db.session.get(Business, business_id)
    if not business or not _can_manage(business, current_user):
        return jsonify({'message': 'Not authorized'}), 403
    rows = (BusinessLead.query.filter_by(business_id=business_id)
            .order_by(BusinessLead.created_at.desc()).all())
    return jsonify(LeadSchema(many=True).dump(rows))


@lead_api.route('/leads/<int:lead_id>/status', methods=['PATCH'])
@super_admin_required
def update_lead_status(current_user, lead_id):
    lead = db.session.get(BusinessLead, lead_id)
    if not lead or not _can_manage(lead.business, current_user):
        return jsonify({'message': 'Not authorized'}), 403
    status = (request.get_json() or {}).get('status')
    if status not in ('new', 'read', 'archived'):
        return jsonify({'message': 'status must be one of: new, read, archived'}), 400
    lead.status = status
    db.session.commit()
    return jsonify(LeadSchema().dump(lead))
