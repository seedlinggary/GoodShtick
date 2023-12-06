from flask import  jsonify, request,send_file, make_response,redirect
from datetime import datetime, timedelta
from werkzeug.security import check_password_hash
import jwt
from config import application, db
from backend.user.routes.user import user_api
from backend.user.modals.user import User
from backend.shtick.routes.generalc import generalc_api
from backend.shtick.routes.shtick import shtick_api
from backend.shtick.routes.like import like_api
from backend.shtick.modals.picture import Picture
application.register_blueprint(user_api)
application.register_blueprint(generalc_api)
application.register_blueprint(shtick_api)
application.register_blueprint(like_api)
with application.app_context():
    db.create_all()



@application.route('/login', methods=['GET'])
def login():
    auth = request.authorization
    if not auth or not auth.username or not auth.password:
        return make_response('could not verify',401,{"www-authenticate": "basicl realm = 'login required'"})
    user = User.query.filter_by(email=auth.username).first()
    if not user:
        return make_response('could not verify',401,{"www-authenticate": "basicl realm = 'login required'"})
    if check_password_hash(user.password, auth.password):
        token = jwt.encode({'public_id': user.public_id, 'exp': datetime.utcnow() + timedelta(minutes=30000)}, application.config["SECRET_KEY"], algorithm="HS256")
        return jsonify({'token': token, 'is_boss': user.is_boss})
    return make_response('could not verify',401,{"www-authenticate": "basicl realm = 'login required'"})


if(__name__) == '__main__':
    # app.run()

    application.run(debug=True)
