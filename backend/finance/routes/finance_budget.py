from datetime import datetime

from flask import Blueprint, jsonify, request

from config import db
from security import token_required
from backend.finance.modals.finance import (
    FinanceWatchlistItem, FinanceBudget, FinanceBudgetCategory, BUDGET_CATEGORY_KINDS,
    FinanceSavedScenario, CALCULATOR_KEYS,
)
from backend.finance.schemas.finance import WatchlistItemSchema, BudgetSchema, BudgetCardSchema, SavedScenarioSchema

finance_budget_api = Blueprint('finance_budget_api', __name__, url_prefix='/finance')

NAME_MAX = 80
MAX_CATEGORIES = 60
TITLE_MAX = 100
MAX_BUDGETS = 25
MAX_SCENARIOS_PER_CALCULATOR = 25


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


@finance_budget_api.route('/budgets', methods=['GET'])
@token_required
def list_budgets(current_user):
    rows = (FinanceBudget.query.filter_by(user_id=current_user.public_id)
            .order_by(FinanceBudget.updated_at.desc()).all())
    return jsonify({'budgets': BudgetCardSchema(many=True).dump(rows)})


@finance_budget_api.route('/budgets', methods=['POST'])
@token_required
def create_budget(current_user):
    if FinanceBudget.query.filter_by(user_id=current_user.public_id).count() >= MAX_BUDGETS:
        return jsonify({'message': f'You can keep at most {MAX_BUDGETS} budgets'}), 400
    title = ((request.get_json() or {}).get('title') or 'My Budget').strip()[:TITLE_MAX] or 'My Budget'
    budget = FinanceBudget(user_id=current_user.public_id, title=title)
    db.session.add(budget)
    db.session.commit()
    return jsonify(BudgetSchema().dump(budget)), 201


@finance_budget_api.route('/budgets/<int:budget_id>', methods=['GET'])
@token_required
def get_budget(current_user, budget_id):
    budget = FinanceBudget.query.filter_by(id=budget_id, user_id=current_user.public_id).first()
    if not budget:
        return jsonify({'message': 'Budget not found'}), 404
    return jsonify(BudgetSchema().dump(budget))


@finance_budget_api.route('/budgets/<int:budget_id>', methods=['PATCH'])
@token_required
def rename_budget(current_user, budget_id):
    """Also doubles as where the savings goal gets set/changed/cleared --
    both are single top-level fields on the budget itself, not another
    category row, so they share this one PATCH rather than each getting
    their own endpoint."""
    budget = FinanceBudget.query.filter_by(id=budget_id, user_id=current_user.public_id).first()
    if not budget:
        return jsonify({'message': 'Budget not found'}), 404
    body = request.get_json() or {}
    if 'title' in body:
        title = (body.get('title') or '').strip()
        if not title:
            return jsonify({'message': 'Title is required'}), 400
        budget.title = title[:TITLE_MAX]
    if 'savings_goal' in body:
        goal = body.get('savings_goal')
        if goal is None:
            budget.savings_goal = None
        else:
            try:
                budget.savings_goal = max(0.0, float(goal))
            except (TypeError, ValueError):
                return jsonify({'message': 'savings_goal must be a number'}), 400
    budget.updated_at = datetime.utcnow()
    db.session.commit()
    return jsonify(BudgetSchema().dump(budget))


@finance_budget_api.route('/budgets/<int:budget_id>', methods=['DELETE'])
@token_required
def delete_budget(current_user, budget_id):
    budget = FinanceBudget.query.filter_by(id=budget_id, user_id=current_user.public_id).first()
    if not budget:
        return jsonify({'message': 'Budget not found'}), 404
    db.session.delete(budget)
    db.session.commit()
    return jsonify({'message': 'Deleted'})


