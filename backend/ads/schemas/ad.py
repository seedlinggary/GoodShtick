from marshmallow import Schema, fields

from upload import get_public_url


def _safe_image_url(obj):
    try:
        return get_public_url(obj.image_name) if obj.image_name else None
    except Exception:
        return None


class AdSchema(Schema):
    """Full schema — superadmin management view."""
    id = fields.Int()
    name = fields.Str()
    advertiser_name = fields.Str()
    status = fields.Str()
    image_name = fields.Str()
    image_url = fields.Method('get_image_url')
    headline = fields.Str()
    body_text = fields.Str()
    cta_label = fields.Str()
    destination_type = fields.Str()
    destination_value = fields.Str()
    placement = fields.Str()
    target_age_min = fields.Int()
    target_age_max = fields.Int()
    target_gender = fields.Str()
    target_countries = fields.Str()
    start_date = fields.DateTime()
    end_date = fields.DateTime()
    weight = fields.Int()
    impression_count = fields.Int()
    click_count = fields.Int()
    created_by = fields.Str()
    pub_date = fields.DateTime()
    updated_at = fields.DateTime()

    def get_image_url(self, obj):
        return _safe_image_url(obj)


class AdServeSchema(Schema):
    """Lean, public-safe schema for serving an ad to a visitor — no targeting internals, no stats."""
    id = fields.Int()
    advertiser_name = fields.Str()
    image_url = fields.Method('get_image_url')
    headline = fields.Str()
    body_text = fields.Str()
    cta_label = fields.Str()
    placement = fields.Str()

    def get_image_url(self, obj):
        return _safe_image_url(obj)


ad_schema = AdSchema()
ads_schema = AdSchema(many=True)
ad_serve_schema = AdServeSchema()
