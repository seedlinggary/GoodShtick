from marshmallow import Schema, fields

from backend.business.social.publishers import is_configured


class SocialAccountSchema(Schema):
    id = fields.Int()
    business_id = fields.Int()
    platform = fields.Str()
    external_account_name = fields.Str(allow_none=True)
    status = fields.Str()
    last_error = fields.Str(allow_none=True)
    connected_at = fields.DateTime(allow_none=True)


class SocialPostTargetSchema(Schema):
    id = fields.Int()
    platform = fields.Str()
    status = fields.Str()
    remote_post_id = fields.Str(allow_none=True)
    error = fields.Str(allow_none=True)
    posted_at = fields.DateTime(allow_none=True)


class SocialPostSchema(Schema):
    id = fields.Int()
    business_id = fields.Int()
    caption = fields.Str()
    media_url = fields.Method('get_media_url')
    link_url = fields.Str(allow_none=True)
    scheduled_at = fields.DateTime(allow_none=True)
    status = fields.Str()
    created_at = fields.DateTime()
    targets = fields.List(fields.Nested(SocialPostTargetSchema))

    def get_media_url(self, obj):
        from upload import get_public_url
        return get_public_url(obj.media) if obj.media else None


class PlatformStatusSchema(Schema):
    """One row per platform in the composer's connect screen -- whether this
    deployment even has app credentials configured, independent of whether
    this particular business has connected an account yet."""
    platform = fields.Str()
    configured = fields.Method('get_configured')
    connected = fields.Bool()
    account = fields.Nested(SocialAccountSchema, allow_none=True)
    mode = fields.Str()  # 'api' or 'share_sheet'

    def get_configured(self, obj):
        return is_configured(obj['platform'])
