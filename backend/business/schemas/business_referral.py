from marshmallow import Schema, fields

from backend.shtick.schemas.shtick import UserPublicSchema


class ReferralReplySchema(Schema):
    id = fields.Int()
    post_id = fields.Int()
    business_id = fields.Int()
    user_id = fields.Str()
    user = fields.Nested(UserPublicSchema)
    body = fields.Str()
    created_at = fields.DateTime()


class ReferralPostSchema(Schema):
    id = fields.Int()
    business_id = fields.Int()
    business_name = fields.Method('get_business_name')
    user_id = fields.Str()
    user = fields.Nested(UserPublicSchema)
    title = fields.Str()
    body = fields.Str()
    created_at = fields.DateTime()
    replies = fields.List(fields.Nested(ReferralReplySchema))

    def get_business_name(self, obj):
        return obj.business.name if obj.business else None
