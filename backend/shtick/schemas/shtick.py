from backend.user.modals.user import User
from backend.shtick.modals.shtick import Shtick
from backend.shtick.modals.generalc import Generalc
from backend.shtick.modals.picture import Picture
from backend.shtick.modals.url import Url
from backend.shtick.modals.content import Content
from backend.shtick.modals.like import Like
from config import ma

class UserSchema(ma.Schema):
    class Meta:
        model = User
        fields = ('public_id','profile_name', 'email')

class LikeSchema(ma.Schema):
    class Meta:
        model = Like
        fields = ('id','pub_date','shtick_id','user_id', 'user')
    user = ma.Nested(UserSchema)
class GeneralcSchema(ma.Schema):
    class Meta:
        model = Generalc
        fields = ('id','name')

                # include_fk = True
class PictureSchema(ma.Schema):
    class Meta:
        model = Picture
        fields = ('id','name')
                # include_fk = True
class UrlSchema(ma.Schema):
    class Meta:
        model = Url
        fields = ('id','name')
                # include_fk = True
class ContentSchema(ma.Schema):
    class Meta:
        model = Content
        fields = ('id','stuff')
                # include_fk = True
class ShtickSchema(ma.Schema):
    class Meta:
        model = Shtick
        fields = ('id','pub_date','caption','credit','approved_to_publish','specific_category','user_id','user','generalc_id','generalc','content', 'picture', 'url','likes')
                # include_fk = True
    user = ma.Nested(UserSchema)
    generalc = ma.Nested(GeneralcSchema)
    content = ma.Nested(ContentSchema)
    picture = ma.Nested(PictureSchema)
    url = ma.Nested(UrlSchema)
    likes = ma.Nested(LikeSchema, many=True)
shtick_schema = ShtickSchema()
shticks_schema = ShtickSchema(many=True)