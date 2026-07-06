from config import db
from datetime import datetime


class User(db.Model):
    __tablename__ = 'user'

    id = db.Column(db.Integer, primary_key=True)
    public_id = db.Column(db.String(50), unique=True)
    first_name = db.Column(db.String(20))
    last_name = db.Column(db.String(20))
    profile_name = db.Column(db.String(120), unique=True)
    email = db.Column(db.String(120), unique=True)
    password = db.Column(db.String(200))
    pub_date = db.Column(db.DateTime, default=datetime.utcnow)
    role = db.Column(db.String(20), default='user')  # viewer, user, admin, super_admin
    last_login = db.Column(db.DateTime, nullable=True)

    # Optional, self-reported — used only for ad targeting. Never required at signup.
    birthdate = db.Column(db.Date, nullable=True)
    gender = db.Column(db.String(20), nullable=True)
    location_country = db.Column(db.String(100), nullable=True)
    location_city = db.Column(db.String(100), nullable=True)

    def __init__(self, public_id, first_name, last_name, password, email, profile_name):
        self.public_id = public_id
        self.first_name = first_name
        self.last_name = last_name
        self.password = password
        self.email = email
        self.profile_name = profile_name

    @property
    def is_boss(self):
        return self.role in ('admin', 'super_admin')

    @property
    def is_super_admin(self):
        return self.role == 'super_admin'

    @property
    def age(self):
        """Whole years old as of today, or None if birthdate isn't set. Ad-targeting only."""
        if not self.birthdate:
            return None
        today = datetime.utcnow().date()
        years = today.year - self.birthdate.year
        if (today.month, today.day) < (self.birthdate.month, self.birthdate.day):
            years -= 1
        return years

    def __repr__(self):
        return f'{self.first_name} {self.last_name}'
