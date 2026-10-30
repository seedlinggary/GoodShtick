from marshmallow import Schema, fields


class LoginLogSchema(Schema):
    id = fields.Int()
    user_id = fields.Str(allow_none=True)
    profile_name = fields.Method('get_profile_name')
    email_attempted = fields.Str(allow_none=True)
    site = fields.Str(allow_none=True)
    method = fields.Str()
    success = fields.Bool()
    ip_address = fields.Str(allow_none=True)
    user_agent = fields.Str(allow_none=True)
    created_at = fields.DateTime()

    def get_profile_name(self, obj):
        return obj.user.profile_name if obj.user else None


login_log_schema = LoginLogSchema()
login_logs_schema = LoginLogSchema(many=True)
