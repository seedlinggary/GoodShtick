from config import db
from datetime import datetime

class Like(db.Model):
    
    id = db.Column(db.Integer, primary_key = True)
    pub_date = db.Column(db.DateTime, default=datetime.utcnow)
    shtick_id = db.Column(db.Integer, db.ForeignKey('shtick.id'), nullable=False)
    user_id = db.Column(db.String(50), db.ForeignKey('user.public_id'))

    def __init__(self,user_id,shtick_id):
        self.user_id = user_id
        self.shtick_id = shtick_id