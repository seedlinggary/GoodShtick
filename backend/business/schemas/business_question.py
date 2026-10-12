from marshmallow import Schema, fields


class QuestionSchema(Schema):
    id = fields.Int()
    business_id = fields.Int()
    asker_name = fields.Str()
    question = fields.Str()
    answer = fields.Str(allow_none=True)
    answered_at = fields.DateTime(allow_none=True)
    created_at = fields.DateTime()
    is_answered = fields.Bool()
