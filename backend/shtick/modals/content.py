from config import db
from datetime import datetime

class Content(db.Model):
    
    id = db.Column(db.Integer, primary_key = True)
    stuff = db.Column(db.Text)
    pub_date = db.Column(db.DateTime, default=datetime.utcnow)
    shtick_id = db.Column(db.Integer, db.ForeignKey('shtick.id'), nullable=False)

    def __init__(self,stuff,shtick_id):
        self.stuff = stuff
        self.shtick_id = shtick_id

        
