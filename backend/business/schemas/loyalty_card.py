from marshmallow import Schema, fields


class LoyaltyCardSchema(Schema):
    id = fields.Int()
    business_id = fields.Int()
    customer_code = fields.Str()
    stamps = fields.Int()
    rewards_redeemed = fields.Int()
    created_at = fields.DateTime()
    updated_at = fields.DateTime()
