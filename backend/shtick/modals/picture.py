from config import db
from datetime import datetime

class Picture(db.Model):
    
    id = db.Column(db.Integer, primary_key = True)
    name = db.Column(db.String(20))
    pub_date = db.Column(db.DateTime, default=datetime.utcnow)
    shtick_id = db.Column(db.Integer, db.ForeignKey('shtick.id'), nullable=False)

    def __init__(self,name,shtick_id):
        self.name = name
        self.shtick_id = shtick_id

        
