from marshmallow import Schema, fields

from backend.shtick.schemas.shtick import UserPublicSchema
from backend.business.modals.business import FOOD_CATEGORIES
from backend.business.social.holidays import auto_closure_reason
from upload import get_public_url


class LocationSchema(Schema):
    id = fields.Int()
    business_id = fields.Int()
    location_type = fields.Str()
    address = fields.Str(allow_none=True)
    city = fields.Str(allow_none=True)
    state = fields.Str(allow_none=True)
    zip_code = fields.Str(allow_none=True)
    country = fields.Str(allow_none=True)
    lat = fields.Float(allow_none=True)
    lng = fields.Float(allow_none=True)
    phone = fields.Str(allow_none=True)
    email = fields.Str(allow_none=True)
    hours = fields.Raw(allow_none=True)
    kashrut = fields.Str(allow_none=True)
    attributes = fields.Raw(allow_none=True)
    is_primary = fields.Bool()
    holiday_closed_reason = fields.Method('get_holiday_closed_reason')

    def get_holiday_closed_reason(self, obj):
        if not (obj.attributes or {}).get('auto_holiday_closure'):
            return None
        return auto_closure_reason()


class BusinessCardSchema(Schema):
    """Lean tile for directory/map listings."""
    id = fields.Int()
    slug = fields.Str()
    name = fields.Str()
    logo_url = fields.Method('get_logo_url')
    category = fields.Str()
    is_food = fields.Method('get_is_food')
    website = fields.Str(allow_none=True)
    rating_avg = fields.Float()
    rating_count = fields.Int()
    is_claimed = fields.Bool()
    imported = fields.Bool()
    types = fields.Method('get_types')
    is_boosted = fields.Method('get_is_boosted')
    primary_location = fields.Method('get_primary_location')
    community_info = fields.Method('get_community_info')
    pub_date = fields.DateTime()

    def get_logo_url(self, obj):
        return get_public_url(obj.logo) if obj.logo else None

    def get_is_food(self, obj):
        return obj.category in FOOD_CATEGORIES

    def get_types(self, obj):
        return (obj.attributes or {}).get('types') or []

    # A lean, named allowlist rather than dumping the raw attributes blob --
    # these are specifically the extra fields the "Find a Community" feature
    # surfaces (shul rabbi/hashkafa/size, mikvah accessibility/scheduling),
    # sourced from the OU Communities API and mikvah.org. Anything else an
    # owner or another import stashes in attributes stays internal.
    def get_community_info(self, obj):
        attrs = obj.attributes or {}
        keys = ('rabbi_name', 'hashkafa', 'families_count', 'wheelchair_accessible', 'mikvah_schedule')
        info = {k: attrs[k] for k in keys if attrs.get(k) not in (None, '')}
        return info or None

    def get_is_boosted(self, obj):
        from datetime import datetime
        return bool(obj.boost_until and obj.boost_until > datetime.utcnow())

    def get_primary_location(self, obj):
        if not obj.locations:
            return None
        loc = next((l for l in obj.locations if l.is_primary), obj.locations[0])
        return LocationSchema().dump(loc)


class BusinessSchema(Schema):
    """Full profile -- detail page."""
    id = fields.Int()
    slug = fields.Str()
    name = fields.Str()
    about = fields.Str(allow_none=True)
    logo_url = fields.Method('get_logo_url')
    category = fields.Str()
    is_food = fields.Method('get_is_food')
    website = fields.Str(allow_none=True)
    source_url = fields.Str(allow_none=True)
    source_name = fields.Str(allow_none=True)
    imported = fields.Bool()
    owner_user_id = fields.Str(allow_none=True)
    is_claimed = fields.Bool()
    is_own_business = fields.Method('get_is_own_business')
    created_by = fields.Str(allow_none=True)
    rating_avg = fields.Float()
    rating_count = fields.Int()
    attributes = fields.Raw(allow_none=True)
    pub_date = fields.DateTime()
    locations = fields.List(fields.Nested(LocationSchema))
    my_claim_status = fields.Method('get_my_claim_status')
    my_rating = fields.Method('get_my_rating')
    google_review_url = fields.Method('get_google_review_url')
    referral_reward = fields.Method('get_referral_reward')
    loyalty_enabled = fields.Method('get_loyalty_enabled')

    def get_google_review_url(self, obj):
        return (obj.attributes or {}).get('google_review_url')

    def get_referral_reward(self, obj):
        return (obj.attributes or {}).get('referral_reward')

    def get_loyalty_enabled(self, obj):
        return bool((obj.attributes or {}).get('loyalty_enabled'))

    def get_logo_url(self, obj):
        return get_public_url(obj.logo) if obj.logo else None

    def get_is_food(self, obj):
        return obj.category in FOOD_CATEGORIES

    def get_is_own_business(self, obj):
        uid = self.context.get('user_id')
        return bool(uid) and (obj.owner_user_id == uid or obj.created_by == uid)

    def get_my_claim_status(self, obj):
        uid = self.context.get('user_id')
        if not uid:
            return None
        mine = [c for c in obj.claims if c.user_id == uid]
        if not mine:
            return None
        mine.sort(key=lambda c: c.created_at or 0, reverse=True)
        return mine[0].status

    def get_my_rating(self, obj):
        uid = self.context.get('user_id')
        if not uid:
            return None
        mine = next((r for r in obj.ratings if r.user_id == uid), None)
        return {'stars': mine.stars, 'review_text': mine.review_text} if mine else None


def make_business_schema(current_user=None, many=False, card=False):
    """marshmallow 4 dropped the context= constructor kwarg -- set it after
    construction, matching every other schema factory in this codebase."""
    ctx = {'user_id': current_user.public_id if current_user else None}
    cls = BusinessCardSchema if card else BusinessSchema
    schema = cls(many=many)
    schema.context = ctx
    return schema


class ClaimSchema(Schema):
    id = fields.Int()
    business_id = fields.Int()
    user_id = fields.Str()
    user = fields.Nested(UserPublicSchema)
    status = fields.Str()
    message = fields.Str(allow_none=True)
    created_at = fields.DateTime()
    reviewed_by = fields.Str(allow_none=True)
    reviewed_at = fields.DateTime(allow_none=True)
    business = fields.Nested(BusinessCardSchema)


class RatingSchema(Schema):
    id = fields.Int()
    business_id = fields.Int()
    user_id = fields.Str()
    user = fields.Nested(UserPublicSchema)
    stars = fields.Int()
    review_text = fields.Str(allow_none=True)
    verified = fields.Bool()
    created_at = fields.DateTime()
    updated_at = fields.DateTime()


class CommentSchema(Schema):
    id = fields.Int()
    business_id = fields.Int()
    user_id = fields.Str()
    user = fields.Nested(UserPublicSchema)
    body = fields.Str()
    pub_date = fields.DateTime()
    is_own_comment = fields.Method('get_is_own_comment')

    def get_is_own_comment(self, obj):
        uid = self.context.get('user_id')
        return bool(uid) and obj.user_id == uid


def make_comment_schema(current_user=None, many=False):
    ctx = {'user_id': current_user.public_id if current_user else None}
    schema = CommentSchema(many=many)
    schema.context = ctx
    return schema
