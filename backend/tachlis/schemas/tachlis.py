from marshmallow import Schema, fields

from backend.shtick.schemas.shtick import UserPublicSchema


class TachlisPostSchema(Schema):
    """Full post — used on the detail page and in admin listings."""
    id = fields.Int()
    post_type = fields.Str()
    title = fields.Str()
    body = fields.Str()
    contact = fields.Str()
    location = fields.Str(allow_none=True)
    compensation = fields.Str(allow_none=True)
    user_id = fields.Str()
    user = fields.Nested(UserPublicSchema)
    pub_date = fields.DateTime()
    expires_at = fields.DateTime(allow_none=True)
    approved_to_publish = fields.Bool(allow_none=True)
    approved_by = fields.Str(allow_none=True)
    is_own_post = fields.Method('get_is_own_post')

    def get_is_own_post(self, obj):
        uid = self.context.get('user_id')
        return bool(uid) and obj.user_id == uid


class TachlisPostCardSchema(Schema):
    """Lean post card for the board list — no contact info, just enough
    for a listing tile (title, type, location, compensation, snippet)."""
    id = fields.Int()
    post_type = fields.Str()
    title = fields.Str()
    body = fields.Str()
    location = fields.Str(allow_none=True)
    compensation = fields.Str(allow_none=True)
    user_id = fields.Str()
    user = fields.Nested(UserPublicSchema)
    pub_date = fields.DateTime()
    is_own_post = fields.Method('get_is_own_post')

    def get_is_own_post(self, obj):
        uid = self.context.get('user_id')
        return bool(uid) and obj.user_id == uid


def make_tachlis_post_schema(current_user=None, many=False, card=False):
    """Build a post schema bound to the viewer (for `is_own_post`).

    marshmallow 4 removed the `context=` constructor kwarg present in
    marshmallow 3 — `context` is still a plain instance attribute, it just
    has to be set after construction rather than passed in. NEVER call
    Cls(many=many, context=ctx) here.
    """
    ctx = {'user_id': current_user.public_id if current_user else None}
    cls = TachlisPostCardSchema if card else TachlisPostSchema
    schema = cls(many=many)
    schema.context = ctx
    return schema
