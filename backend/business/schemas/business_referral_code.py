from marshmallow import Schema, fields

from backend.shtick.schemas.shtick import UserPublicSchema


class ReferralUseSchema(Schema):
    id = fields.Int()
    referred_user = fields.Nested(UserPublicSchema)
    created_at = fields.DateTime()


class ReferralCodeSchema(Schema):
    id = fields.Int()
    business_id = fields.Int()
    code = fields.Str()
    created_at = fields.DateTime()
    use_count = fields.Method('get_use_count')
    uses = fields.List(fields.Nested(ReferralUseSchema))

    def get_use_count(self, obj):
        return len(obj.uses)
