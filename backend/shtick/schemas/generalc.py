from marshmallow import Schema, fields


class GeneralcSchema(Schema):
    id = fields.Int()
    name = fields.Str()

generalc_schema = GeneralcSchema()
generalcs_schema = GeneralcSchema(many=True)
