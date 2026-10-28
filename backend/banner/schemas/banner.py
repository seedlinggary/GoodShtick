from marshmallow import Schema, fields


class SiteBannerSchema(Schema):
    enabled = fields.Bool()
    message = fields.Str(allow_none=True)
    link_url = fields.Str(allow_none=True)
    link_text = fields.Str(allow_none=True)
    style = fields.Str()
    updated_at = fields.DateTime()


site_banner_schema = SiteBannerSchema()
