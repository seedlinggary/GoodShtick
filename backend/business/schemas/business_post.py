from marshmallow import Schema, fields

from backend.shtick.schemas.shtick import UserPublicSchema
from backend.business.schemas.business import BusinessCardSchema
from upload import get_public_url


class BusinessPostSchema(Schema):
    id = fields.Int()
    business_id = fields.Int()
    business = fields.Nested(BusinessCardSchema)
    user_id = fields.Str()
    user = fields.Nested(UserPublicSchema)
    post_type = fields.Str()
    title = fields.Str()
    body = fields.Str()
    image_url = fields.Method('get_image_url')
    pub_date = fields.DateTime()
    expires_at = fields.DateTime(allow_none=True)
    approved_to_publish = fields.Bool()
    is_own_post = fields.Method('get_is_own_post')

    def get_image_url(self, obj):
        return get_public_url(obj.image) if obj.image else None

    def get_is_own_post(self, obj):
        uid = self.context.get('user_id')
        return bool(uid) and obj.user_id == uid


def make_business_post_schema(current_user=None, many=False):
    ctx = {'user_id': current_user.public_id if current_user else None}
    schema = BusinessPostSchema(many=many)
    schema.context = ctx
    return schema
