from marshmallow import Schema, fields


class AlertSchema(Schema):
    """Never includes confirm_token/unsubscribe_token -- those only ever go
    out inside an emailed link (see routes/alert.py's emails), never in a
    JSON response a browser could read."""
    id = fields.Int()
    search_type = fields.Str()
    filters = fields.Str()
    label = fields.Str(allow_none=True)
    confirmed = fields.Bool()
    paused = fields.Bool()
    created_at = fields.DateTime()
    last_notified_at = fields.DateTime(allow_none=True)


alert_schema = AlertSchema()
alerts_schema = AlertSchema(many=True)
