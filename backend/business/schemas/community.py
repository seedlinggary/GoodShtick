from marshmallow import Schema, fields


class CommunitySchema(Schema):
    id = fields.Int()
    slug = fields.Str()
    name = fields.Str()
    description = fields.Str(allow_none=True)
    city = fields.Str()
    state = fields.Str(allow_none=True)
    country = fields.Str(allow_none=True)
    lat = fields.Float(allow_none=True)
    lng = fields.Float(allow_none=True)
    logo_url = fields.Method('get_logo_url')
    source_url = fields.Str(allow_none=True)
    source_name = fields.Str(allow_none=True)
    imported = fields.Bool()
    pub_date = fields.DateTime()
    eruv_status = fields.Str(allow_none=True)
    eruv_url = fields.Str(allow_none=True)
    eruv_map_image = fields.Str(allow_none=True)
    eruv_map_image_url = fields.Method('get_eruv_map_image_url')

    def get_logo_url(self, obj):
        if not obj.logo:
            return None
        from upload import get_public_url
        return get_public_url(obj.logo)

    def get_eruv_map_image_url(self, obj):
        if not obj.eruv_map_image:
            return None
        from upload import get_public_url
        return get_public_url(obj.eruv_map_image)


class MinyanSchema(Schema):
    id = fields.Int()
    business_id = fields.Int()
    tefilah = fields.Str()
    label = fields.Str(allow_none=True)
    days = fields.Str(allow_none=True)
    season = fields.Str(allow_none=True)
    fixed_time = fields.Method('get_fixed_time')  # "HH:MM", or null when this minyan is sun-relative
    relative_anchor = fields.Str(allow_none=True)
    relative_offset_minutes = fields.Int(allow_none=True)
    notes = fields.Str(allow_none=True)
    source_name = fields.Str()
    source_url = fields.Str(allow_none=True)
    pub_date = fields.DateTime()
    updated_at = fields.DateTime(allow_none=True)

    def get_fixed_time(self, obj):
        return obj.fixed_time.strftime('%H:%M') if obj.fixed_time else None
