from marshmallow import Schema, fields

from upload import get_public_url


class NewsArticleCardSchema(Schema):
    """Lean tile for the feed."""
    id = fields.Int()
    slug = fields.Str()
    title = fields.Str()
    category = fields.Str()
    excerpt = fields.Str(allow_none=True)
    image_url = fields.Method('get_image_url')
    source_name = fields.Str(allow_none=True)
    imported = fields.Bool()
    pub_date = fields.DateTime()
    like_count = fields.Method('get_like_count')

    def get_image_url(self, obj):
        return get_public_url(obj.image) if obj.image else None

    def get_like_count(self, obj):
        return len(obj.likes)


class NewsArticleSchema(Schema):
    """Full detail view."""
    id = fields.Int()
    slug = fields.Str()
    title = fields.Str()
    excerpt = fields.Str(allow_none=True)
    body_text = fields.Str(allow_none=True)
    image_url = fields.Method('get_image_url')
    category = fields.Str()
    imported = fields.Bool()
    source_url = fields.Str(allow_none=True)
    source_name = fields.Str(allow_none=True)
    approved_to_publish = fields.Bool(allow_none=True)
    pub_date = fields.DateTime()
    views_count = fields.Int()
    created_by = fields.Str(allow_none=True)
    is_own_post = fields.Method('get_is_own_post')
    like_count = fields.Method('get_like_count')
    is_liked = fields.Method('get_is_liked')
    can_manage = fields.Method('get_can_manage')

    def __init__(self, current_user=None, **kwargs):
        super().__init__(**kwargs)
        self.current_user = current_user

    def get_image_url(self, obj):
        return get_public_url(obj.image) if obj.image else None

    def get_is_own_post(self, obj):
        return bool(self.current_user and obj.created_by == self.current_user.public_id)

    def get_like_count(self, obj):
        return len(obj.likes)

    def get_is_liked(self, obj):
        if not self.current_user:
            return False
        return any(like.user_id == self.current_user.public_id for like in obj.likes)

    def get_can_manage(self, obj):
        if not self.current_user:
            return False
        if self.current_user.is_boss:
            return True
        return obj.created_by == self.current_user.public_id


def make_article_schema(current_user, many=False):
    return NewsArticleSchema(current_user=current_user, many=many)
