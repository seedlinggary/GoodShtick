from marshmallow import Schema, fields


class UserSchema(Schema):
    public_id = fields.Str()
    first_name = fields.Str()
    last_name = fields.Str()
    email = fields.Str()
    profile_name = fields.Str()
    role = fields.Str()
    pub_date = fields.DateTime()
    last_login = fields.DateTime()
    birthdate = fields.Date()
    gender = fields.Str()
    location_country = fields.Str()
    location_city = fields.Str()
    profile_area = fields.Str()
    budget_min = fields.Int()
    budget_max = fields.Int()
    family_size = fields.Int()
    line_of_work = fields.Str()
    weekly_digest_enabled = fields.Bool()
    cv_summary = fields.Str(allow_none=True)
    cv_contact = fields.Str(allow_none=True)
    open_to_work = fields.Bool()


class UserPublicSchema(Schema):
    public_id = fields.Str()
    profile_name = fields.Str()
    role = fields.Str()


user_schema = UserSchema()
users_schema = UserSchema(many=True)
user_public_schema = UserPublicSchema()
users_public_schema = UserPublicSchema(many=True)
