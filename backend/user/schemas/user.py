from backend.user.modals.user import User
from config import ma



class UserSchema(ma.Schema):
    class Meta:
        model = User
        fields = ('public_id', 'first_name', 'last_name', 'email', 'profile_name')
                # include_fk = True
user_schema = UserSchema()
users_schema = UserSchema(many=True)