from config import db
from datetime import datetime


class AdImpression(db.Model):
    __tablename__ = 'ad_impression'

    id = db.Column(db.Integer, primary_key=True)
    ad_id = db.Column(db.Integer, db.ForeignKey('ad.id'), nullable=False)
    user_id = db.Column(db.String(50), nullable=True)  # null for anonymous/logged-out visitors
    placement = db.Column(db.String(30))
    country = db.Column(db.String(100), nullable=True)
    viewed_at = db.Column(db.DateTime, default=datetime.utcnow)
