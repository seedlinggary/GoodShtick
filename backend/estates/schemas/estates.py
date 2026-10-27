from marshmallow import Schema, fields

from upload import get_public_url


class ListingPhotoSchema(Schema):
    id = fields.Int()
    position = fields.Int()
    # Exposed (unlike Business.logo) so the edit form can round-trip the
    # existing photo list back to PATCH .../listings/<id> without re-uploading
    # -- see EstatesPhotoUpload.js, which only ever POSTs a *new* file once
    # per added photo and otherwise just reorders/drops these filenames.
    filename = fields.Str()
    url = fields.Method('get_url')

    def get_url(self, obj):
        return get_public_url(obj.filename)


class EstatesListingCardSchema(Schema):
    """Lean tile for the listings directory/map."""
    id = fields.Int()
    slug = fields.Str()
    listing_type = fields.Str()
    title = fields.Str()
    price = fields.Float(allow_none=True)
    currency = fields.Str()
    price_period = fields.Str(allow_none=True)
    neighborhood = fields.Str(allow_none=True)
    city = fields.Str(allow_none=True)
    state = fields.Str(allow_none=True)
    country = fields.Str(allow_none=True)
    lat = fields.Float(allow_none=True)
    lng = fields.Float(allow_none=True)
    bedrooms = fields.Float(allow_none=True)
    bathrooms = fields.Float(allow_none=True)
    size_value = fields.Float(allow_none=True)
    size_unit = fields.Str(allow_none=True)
    is_agent = fields.Bool(allow_none=True)
    cover_photo_url = fields.Method('get_cover_photo_url')
    is_expired = fields.Bool()
    expires_at = fields.DateTime(allow_none=True)
    pub_date = fields.DateTime()
    source_posted_at = fields.DateTime(allow_none=True)

    def get_cover_photo_url(self, obj):
        if not obj.photos:
            return None
        return get_public_url(obj.photos[0].filename)


class EstatesListingSchema(Schema):
    """Full profile -- detail page."""
    id = fields.Int()
    slug = fields.Str()
    listing_type = fields.Str()
    title = fields.Str()
    description = fields.Str(allow_none=True)

    price = fields.Float(allow_none=True)
    currency = fields.Str()
    price_period = fields.Str(allow_none=True)

    address = fields.Str(allow_none=True)
    neighborhood = fields.Str(allow_none=True)
    city = fields.Str(allow_none=True)
    state = fields.Str(allow_none=True)
    zip_code = fields.Str(allow_none=True)
    country = fields.Str(allow_none=True)
    lat = fields.Float(allow_none=True)
    lng = fields.Float(allow_none=True)

    bedrooms = fields.Float(allow_none=True)
    bathrooms = fields.Float(allow_none=True)
    size_value = fields.Float(allow_none=True)
    size_unit = fields.Str(allow_none=True)

    is_agent = fields.Bool(allow_none=True)
    contact_name = fields.Str(allow_none=True)
    contact_email = fields.Str(allow_none=True)
    contact_phone = fields.Str(allow_none=True)
    contact_whatsapp = fields.Str(allow_none=True)

    attributes = fields.Raw(allow_none=True)

    photos = fields.Method('get_photos')
    is_expired = fields.Bool()
    expires_at = fields.DateTime(allow_none=True)
    pub_date = fields.DateTime()
    renewed_count = fields.Int()
    views_count = fields.Int()

    created_by = fields.Str(allow_none=True)
    is_own_listing = fields.Method('get_is_own_listing')
    like_count = fields.Method('get_like_count')
    is_liked = fields.Method('get_is_liked')

    def __init__(self, current_user=None, **kwargs):
        super().__init__(**kwargs)
        self.current_user = current_user

    def get_photos(self, obj):
        return ListingPhotoSchema(many=True).dump(obj.photos)

    def get_is_own_listing(self, obj):
        return bool(self.current_user and obj.created_by == self.current_user.public_id)

    def get_like_count(self, obj):
        return len(obj.likes)

    def get_is_liked(self, obj):
        if not self.current_user:
            return False
        return any(like.user_id == self.current_user.public_id for like in obj.likes)


