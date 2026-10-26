from config import db
from datetime import datetime


class Ad(db.Model):
    __tablename__ = 'ad'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    advertiser_name = db.Column(db.String(120))
    status = db.Column(db.String(20), default='draft')  # draft, active, paused, archived

    # Creative
    image_name = db.Column(db.String(200))
    headline = db.Column(db.String(200))
    body_text = db.Column(db.Text)
    cta_label = db.Column(db.String(40), default='Learn More')

    # Destination
    destination_type = db.Column(db.String(20), default='url')  # url, whatsapp, phone, email, internal
    destination_value = db.Column(db.String(500), nullable=False)

    # Pages/placements this ad is allowed to appear on. Comma-separated list of
    # VALID_PLACEMENTS values (see routes/ads.py); NULL/empty = every placement,
    # same "unrestricted" convention as target_age_min/target_gender/
    # target_countries below. This is what lets one ad be assigned to one or
    # many pages across any site.
    placements = db.Column(db.Text, nullable=True)

    # Targeting — null/empty on any field means "no restriction on that axis"
    target_age_min = db.Column(db.Integer, nullable=True)
    target_age_max = db.Column(db.Integer, nullable=True)
    target_gender = db.Column(db.String(20), nullable=True)
    target_countries = db.Column(db.String(500), nullable=True)  # comma-separated ISO country codes

    # Scheduling — null on either side means unbounded
    start_date = db.Column(db.DateTime, nullable=True)
    end_date = db.Column(db.DateTime, nullable=True)

    # Relative weight used to diversify which ad wins among simultaneously-eligible active ads
    weight = db.Column(db.Integer, default=1)

    # Denormalized counters for fast admin list display; ad_impression/ad_click are the source of truth
    impression_count = db.Column(db.Integer, default=0)
    click_count = db.Column(db.Integer, default=0)

    created_by = db.Column(db.String(50), nullable=True)
    pub_date = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f'<Ad {self.id} {self.name}>'
