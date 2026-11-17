from marshmallow import Schema, fields


class NewsTickerItemSchema(Schema):
    id = fields.Int()
    text = fields.Str()
    link_url = fields.Str(allow_none=True)
    is_active = fields.Bool()
    created_at = fields.DateTime()