def make_listing_schema(current_user, many=False):
    return EstatesListingSchema(current_user=current_user, many=many)


# ── Group buy ─────────────────────────────────────────────────────────────

class GroupBuyPhotoSchema(Schema):
    id = fields.Int()
    position = fields.Int()
    filename = fields.Str()
    url = fields.Method('get_url')

    def get_url(self, obj):
        return get_public_url(obj.filename)


class EstatesGroupBuyCardSchema(Schema):
    id = fields.Int()
    slug = fields.Str()
    title = fields.Str()
    stage = fields.Str(allow_none=True)
    neighborhood = fields.Str(allow_none=True)
    city = fields.Str(allow_none=True)
    state = fields.Str(allow_none=True)
    country = fields.Str(allow_none=True)
    lat = fields.Float(allow_none=True)
    lng = fields.Float(allow_none=True)
    price_per_unit_estimate = fields.Float(allow_none=True)
    currency = fields.Str()
    total_units = fields.Int(allow_none=True)
    min_group_size = fields.Int(allow_none=True)
    expected_completion = fields.Str(allow_none=True)
    is_closed = fields.Bool()
    member_count = fields.Method('get_member_count')
    cover_photo_url = fields.Method('get_cover_photo_url')

    def get_member_count(self, obj):
        return len(obj.members)

    def get_cover_photo_url(self, obj):
        if not obj.photos:
            return None
        return get_public_url(obj.photos[0].filename)


class EstatesGroupBuySchema(Schema):
    id = fields.Int()
    slug = fields.Str()
    title = fields.Str()
    description = fields.Str(allow_none=True)
    developer_name = fields.Str(allow_none=True)
    stage = fields.Str(allow_none=True)

    address = fields.Str(allow_none=True)
    neighborhood = fields.Str(allow_none=True)
    city = fields.Str(allow_none=True)
    state = fields.Str(allow_none=True)
    country = fields.Str(allow_none=True)
    lat = fields.Float(allow_none=True)
    lng = fields.Float(allow_none=True)

    price_per_unit_estimate = fields.Float(allow_none=True)
    currency = fields.Str()
    total_units = fields.Int(allow_none=True)
    min_group_size = fields.Int(allow_none=True)
    expected_completion = fields.Str(allow_none=True)

    contact_name = fields.Str(allow_none=True)
    contact_email = fields.Str(allow_none=True)
    contact_phone = fields.Str(allow_none=True)
    contact_whatsapp = fields.Str(allow_none=True)

    photos = fields.Method('get_photos')
    pub_date = fields.DateTime()
    is_closed = fields.Bool()
    created_by = fields.Str(allow_none=True)

    member_count = fields.Method('get_member_count')
    is_own_group_buy = fields.Method('get_is_own_group_buy')
    is_member = fields.Method('get_is_member')
    can_manage = fields.Method('get_can_manage')
    members = fields.Method('get_members')

    def __init__(self, current_user=None, **kwargs):
        super().__init__(**kwargs)
        self.current_user = current_user

    def get_photos(self, obj):
        return GroupBuyPhotoSchema(many=True).dump(obj.photos)

    def get_member_count(self, obj):
        return len(obj.members)

    def get_is_own_group_buy(self, obj):
        return bool(self.current_user and obj.created_by == self.current_user.public_id)

    def get_is_member(self, obj):
        if not self.current_user:
            return False
        return any(m.user_id == self.current_user.public_id for m in obj.members)

    def get_can_manage(self, obj):
        return bool(self.current_user and (
            obj.created_by == self.current_user.public_id or self.current_user.is_boss
        ))

    # Only the organizer (or an admin) sees the member list -- everyone else
    # just gets member_count, see the model's own docstring.
    def get_members(self, obj):
        if not self.get_can_manage(obj):
            return None
        return [
            {
                'user_id': m.user_id,
                'note': m.note,
                'created_at': m.created_at.isoformat() if m.created_at else None,
                'email': m.user.email if m.user else None,
            }
            for m in obj.members
        ]


def make_group_buy_schema(current_user, many=False):
    return EstatesGroupBuySchema(current_user=current_user, many=many)
