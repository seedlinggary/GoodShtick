from urllib.parse import urlsplit

from marshmallow import Schema, fields


class CampaignLinkSchema(Schema):
    id = fields.Int()
    campaign_id = fields.Int()
    code = fields.Str()
    label = fields.Str()
    destination_url = fields.Str()
    is_active = fields.Bool()
    created_at = fields.DateTime()
    tracked_url = fields.Method('get_tracked_url')
    stats = fields.Method('get_stats')

    def get_tracked_url(self, obj):
        """Served from the SAME host as destination_url (e.g.
        www.gutcommunity.com), not the backend's own domain -- the frontend
        rewrites /campaigns/r/<code> on every site domain through to this
        same backend route (see good-shtick/vercel.json +
        good-shtick/api/campaign-redirect.js), so a link someone shares for
        a given site looks like it belongs to that site. Falls back to the
        backend's own host only if destination_url is somehow not a full
        absolute URL (shouldn't happen -- create_link/update_link require
        one)."""
        parts = urlsplit(obj.destination_url or '')
        if parts.scheme and parts.netloc:
            return f'{parts.scheme}://{parts.netloc}/campaigns/r/{obj.code}'
        api_base = (self.context or {}).get('api_base', '')
        return f'{api_base}/campaigns/r/{obj.code}'

    def get_stats(self, obj):
        stats_by_link = (self.context or {}).get('stats_by_link') or {}
        return stats_by_link.get(obj.id, {'clicks': 0, 'visitors': 0, 'signups': 0})


class MarketingCampaignSchema(Schema):
    id = fields.Int()
    name = fields.Str()
    description = fields.Str()
    status = fields.Str()
    created_at = fields.DateTime()
    links = fields.Method('get_links')
    totals = fields.Method('get_totals')

    def get_links(self, obj):
        # Deliberately NOT fields.Nested(CampaignLinkSchema) -- marshmallow 4
        # gives a field.Nested's auto-instantiated child schema no context
        # at all (not even an empty default; reading self.context on it
        # raises AttributeError), so it can never see api_base/stats_by_link.
        # Building it explicitly through make_link_schema (same helper the
        # standalone link endpoints use) sidesteps that entirely.
        ctx = self.context or {}
        schema = make_link_schema(ctx.get('api_base', ''), ctx.get('stats_by_link') or {}, many=True)
        return schema.dump(obj.links)

    def get_totals(self, obj):
        stats_by_link = (self.context or {}).get('stats_by_link') or {}
        totals = {'clicks': 0, 'visitors': 0, 'signups': 0}
        for link in obj.links:
            s = stats_by_link.get(link.id, {'clicks': 0, 'visitors': 0, 'signups': 0})
            for k in totals:
                totals[k] += s.get(k, 0)
        return totals


def make_campaign_schema(api_base, stats_by_link, many=False):
    """marshmallow 4 removed the `context=` constructor kwarg (see
    backend/tachlis/schemas/tachlis.py's make_tachlis_post_schema for the
    same pattern) -- context has to be set as a plain attribute after
    construction, never passed into Cls(...)."""
    schema = MarketingCampaignSchema(many=many)
    schema.context = {'api_base': api_base, 'stats_by_link': stats_by_link}
    return schema


def make_link_schema(api_base, stats_by_link, many=False):
    schema = CampaignLinkSchema(many=many)
    schema.context = {'api_base': api_base, 'stats_by_link': stats_by_link}
    return schema
