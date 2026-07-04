from marshmallow import Schema, fields


class GameScoreSchema(Schema):
    id = fields.Int()
    game_type = fields.Str()
    result = fields.Str()
    difficulty = fields.Str()
    score = fields.Int()
    pub_date = fields.DateTime()
    user_id = fields.Str()


game_score_schema = GameScoreSchema()
game_scores_schema = GameScoreSchema(many=True)
