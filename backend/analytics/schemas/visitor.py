from marshmallow import Schema, fields


class VisitorSessionSchema(Schema):
    """Not currently used to serialize raw rows over the wire (the dashboard
    route returns hand-built aggregate dicts, not ORM rows) -- kept here for
    parity with the rest of the codebase's model/route/schema layout, and in
    case a future 'raw session list' admin view wants it."""
    id = fields.Int()
    anonymous_id = fields.Str()
    user_id = fields.Str(allow_none=True)
    country = fields.Str(allow_none=True)
    first_seen = fields.DateTime()
    last_seen = fields.DateTime()
    page_view_count = fields.Int()
    is_localhost = fields.Bool()


visitor_session_schema = VisitorSessionSchema()
visitor_sessions_schema = VisitorSessionSchema(many=True)
