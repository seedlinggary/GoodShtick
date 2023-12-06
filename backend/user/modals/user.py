from config import db
from datetime import datetime

class User(db.Model):
    
    id = db.Column(db.Integer, primary_key = True)
    public_id = db.Column(db.String(50), unique=True )
    first_name = db.Column(db.String(20))
    last_name = db.Column(db.String(20))
    profile_name = db.Column(db.String(120), unique=True)
    email = db.Column(db.String(120), unique=True)
    password = db.Column(db.String(120))
    pub_date = db.Column(db.DateTime, default=datetime.utcnow)
    
    is_boss = db.Column(db.Boolean, default=False)
    shticks = db.relationship('Shtick', backref='user', lazy=True)
    likes = db.relationship('Like', backref='user', lazy=True)

    def __init__(self,public_id, first_name, last_name, password,email,profile_name):
        self.public_id = public_id
        self.first_name = first_name
        self.last_name = last_name
        self.password = password
        self.email = email
        self.profile_name = profile_name
        
    def __repr__(self):
        return  f'{self.first_name} {self.last_name}'
