from marshmallow import Schema, fields

from backend.business.schemas.business_post import BusinessPostSchema


class RedemptionSchema(Schema):
    id = fields.Int()
    business_post_id = fields.Int()
    business_id = fields.Int()
    code = fields.Str()
    status = fields.Str()
    issued_at = fields.DateTime()
    redeemed_at = fields.DateTime(allow_none=True)
    post = fields.Nested(BusinessPostSchema)
