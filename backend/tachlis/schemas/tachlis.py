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
    category = fields.Str(allow_none=True)
    remote = fields.Bool(allow_none=True)
    user_id = fields.Str()
    user = fields.Nested(UserPublicSchema)
    pub_date = fields.DateTime()
    source_posted_at = fields.DateTime(allow_none=True)
    expires_at = fields.DateTime(allow_none=True)
    approved_to_publish = fields.Bool(allow_none=True)
    approved_by = fields.Str(allow_none=True)
    is_own_post = fields.Method('get_is_own_post')
    views_count = fields.Int()
    contact_taps = fields.Int()
    status = fields.Str()
    renewed_count = fields.Int()
    is_expired = fields.Bool()
    # Set only when a claimed business posted this via the Hiring tab (see
    # routes/tachlis_post.py's create_post) -- business_id alone, plus the
    # minimal name/slug a card/detail page needs to link to that business's
    # public profile (siteUrl('business', `/business/<slug>`) on the
    # frontend), not the full BusinessCardSchema.
    business_id = fields.Int(allow_none=True)
    business_name = fields.Method('get_business_name')
    business_slug = fields.Method('get_business_slug')

    def get_is_own_post(self, obj):
        uid = self.context.get('user_id')
        return bool(uid) and obj.user_id == uid

    def get_business_name(self, obj):
        return obj.business.name if obj.business else None

    def get_business_slug(self, obj):
        return obj.business.slug if obj.business else None


class TachlisPostCardSchema(Schema):
    """Lean post card for the board list — no contact info, just enough
    for a listing tile (title, type, location, compensation, snippet)."""
    id = fields.Int()
    post_type = fields.Str()
    title = fields.Str()
    body = fields.Str()
    location = fields.Str(allow_none=True)
    compensation = fields.Str(allow_none=True)
    category = fields.Str(allow_none=True)
    remote = fields.Bool(allow_none=True)
    user_id = fields.Str()
    user = fields.Nested(UserPublicSchema)
    pub_date = fields.DateTime()
    source_posted_at = fields.DateTime(allow_none=True)
    is_own_post = fields.Method('get_is_own_post')
    business_id = fields.Int(allow_none=True)
    business_name = fields.Method('get_business_name')
    business_slug = fields.Method('get_business_slug')

    def get_is_own_post(self, obj):
        uid = self.context.get('user_id')
        return bool(uid) and obj.user_id == uid

    def get_business_name(self, obj):
        return obj.business.name if obj.business else None

    def get_business_slug(self, obj):
        return obj.business.slug if obj.business else None


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
