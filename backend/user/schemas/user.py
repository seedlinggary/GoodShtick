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


class UserPublicSchema(Schema):
    public_id = fields.Str()
    profile_name = fields.Str()
    role = fields.Str()


user_schema = UserSchema()
users_schema = UserSchema(many=True)
user_public_schema = UserPublicSchema()
users_public_schema = UserPublicSchema(many=True)
