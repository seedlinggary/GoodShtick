from marshmallow import Schema, fields

from upload import get_public_url


class TorahPostPhotoSchema(Schema):
    id = fields.Int()
    position = fields.Int()
    filename = fields.Str()  # exposed for edit-form round-tripping, same reasoning as estates' ListingPhotoSchema
    url = fields.Method('get_url')

    def get_url(self, obj):
        return get_public_url(obj.filename)


class TorahPostCardSchema(Schema):
    """Lean tile for the feed."""
    id = fields.Int()
    slug = fields.Str()
    post_type = fields.Str()
    title = fields.Str()
    category = fields.Str()
    cover_photo_url = fields.Method('get_cover_photo_url')
    youtube_video_id = fields.Str(allow_none=True)
    excerpt = fields.Method('get_excerpt')
    pub_date = fields.DateTime()
    like_count = fields.Method('get_like_count')

    def get_cover_photo_url(self, obj):
        if not obj.photos:
            return None
        return get_public_url(obj.photos[0].filename)

    def get_excerpt(self, obj):
        if not obj.body_text:
            return None
        text = obj.body_text.strip()
        return text if len(text) <= 160 else f'{text[:159].rstrip()}…'

    def get_like_count(self, obj):
        return len(obj.likes)


class TorahPostSchema(Schema):
    """Full detail view."""
    id = fields.Int()
    slug = fields.Str()
    post_type = fields.Str()
    title = fields.Str()
    body_text = fields.Str(allow_none=True)
    youtube_video_id = fields.Str(allow_none=True)
    category = fields.Str()
    photos = fields.Method('get_photos')
    pub_date = fields.DateTime()
    views_count = fields.Int()
    created_by = fields.Str(allow_none=True)
    is_own_post = fields.Method('get_is_own_post')
    like_count = fields.Method('get_like_count')
    is_liked = fields.Method('get_is_liked')

    def __init__(self, current_user=None, **kwargs):
        super().__init__(**kwargs)
        self.current_user = current_user

    def get_photos(self, obj):
        return TorahPostPhotoSchema(many=True).dump(obj.photos)

    def get_is_own_post(self, obj):
        return bool(self.current_user and obj.created_by == self.current_user.public_id)

    def get_like_count(self, obj):
        return len(obj.likes)

    def get_is_liked(self, obj):
        if not self.current_user:
            return False
        return any(like.user_id == self.current_user.public_id for like in obj.likes)


def make_post_schema(current_user, many=False):
    return TorahPostSchema(current_user=current_user, many=many)


class SourceSheetItemSchema(Schema):
    id = fields.Int()
    position = fields.Int()
    item_type = fields.Str()
    custom_title = fields.Str(allow_none=True)
    ref = fields.Str(allow_none=True)
    he_text = fields.Raw(allow_none=True)
    en_text = fields.Raw(allow_none=True)
    note_text = fields.Str(allow_none=True)


class SourceSheetCardSchema(Schema):
    """Lean row for sheet listings (my sheets / browse public)."""
    id = fields.Int()
    title = fields.Str()
    is_public = fields.Bool()
    created_at = fields.DateTime()
    updated_at = fields.DateTime()
    item_count = fields.Method('get_item_count')
    author_name = fields.Method('get_author_name')
    forked_from_id = fields.Int(allow_none=True)

    def get_item_count(self, obj):
        return len(obj.items)

    def get_author_name(self, obj):
        return obj.creator.profile_name if obj.creator else None


class SourceSheetSchema(Schema):
    id = fields.Int()
    title = fields.Str()
    is_public = fields.Bool()
    created_by = fields.Str()
    created_at = fields.DateTime()
    updated_at = fields.DateTime()
    forked_from_id = fields.Int(allow_none=True)
    items = fields.Method('get_items')
    is_own_sheet = fields.Method('get_is_own_sheet')
    author_name = fields.Method('get_author_name')

    def __init__(self, current_user=None, **kwargs):
        super().__init__(**kwargs)
        self.current_user = current_user

    def get_items(self, obj):
        return SourceSheetItemSchema(many=True).dump(obj.items)

    def get_is_own_sheet(self, obj):
        return bool(self.current_user and obj.created_by == self.current_user.public_id)

    def get_author_name(self, obj):
        return obj.creator.profile_name if obj.creator else None


def make_sheet_schema(current_user, many=False):
    return SourceSheetSchema(current_user=current_user, many=many)
