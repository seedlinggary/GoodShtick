"""'Ask a question' without WhatsApp -- answered questions double as a small
public FAQ on the profile."""
from datetime import datetime

from flask import Blueprint, jsonify, request

from config import db
from security import token_optional, token_required
from backend.notifications.helpers import notify
from backend.business.modals.business import Business
from backend.business.modals.business_question import BusinessQuestion
from backend.business.schemas.business_question import QuestionSchema

question_api = Blueprint('question_api', __name__, url_prefix='/business')

NAME_MAX, QUESTION_MAX, ANSWER_MAX = 150, 800, 1500


def _can_manage(business, user):
    if not user:
        return False
    if user.is_boss:
        return True
    if business.owner_user_id:
        return business.owner_user_id == user.public_id
    return business.created_by == user.public_id


@question_api.route('/businesses/<int:business_id>/questions', methods=['GET'])
@token_optional
def list_questions(current_user, business_id):
    """Public: answered questions only, as a mini-FAQ, unless the requester
    manages the business (they see everything, including unanswered)."""
    business = db.session.get(Business, business_id)
    if not business:
        return jsonify({'message': 'Business not found'}), 404
    query = BusinessQuestion.query.filter_by(business_id=business_id)
    if not _can_manage(business, current_user):
        query = query.filter(BusinessQuestion.answer.isnot(None))
    rows = query.order_by(BusinessQuestion.created_at.desc()).all()
    return jsonify(QuestionSchema(many=True).dump(rows))


@question_api.route('/businesses/<int:business_id>/questions', methods=['POST'])
@token_required
def ask_question(current_user, business_id):
    business = db.session.get(Business, business_id)
    if not business:
        return jsonify({'message': 'Business not found'}), 404

    question = ((request.get_json() or {}).get('question') or '').strip()
    if not question or len(question) > QUESTION_MAX:
        return jsonify({'message': f'A question (max {QUESTION_MAX} characters) is required'}), 400

    row = BusinessQuestion(business_id=business_id, asker_name=current_user.profile_name or 'A visitor',
                            question=question, user_id=current_user.public_id, asker_email=current_user.email)
    db.session.add(row)
    db.session.flush()
    if business.owner_user_id:
        notify(business.owner_user_id, f'New question on {business.name}',
               type='business_question', link=f'/business/{business.slug}/edit')
    db.session.commit()
    return jsonify(QuestionSchema().dump(row)), 201


@question_api.route('/questions/<int:question_id>/answer', methods=['POST'])
@token_required
def answer_question(current_user, question_id):
    question = db.session.get(BusinessQuestion, question_id)
    if not question or not _can_manage(question.business, current_user):
        return jsonify({'message': 'Not authorized'}), 403

    answer = ((request.get_json() or {}).get('answer') or '').strip()
    if not answer or len(answer) > ANSWER_MAX:
        return jsonify({'message': f'An answer (max {ANSWER_MAX} characters) is required'}), 400

    question.answer = answer
    question.answered_at = datetime.utcnow()
    db.session.flush()
    if question.user_id:
        notify(question.user_id, f'{question.business.name} answered your question',
               type='business_question_answered', link=f'/business/{question.business.slug}')
    db.session.commit()
    return jsonify(QuestionSchema().dump(question))
