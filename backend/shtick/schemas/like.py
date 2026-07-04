from marshmallow import Schema, fields


class UserSchema(Schema):
    public_id = fields.Str()
    email = fields.Str()


class LikeSchema(Schema):
    id = fields.Int()
    pub_date = fields.DateTime()
    shtick_id = fields.Int()
    user_id = fields.Str()
    user = fields.Nested(UserSchema)

like_schema = LikeSchema()
likes_schema = LikeSchema(many=True)
