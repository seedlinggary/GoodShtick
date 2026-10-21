from flask import Blueprint, jsonify, request

from config import db
from security import token_required
from backend.finance.modals.finance import (
    FinanceWatchlistItem, FinanceBudget, FinanceBudgetCategory, BUDGET_CATEGORY_KINDS,
)
from backend.finance.schemas.finance import WatchlistItemSchema, BudgetSchema

finance_budget_api = Blueprint('finance_budget_api', __name__, url_prefix='/finance')

NAME_MAX = 80
MAX_CATEGORIES = 60


@finance_budget_api.route('/watchlist', methods=['GET'])
@token_required
def list_watchlist(current_user):
    rows = (FinanceWatchlistItem.query.filter_by(user_id=current_user.public_id)
            .order_by(FinanceWatchlistItem.created_at.desc()).all())
    return jsonify({'items': WatchlistItemSchema(many=True).dump(rows)})


@finance_budget_api.route('/watchlist', methods=['POST'])
@token_required
def add_watchlist_item(current_user):
    symbol = ((request.get_json() or {}).get('symbol') or '').strip().upper()
    if not symbol:
        return jsonify({'message': 'symbol is required'}), 400
    existing = FinanceWatchlistItem.query.filter_by(user_id=current_user.public_id, symbol=symbol).first()
    if not existing:
        db.session.add(FinanceWatchlistItem(user_id=current_user.public_id, symbol=symbol))
        db.session.commit()
    return jsonify({'message': 'Added'}), 201


@finance_budget_api.route('/watchlist/<symbol>', methods=['DELETE'])
@token_required
def remove_watchlist_item(current_user, symbol):
    item = FinanceWatchlistItem.query.filter_by(user_id=current_user.public_id, symbol=symbol.upper()).first()
    if item:
        db.session.delete(item)
        db.session.commit()
    return jsonify({'message': 'Removed'})


def _get_or_create_budget(user_id):
    budget = FinanceBudget.query.filter_by(user_id=user_id).first()
    if not budget:
        budget = FinanceBudget(user_id=user_id)
        db.session.add(budget)
        db.session.commit()
    return budget


@finance_budget_api.route('/budget', methods=['GET'])
@token_required
def get_budget(current_user):
    budget = _get_or_create_budget(current_user.public_id)
    return jsonify(BudgetSchema().dump(budget))


@finance_budget_api.route('/budget', methods=['PUT'])
@token_required
def replace_budget(current_user):
    """Replaces the whole category list in one call -- the Budgeting page's
    form always edits/submits the full set at once, so there's no partial-
    update case to support (see FinanceBudget's own docstring)."""
    body = request.get_json() or {}
    categories = body.get('categories')
    if not isinstance(categories, list):
        return jsonify({'message': 'categories must be a list'}), 400
    if len(categories) > MAX_CATEGORIES:
        return jsonify({'message': f'At most {MAX_CATEGORIES} categories'}), 400

    cleaned = []
    for c in categories:
        kind = (c.get('kind') or '').strip().lower()
        name = (c.get('name') or '').strip()
        if kind not in BUDGET_CATEGORY_KINDS:
            return jsonify({'message': f'kind must be one of: {", ".join(BUDGET_CATEGORY_KINDS)}'}), 400
        if not name or len(name) > NAME_MAX:
            return jsonify({'message': f'Each category needs a name of {NAME_MAX} characters or fewer'}), 400
        try:
            amount = float(c.get('monthly_amount') or 0)
        except (TypeError, ValueError):
            return jsonify({'message': 'monthly_amount must be a number'}), 400
        cleaned.append({'kind': kind, 'name': name, 'monthly_amount': amount})

    budget = _get_or_create_budget(current_user.public_id)
    for existing in list(budget.categories):
        db.session.delete(existing)
    db.session.flush()
    for c in cleaned:
        db.session.add(FinanceBudgetCategory(budget_id=budget.id, **c))
    db.session.commit()
    return jsonify(BudgetSchema().dump(budget))
