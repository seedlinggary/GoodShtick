from marshmallow import Schema, fields


class WatchlistItemSchema(Schema):
    id = fields.Int()
    symbol = fields.Str()
    created_at = fields.DateTime()


class BudgetCategorySchema(Schema):
    id = fields.Int()
    kind = fields.Str()
    name = fields.Str()
    monthly_amount = fields.Float()


class BudgetSchema(Schema):
    id = fields.Int()
    title = fields.Str()
    savings_goal = fields.Float(allow_none=True)
    created_at = fields.DateTime(allow_none=True)
    updated_at = fields.DateTime(allow_none=True)
    categories = fields.Nested(BudgetCategorySchema, many=True)


class BudgetCardSchema(Schema):
    """Lean row for the budget list -- no categories, plus computed totals
    so the list itself is useful without opening each one."""
    id = fields.Int()
    title = fields.Str()
    savings_goal = fields.Float(allow_none=True)
    updated_at = fields.DateTime(allow_none=True)
    total_income = fields.Method('get_total_income')
    total_expenses = fields.Method('get_total_expenses')

    def get_total_income(self, obj):
        return sum(c.monthly_amount for c in obj.categories if c.kind == 'income')

    def get_total_expenses(self, obj):
        return sum(c.monthly_amount for c in obj.categories if c.kind == 'expense')


class SavedScenarioSchema(Schema):
    id = fields.Int()
    calculator_key = fields.Str()
    title = fields.Str()
    inputs = fields.Raw()
    created_at = fields.DateTime(allow_none=True)
    updated_at = fields.DateTime(allow_none=True)