@finance_budget_api.route('/budgets/<int:budget_id>', methods=['PUT'])
@token_required
def replace_budget_categories(current_user, budget_id):
    """Replaces a budget's whole category list in one call -- the
    Budgeting page's form always edits/submits the full set at once, so
    there's no partial-update case to support (see FinanceBudget's own
    docstring)."""
    budget = FinanceBudget.query.filter_by(id=budget_id, user_id=current_user.public_id).first()
    if not budget:
        return jsonify({'message': 'Budget not found'}), 404

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

    for existing in list(budget.categories):
        db.session.delete(existing)
    db.session.flush()
    for c in cleaned:
        db.session.add(FinanceBudgetCategory(budget_id=budget.id, **c))
    budget.updated_at = datetime.utcnow()
    db.session.commit()
    return jsonify(BudgetSchema().dump(budget))


# ── Saved calculator scenarios (Compound Interest, Retirement, etc.) ──────

@finance_budget_api.route('/scenarios', methods=['GET'])
@token_required
def list_scenarios(current_user):
    calculator_key = (request.args.get('calculator') or '').strip()
    query = FinanceSavedScenario.query.filter_by(user_id=current_user.public_id)
    if calculator_key:
        query = query.filter_by(calculator_key=calculator_key)
    rows = query.order_by(FinanceSavedScenario.updated_at.desc()).all()
    return jsonify({'scenarios': SavedScenarioSchema(many=True).dump(rows)})


@finance_budget_api.route('/scenarios', methods=['POST'])
@token_required
def create_scenario(current_user):
    body = request.get_json() or {}
    calculator_key = (body.get('calculator_key') or '').strip()
    title = (body.get('title') or '').strip()
    inputs = body.get('inputs')
    if calculator_key not in CALCULATOR_KEYS:
        return jsonify({'message': f'calculator_key must be one of: {", ".join(CALCULATOR_KEYS)}'}), 400
    if not title or len(title) > TITLE_MAX:
        return jsonify({'message': f'Title is required and must be {TITLE_MAX} characters or fewer'}), 400
    if not isinstance(inputs, dict):
        return jsonify({'message': 'inputs must be an object'}), 400
    existing_count = FinanceSavedScenario.query.filter_by(
        user_id=current_user.public_id, calculator_key=calculator_key).count()
    if existing_count >= MAX_SCENARIOS_PER_CALCULATOR:
        return jsonify({'message': f'You can save at most {MAX_SCENARIOS_PER_CALCULATOR} scenarios per calculator'}), 400

    scenario = FinanceSavedScenario(user_id=current_user.public_id, calculator_key=calculator_key, title=title, inputs=inputs)
    db.session.add(scenario)
    db.session.commit()
    return jsonify(SavedScenarioSchema().dump(scenario)), 201


@finance_budget_api.route('/scenarios/<int:scenario_id>', methods=['PATCH'])
@token_required
def edit_scenario(current_user, scenario_id):
    scenario = FinanceSavedScenario.query.filter_by(id=scenario_id, user_id=current_user.public_id).first()
    if not scenario:
        return jsonify({'message': 'Scenario not found'}), 404
    body = request.get_json() or {}
    if 'title' in body:
        title = (body.get('title') or '').strip()
        if not title:
            return jsonify({'message': 'Title is required'}), 400
        scenario.title = title[:TITLE_MAX]
    if 'inputs' in body:
        if not isinstance(body.get('inputs'), dict):
            return jsonify({'message': 'inputs must be an object'}), 400
        scenario.inputs = body.get('inputs')
    scenario.updated_at = datetime.utcnow()
    db.session.commit()
    return jsonify(SavedScenarioSchema().dump(scenario))


@finance_budget_api.route('/scenarios/<int:scenario_id>', methods=['DELETE'])
@token_required
def delete_scenario(current_user, scenario_id):
    scenario = FinanceSavedScenario.query.filter_by(id=scenario_id, user_id=current_user.public_id).first()
    if not scenario:
        return jsonify({'message': 'Scenario not found'}), 404
    db.session.delete(scenario)
    db.session.commit()
    return jsonify({'message': 'Deleted'})
