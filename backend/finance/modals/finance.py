from datetime import datetime

from config import db

BUDGET_CATEGORY_KINDS = ('income', 'expense')


class FinanceDataCache(db.Model):
    """Generic cache for Alpha Vantage responses, keyed by a string like
    'quote:AAPL' or 'indicator:CPI'. Alpha Vantage's free tier is a hard
    25-requests/day, 5/minute cap *shared across every visitor to the site*
    -- without this cache, a handful of page loads would exhaust the whole
    day's quota. See routes/finance_market.py's CACHE_TTL for how long each
    kind of data is considered fresh before it's worth spending another
    request on."""
    __tablename__ = 'finance_data_cache'

    id = db.Column(db.Integer, primary_key=True)
    cache_key = db.Column(db.String(120), unique=True, nullable=False, index=True)
    payload = db.Column(db.JSON, nullable=False)
    fetched_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def __init__(self, cache_key, payload):
        self.cache_key = cache_key
        self.payload = payload


class FinanceWatchlistItem(db.Model):
    """A ticker symbol a user wants to keep an eye on -- the Investing
    page's watchlist."""
    __tablename__ = 'finance_watchlist_item'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(50), db.ForeignKey('user.public_id'), nullable=False, index=True)
    symbol = db.Column(db.String(20), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('user_id', 'symbol', name='uq_finance_watchlist_user_symbol'),
    )

    user = db.relationship('User', backref=db.backref('finance_watchlist_items', lazy=True))

    def __init__(self, user_id, symbol):
        self.user_id = user_id
        self.symbol = symbol.upper()


class FinanceBudget(db.Model):
    """A named budget -- a user can keep several (e.g. "Household", "Side
    business", "If we move to Lakewood") rather than just one, since real
    budgeting usually means comparing a few different pictures side by
    side, not committing to a single live one. Categories (income/expense
    lines) live in FinanceBudgetCategory; PUT /finance/budgets/<id>
    replaces a budget's whole category list wholesale rather than patching
    individual rows, since the form always submits the full current list
    anyway (see routes/finance_budget.py)."""
    __tablename__ = 'finance_budget'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(50), db.ForeignKey('user.public_id'), nullable=False, index=True)
    title = db.Column(db.String(100), nullable=False, default='My Budget', server_default='My Budget')
    # A standalone target, separate from the income/expense categories --
    # "how much do you PLAN to save" is a single goal to measure actual
    # leftover (income - expenses) against, not another transaction line
    # to add up. Null until the user sets one (no goal to compare against
    # yet, distinct from a goal of literally $0).
    savings_goal = db.Column(db.Float, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    categories = db.relationship('FinanceBudgetCategory', backref='budget', lazy=True,
                                  cascade='all, delete-orphan', order_by='FinanceBudgetCategory.id')
    user = db.relationship('User', backref=db.backref('finance_budgets', lazy=True))

    def __init__(self, user_id, title='My Budget'):
        self.user_id = user_id
        self.title = title


CALCULATOR_KEYS = ('compound', 'retirement', 'debt', 'emergency', 'goal', 'coast_fire', 'fire_number')


class FinanceSavedScenario(db.Model):
    """A named, saved set of inputs for one of the Calculators-page tools --
    "save for many different items for many different lengths" means one
    person wants several saved runs of the SAME calculator (e.g. three
    separate Compound Interest scenarios: a house downpayment, a car, a
    kid's bar mitzvah), not just one live set of numbers. `inputs` is a
    free-form JSON blob matching whatever fields that specific calculator's
    own React state shape uses -- deliberately generic (one table for every
    calculator) rather than a bespoke table per calculator, since a saved
    scenario here is just "remember these numbers under this name," with no
    server-side computation or validation of what's inside beyond that."""
    __tablename__ = 'finance_saved_scenario'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(50), db.ForeignKey('user.public_id'), nullable=False, index=True)
    calculator_key = db.Column(db.String(30), nullable=False, index=True)  # CALCULATOR_KEYS
    title = db.Column(db.String(100), nullable=False)
    inputs = db.Column(db.JSON, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = db.relationship('User', backref=db.backref('finance_saved_scenarios', lazy=True))

    def __init__(self, user_id, calculator_key, title, inputs):
        self.user_id = user_id
        self.calculator_key = calculator_key
        self.title = title
        self.inputs = inputs


class FinanceBudgetCategory(db.Model):
    __tablename__ = 'finance_budget_category'

    id = db.Column(db.Integer, primary_key=True)
    budget_id = db.Column(db.Integer, db.ForeignKey('finance_budget.id'), nullable=False, index=True)
    kind = db.Column(db.String(10), nullable=False)  # BUDGET_CATEGORY_KINDS
    name = db.Column(db.String(80), nullable=False)
    monthly_amount = db.Column(db.Float, nullable=False, default=0)

    def __init__(self, budget_id, kind, name, monthly_amount=0):
        self.budget_id = budget_id
        self.kind = kind
        self.name = name
        self.monthly_amount = monthly_amount
