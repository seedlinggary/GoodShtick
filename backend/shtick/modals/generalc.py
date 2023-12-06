from config import db
from datetime import datetime

class Generalc(db.Model):
    
    id = db.Column(db.Integer, primary_key = True)
    name = db.Column(db.String(20))
    pub_date = db.Column(db.DateTime, default=datetime.utcnow)
    shticks = db.relationship('Shtick', backref='generalc', lazy=True)


    def __init__(self,name):
        self.name = name

        
    def __repr__(self):
        return  f'{self.name}'
