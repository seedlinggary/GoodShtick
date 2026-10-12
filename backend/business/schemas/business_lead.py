from marshmallow import Schema, fields


class LeadSchema(Schema):
    id = fields.Int()
    business_id = fields.Int()
    name = fields.Str()
    email = fields.Str()
    phone = fields.Str(allow_none=True)
    message = fields.Str()
    status = fields.Str()
    created_at = fields.DateTime()
