from marshmallow import Schema, fields

from backend.business.schemas.business import BusinessCardSchema


class FollowSchema(Schema):
    id = fields.Int()
    business_id = fields.Int()
    user_id = fields.Str()
    created_at = fields.DateTime()
    business = fields.Nested(BusinessCardSchema)
