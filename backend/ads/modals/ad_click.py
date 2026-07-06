from config import db
from datetime import datetime


class AdClick(db.Model):
    __tablename__ = 'ad_click'

    id = db.Column(db.Integer, primary_key=True)
    ad_id = db.Column(db.Integer, db.ForeignKey('ad.id'), nullable=False)
    user_id = db.Column(db.String(50), nullable=True)
    country = db.Column(db.String(100), nullable=True)
    clicked_at = db.Column(db.DateTime, default=datetime.utcnow)
