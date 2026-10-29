from marshmallow import Schema, fields


class AuditLogSchema(Schema):
    id = fields.Int()
    actor_public_id = fields.Str(allow_none=True)
    actor_name = fields.Method('get_actor_name')
    action = fields.Str()
    target_type = fields.Str(allow_none=True)
    target_id = fields.Str(allow_none=True)
    details = fields.Str(allow_none=True)
    created_at = fields.DateTime()

    def get_actor_name(self, obj):
        return obj.actor.profile_name if obj.actor else None


audit_log_schema = AuditLogSchema()
audit_logs_schema = AuditLogSchema(many=True)
