from config import db
from datetime import datetime

class Shtick(db.Model):
    
    id = db.Column(db.Integer, primary_key = True)
    caption = db.Column(db.String(120))
    credit = db.Column(db.String(125))
    specific_category = db.Column(db.String(120))
    pub_date = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.String(50), db.ForeignKey('user.public_id'))
    generalc_id = db.Column(db.Integer, db.ForeignKey('generalc.id'))
    approved_to_publish = db.Column(db.Boolean, default=None)
    content = db.relationship('Content', backref='shtick', lazy=True, uselist=False)
    url = db.relationship('Url', backref='shtick', lazy=True, uselist=False)
    picture = db.relationship('Picture', backref='shtick', lazy=True, uselist=False)
    likes = db.relationship('Like', backref='shtick', lazy=True)

    def __init__(self,caption, credit, specific_category, user_id,generalc_id):
        self.caption = caption
        self.credit = credit
        self.specific_category = specific_category
        self.user_id = user_id
        self.generalc_id =generalc_id
        
    def __repr__(self):
        return  f'{self.caption}'
