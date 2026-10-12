from marshmallow import Schema, fields


class FeedbackSchema(Schema):
    id = fields.Int()
    business_id = fields.Int()
    user_id = fields.Str()
    stars = fields.Int()
    comment = fields.Str(allow_none=True)
    created_at = fields.DateTime()
