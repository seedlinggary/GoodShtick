from marshmallow import Schema, fields

from upload import get_public_url


class UserPublicSchema(Schema):
    public_id = fields.Str()
    profile_name = fields.Str()
    role = fields.Str()


class GeneralcSchema(Schema):
    id = fields.Int()
    name = fields.Str()


class PictureSchema(Schema):
    id = fields.Int()
    name = fields.Str()
    url = fields.Method('get_image_url')

    def get_image_url(self, obj):
        try:
            return get_public_url(obj.name)
        except Exception:
            return None


class UrlSchema(Schema):
    id = fields.Int()
    name = fields.Str()


class ContentSchema(Schema):
    id = fields.Int()
    stuff = fields.Str()


class CommentSchema(Schema):
    id = fields.Int()
    text = fields.Str()
    pub_date = fields.DateTime()
    user_id = fields.Str()
    shtick_id = fields.Int()
    approved_to_publish = fields.Bool()
    user = fields.Nested(UserPublicSchema)


class LikeSchema(Schema):
    id = fields.Int()
    pub_date = fields.DateTime()
    shtick_id = fields.Int()
    user_id = fields.Str()


class ShtickSchema(Schema):
    """Full schema — used in admin views where comments are needed."""
    id = fields.Int()
    pub_date = fields.DateTime()
    caption = fields.Str()
    credit = fields.Str()
    approved_to_publish = fields.Bool()
    view_count = fields.Int()
    specific_category = fields.Str()
    user_id = fields.Str()
    approved_by = fields.Str()
    user = fields.Nested(UserPublicSchema)
    approver = fields.Nested(UserPublicSchema)
    generalc_id = fields.Int()
    generalc = fields.Nested(GeneralcSchema)
    categories = fields.Nested(GeneralcSchema, many=True)
    content = fields.Nested(ContentSchema)
    picture = fields.Nested(PictureSchema)
    url = fields.Nested(UrlSchema)
    likes = fields.Nested(LikeSchema, many=True)
    comments = fields.Nested(CommentSchema, many=True)


class ShtickFeedSchema(Schema):
    """Lean schema for the public feed — omits comments (loaded on-demand by Comments.js)."""
    id = fields.Int()
    pub_date = fields.DateTime()
    caption = fields.Str()
    credit = fields.Str()
    approved_to_publish = fields.Bool()
    view_count = fields.Int()
    specific_category = fields.Str()
    user_id = fields.Str()
    user = fields.Nested(UserPublicSchema)
    generalc_id = fields.Int()
    generalc = fields.Nested(GeneralcSchema)
    categories = fields.Nested(GeneralcSchema, many=True)
    content = fields.Nested(ContentSchema)
    picture = fields.Nested(PictureSchema)
    url = fields.Nested(UrlSchema)
    likes = fields.Nested(LikeSchema, many=True)


shtick_schema = ShtickSchema()
shticks_schema = ShtickSchema(many=True)
shtick_feed_schema = ShtickFeedSchema()
shticks_feed_schema = ShtickFeedSchema(many=True)
comment_schema = CommentSchema()
comments_schema = CommentSchema(many=True)
