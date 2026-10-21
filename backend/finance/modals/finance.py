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
    """One budget per user -- simplest useful version of the Budgeting page.
    Categories (income/expense lines) live in FinanceBudgetCategory;
    PUT /finance/budget replaces the whole category list wholesale rather
    than patching individual rows, since the form always submits the full
    current list anyway (see routes/finance_budget.py)."""
    __tablename__ = 'finance_budget'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(50), db.ForeignKey('user.public_id'), unique=True, nullable=False, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    categories = db.relationship('FinanceBudgetCategory', backref='budget', lazy=True,
                                  cascade='all, delete-orphan', order_by='FinanceBudgetCategory.id')
    user = db.relationship('User', backref=db.backref('finance_budget', uselist=False, lazy=True))

    def __init__(self, user_id):
        self.user_id = user_id


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
