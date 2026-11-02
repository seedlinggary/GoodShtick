from marshmallow import Schema, fields

from upload import get_public_url


class MarketplacePhotoSchema(Schema):
    id = fields.Int()
    position = fields.Int()
    filename = fields.Str()
    url = fields.Method('get_url')

    def get_url(self, obj):
        return get_public_url(obj.filename)


class MarketplaceListingCardSchema(Schema):
    """Lean tile for the browse/search grid."""
    id = fields.Int()
    slug = fields.Str()
    title = fields.Str()
    category = fields.Str()
    subcategory = fields.Str(allow_none=True)
    condition = fields.Str(allow_none=True)
    price = fields.Float(allow_none=True)
    currency = fields.Str()
    is_free = fields.Bool()
    ships = fields.Bool()
    city = fields.Str(allow_none=True)
    state = fields.Str(allow_none=True)
    country = fields.Str(allow_none=True)
    lat = fields.Float(allow_none=True)
    lng = fields.Float(allow_none=True)
    cover_photo_url = fields.Method('get_cover_photo_url')
    is_expired = fields.Bool()
    pub_date = fields.DateTime()

    def get_cover_photo_url(self, obj):
        if not obj.photos:
            return None
        return get_public_url(obj.photos[0].filename)


class MarketplaceListingSchema(Schema):
    """Full detail page."""
    id = fields.Int()
    slug = fields.Str()
    title = fields.Str()
    description = fields.Str(allow_none=True)
    category = fields.Str()
    subcategory = fields.Str(allow_none=True)
    condition = fields.Str(allow_none=True)

    price = fields.Float(allow_none=True)
    currency = fields.Str()
    is_free = fields.Bool()
    ships = fields.Bool()

    address = fields.Str(allow_none=True)
    city = fields.Str(allow_none=True)
    state = fields.Str(allow_none=True)
    country = fields.Str(allow_none=True)
    lat = fields.Float(allow_none=True)
    lng = fields.Float(allow_none=True)

    contact_name = fields.Str(allow_none=True)
    contact_email = fields.Str(allow_none=True)
    contact_phone = fields.Str(allow_none=True)
    contact_whatsapp = fields.Str(allow_none=True)
    contact_link = fields.Str(allow_none=True)

    status = fields.Str()
    is_expired = fields.Bool()
    approved_to_publish = fields.Bool(allow_none=True)
    expires_at = fields.DateTime(allow_none=True)
    renewed_count = fields.Int()
    views_count = fields.Int()
    pub_date = fields.DateTime()

    created_by = fields.Str(allow_none=True)
    photos = fields.Method('get_photos')

    def get_photos(self, obj):
        return MarketplacePhotoSchema(many=True).dump(obj.photos)
