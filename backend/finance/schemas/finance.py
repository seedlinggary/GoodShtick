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
    updated_at = fields.DateTime(allow_none=True)
    categories = fields.Nested(BudgetCategorySchema, many=True)
