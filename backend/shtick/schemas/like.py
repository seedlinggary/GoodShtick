from backend.shtick.modals.like import Like
from backend.user.modals.user import User

from config import ma

class UserSchema(ma.Schema):
    class Meta:
        model = User
        fields = ('public_id','email')

class LikeSchema(ma.Schema):
    class Meta:
        model = Like
        fields = ('id','pub_date','shtick_id','user_id','user')
                # include_fk = True
    user = ma.Nested(UserSchema)

like_schema = LikeSchema()
likes_schema = LikeSchema(many=True)