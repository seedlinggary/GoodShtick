from marshmallow import Schema, fields


class NotificationSchema(Schema):
    id = fields.Int()
    type = fields.Str()
    message = fields.Str()
    link = fields.Str()
    is_read = fields.Bool()
    pub_date = fields.DateTime()


notification_schema = NotificationSchema()
notifications_schema = NotificationSchema(many=True)
