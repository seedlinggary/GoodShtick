from marshmallow import Schema, fields


class GiveawayEntryActionSchema(Schema):
    id = fields.Int()
    campaign_id = fields.Int()
    action_key = fields.Str()
    label = fields.Str()
    description = fields.Str()
    action_url = fields.Str()
    entry_quantity = fields.Int()
    is_required = fields.Bool()
    verification_method = fields.Str()
    max_completions = fields.Int()
    is_enabled = fields.Bool()
    sort_order = fields.Int()
    created_at = fields.DateTime()


def make_entry_action_schema(many=False):
    return GiveawayEntryActionSchema(many=many)


class GiveawayCampaignSchema(Schema):
    id = fields.Int()
    name = fields.Str()
    slug = fields.Str()
    description = fields.Str()
    campaign_type = fields.Str()
    status = fields.Str()
    sites = fields.Raw()
    starts_at = fields.DateTime()
    ends_at = fields.DateTime()
    prize_details = fields.Str()
    terms_text = fields.Str()
    privacy_note = fields.Str()
    image_url = fields.Str()
    entry_rules = fields.Raw()
    marketing_campaign_id = fields.Int()
    created_at = fields.DateTime()
    updated_at = fields.DateTime()
    entry_actions = fields.Method('get_entry_actions')
    stats = fields.Method('get_stats')

    def get_entry_actions(self, obj):
        return make_entry_action_schema(many=True).dump(obj.entry_actions)

    def get_stats(self, obj):
        stats_by_campaign = (self.context or {}).get('stats_by_campaign') or {}
        return stats_by_campaign.get(obj.id, {
            'participants': 0, 'verified': 0, 'entries': 0,
            'referral_clicks': 0, 'qualified_referrals': 0, 'conversion_rate': 0,
        })


def make_campaign_schema(stats_by_campaign=None, many=False):
    """marshmallow 4 dropped the `context=` constructor kwarg -- set as a
    plain attribute after construction, same as backend/campaigns/schemas/
    campaign.py's make_campaign_schema."""
    schema = GiveawayCampaignSchema(many=many)
    schema.context = {'stats_by_campaign': stats_by_campaign or {}}
    return schema
