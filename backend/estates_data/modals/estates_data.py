from datetime import datetime

from config import db

# ── Raw staging ──────────────────────────────────────────────────────────
# Every connector (backend/estates_data/connectors/*.py) writes ONLY here --
# never directly into a canonical table below. This is what makes the whole
# pipeline robust against the fact that almost none of these government
# sources have a stable, documented API (see the plan's source-landscape
# table): a source changing shape, blocking us, or going down only stops new
# raw rows from arriving here, it can never corrupt already-normalized
# canonical data, and fixing a bug in normalize.py later means re-running it
# over existing raw rows, never re-fetching from a flaky source.
RAW_STATUSES = ('pending', 'normalized', 'error', 'ignored')


class RawIngestRecord(db.Model):
    __tablename__ = 'estates_data_raw_record'

    id = db.Column(db.Integer, primary_key=True)
    source = db.Column(db.String(50), nullable=False, index=True)
    # The source's own row/record id, when it has one -- lets a connector
    # re-run safely without creating duplicates (see connectors/data_gov_il.py).
    external_id = db.Column(db.String(200), nullable=True, index=True)
    fetched_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    payload = db.Column(db.JSON, nullable=False)
    status = db.Column(db.String(20), nullable=False, default='pending', server_default='pending', index=True)
    # Set when normalize.py fails on this row, so the failure is visible
    # from the admin raw-record list without digging through logs.
    error = db.Column(db.Text, nullable=True)
    normalized_at = db.Column(db.DateTime, nullable=True)

    __table_args__ = (
        db.UniqueConstraint('source', 'external_id', name='uq_estates_data_raw_source_external_id'),
    )

    def __init__(self, source, payload, external_id=None, status='pending'):
        self.source = source
        self.payload = payload
        self.external_id = external_id
        self.status = status

    def __repr__(self):
        return f'RawIngestRecord({self.id}) {self.source}:{self.external_id}'


# ── Entity -- builder/developer/contractor/company/private person ───────
ENTITY_KINDS = ('company', 'developer', 'contractor', 'government', 'private_person', 'unknown')


class Entity(db.Model):
    """Unifies every named party across every source into one row, so
    de-duplication (backend/estates_data/linking.py) only ever has one table
    to merge into. `is_private` gates whether `name` is ever RENDERED by the
    API (see routes/estates_data.py) -- it is always stored regardless, per
    the owner's call to retrieve everything now and decide display later."""
    __tablename__ = 'estates_data_entity'

    id = db.Column(db.Integer, primary_key=True)
    kind = db.Column(db.String(20), nullable=False, default='unknown', server_default='unknown', index=True)
    name = db.Column(db.String(300), nullable=False)
    # What linking.py actually matches on (lowercased, punctuation/suffix
    # stripped) -- "ABC Construction Ltd" and "ABC Construction LTD." both
    # normalize to the same string and resolve to one Entity row.
    normalized_name = db.Column(db.String(300), nullable=False, index=True)
    # Public company registration number (ח"פ) -- for companies only, never
    # collected for a private person.
    company_number = db.Column(db.String(20), nullable=True, index=True)
    is_private = db.Column(db.Boolean, nullable=False, default=False, server_default='false', index=True)

    website = db.Column(db.String(300), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __init__(self, name, normalized_name, kind='unknown', **kwargs):
        self.name = name
        self.normalized_name = normalized_name
        self.kind = kind
        for key, value in kwargs.items():
            setattr(self, key, value)

    def __repr__(self):
        return f'Entity({self.id}) {self.name}'


# ── Geography -- parcel is the stable key, address is derived from it ────
class GeoParcel(db.Model):
    """Gush/Helka is the stable real-world key Israeli land records actually
    use -- Building, LandTender, ConstructionPermit, and sales all hang off
    this, not off street address, which is secondary/derived and sometimes
    missing or inconsistent across sources."""
    __tablename__ = 'estates_data_parcel'

    id = db.Column(db.Integer, primary_key=True)
    gush = db.Column(db.String(20), nullable=False, index=True)
    helka = db.Column(db.String(20), nullable=False, index=True)
    tat_helka = db.Column(db.String(20), nullable=True)

    municipality = db.Column(db.String(120), nullable=False, index=True)
    neighborhood = db.Column(db.String(120), nullable=True, index=True)
    lat = db.Column(db.Float, nullable=True, index=True)
    lng = db.Column(db.Float, nullable=True, index=True)
    # Parcel polygon, when a cadastral source (Survey of Israel/GovMap)
    # provides one -- optional, most records will have no boundary at all.
    boundary_geojson = db.Column(db.JSON, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    addresses = db.relationship('Address', backref='parcel', lazy=True)
    buildings = db.relationship('Building', backref='parcel', lazy=True)
    land_tenders = db.relationship('LandTender', backref='parcel', lazy=True)
    construction_permits = db.relationship('ConstructionPermit', backref='parcel', lazy=True)
    land_sales = db.relationship('SaleTransaction', backref='parcel', lazy=True)

    __table_args__ = (
        db.UniqueConstraint('gush', 'helka', 'tat_helka', name='uq_estates_data_parcel_gush_helka'),
    )

    def __init__(self, gush, helka, municipality, **kwargs):
        self.gush = gush
        self.helka = helka
        self.municipality = municipality
        for key, value in kwargs.items():
            setattr(self, key, value)

    def __repr__(self):
        return f'GeoParcel({self.id}) {self.gush}/{self.helka}'


class Address(db.Model):
    """A free-text address, resolved to a GeoParcel where possible.
    `parcel_id` is nullable because resolution happens in normalize.py/
    linking.py, not at ingest time -- a freshly staged record's address
    starts unresolved."""
    __tablename__ = 'estates_data_address'

    id = db.Column(db.Integer, primary_key=True)
    raw_text = db.Column(db.String(300), nullable=False)
    normalized_text = db.Column(db.String(300), nullable=False, index=True)
    city = db.Column(db.String(120), nullable=True, index=True)
    street = db.Column(db.String(150), nullable=True)
    house_number = db.Column(db.String(20), nullable=True)
    parcel_id = db.Column(db.Integer, db.ForeignKey('estates_data_parcel.id'), nullable=True, index=True)
    lat = db.Column(db.Float, nullable=True)
    lng = db.Column(db.Float, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __init__(self, raw_text, normalized_text, **kwargs):
        self.raw_text = raw_text
        self.normalized_text = normalized_text
        for key, value in kwargs.items():
            setattr(self, key, value)

    def __repr__(self):
        return f'Address({self.id}) {self.raw_text}'


# ── Buildings and units ───────────────────────────────────────────────────
class Building(db.Model):
    __tablename__ = 'estates_data_building'

    id = db.Column(db.Integer, primary_key=True)
    parcel_id = db.Column(db.Integer, db.ForeignKey('estates_data_parcel.id'), nullable=False, index=True)
    developer_entity_id = db.Column(db.Integer, db.ForeignKey('estates_data_entity.id'), nullable=True, index=True)
    floor_count = db.Column(db.Integer, nullable=True)
    unit_count = db.Column(db.Integer, nullable=True)
    year_built = db.Column(db.Integer, nullable=True)
    source_name = db.Column(db.String(150), nullable=True)
    source_url = db.Column(db.String(500), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    units = db.relationship('Unit', backref='building', lazy=True)
    construction_permits = db.relationship('ConstructionPermit', backref='building', lazy=True)
    developer = db.relationship('Entity', foreign_keys=[developer_entity_id])

    def __init__(self, parcel_id, **kwargs):
        self.parcel_id = parcel_id
        for key, value in kwargs.items():
            setattr(self, key, value)

    def __repr__(self):
        return f'Building({self.id}) parcel={self.parcel_id}'


class Unit(db.Model):
    __tablename__ = 'estates_data_unit'

    id = db.Column(db.Integer, primary_key=True)
    building_id = db.Column(db.Integer, db.ForeignKey('estates_data_building.id'), nullable=False, index=True)
    floor = db.Column(db.String(10), nullable=True)
    apartment_number = db.Column(db.String(20), nullable=True)
    size_sqm = db.Column(db.Float, nullable=True)
    room_count = db.Column(db.Float, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    sales = db.relationship('SaleTransaction', backref='unit', lazy=True)

    def __init__(self, building_id, **kwargs):
        self.building_id = building_id
        for key, value in kwargs.items():
            setattr(self, key, value)

    def __repr__(self):
        return f'Unit({self.id}) building={self.building_id}'


# ── Land tenders and construction permits ─────────────────────────────────
class LandTender(db.Model):
    """A Land Authority (RMI) tender result -- who bought the land, how
    much, how many units they're allowed to build there."""
    __tablename__ = 'estates_data_land_tender'

    id = db.Column(db.Integer, primary_key=True)
    parcel_id = db.Column(db.Integer, db.ForeignKey('estates_data_parcel.id'), nullable=True, index=True)
    tender_number = db.Column(db.String(50), nullable=True, index=True)
    winner_entity_id = db.Column(db.Integer, db.ForeignKey('estates_data_entity.id'), nullable=True, index=True)
    price = db.Column(db.Float, nullable=True)
    currency = db.Column(db.String(3), nullable=False, default='ILS', server_default='ILS')
    buildable_units = db.Column(db.Integer, nullable=True)
    decision_date = db.Column(db.Date, nullable=True, index=True)
    source_name = db.Column(db.String(150), nullable=False)
    source_url = db.Column(db.String(500), nullable=True)
    raw_record_id = db.Column(db.Integer, db.ForeignKey('estates_data_raw_record.id'), nullable=True)
    confidence = db.Column(db.Float, nullable=False, default=1.0, server_default='1.0')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    winner = db.relationship('Entity', foreign_keys=[winner_entity_id])

    def __init__(self, source_name, **kwargs):
        self.source_name = source_name
        for key, value in kwargs.items():
            setattr(self, key, value)

    def __repr__(self):
        return f'LandTender({self.id}) {self.tender_number}'


class ConstructionPermit(db.Model):
    __tablename__ = 'estates_data_construction_permit'

    id = db.Column(db.Integer, primary_key=True)
    parcel_id = db.Column(db.Integer, db.ForeignKey('estates_data_parcel.id'), nullable=True, index=True)
    building_id = db.Column(db.Integer, db.ForeignKey('estates_data_building.id'), nullable=True, index=True)
    permit_number = db.Column(db.String(50), nullable=True, index=True)
    issuing_authority = db.Column(db.String(150), nullable=True)
    entity_id = db.Column(db.Integer, db.ForeignKey('estates_data_entity.id'), nullable=True, index=True)
    units_permitted = db.Column(db.Integer, nullable=True)
    issue_date = db.Column(db.Date, nullable=True, index=True)
    source_name = db.Column(db.String(150), nullable=False)
    source_url = db.Column(db.String(500), nullable=True)
    raw_record_id = db.Column(db.Integer, db.ForeignKey('estates_data_raw_record.id'), nullable=True)
    confidence = db.Column(db.Float, nullable=False, default=1.0, server_default='1.0')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    entity = db.relationship('Entity', foreign_keys=[entity_id])

    def __init__(self, source_name, **kwargs):
        self.source_name = source_name
        for key, value in kwargs.items():
            setattr(self, key, value)

    def __repr__(self):
        return f'ConstructionPermit({self.id}) {self.permit_number}'


# ── Sales -- one transaction, possibly several payments ──────────────────
SALE_STATUSES = ('reported', 'verified', 'disputed')


class SaleTransaction(db.Model):
    """One sale. A sale that arrives from its source as several separate
    payments is still exactly one row here -- the linking engine
    (backend/estates_data/linking.py) groups those payments into this one
    transaction's `payments`, this row is never created straight from a
    single raw payment."""
    __tablename__ = 'estates_data_sale_transaction'

    id = db.Column(db.Integer, primary_key=True)
    unit_id = db.Column(db.Integer, db.ForeignKey('estates_data_unit.id'), nullable=True, index=True)
    # Set instead of unit_id for a land-only sale (no building on it yet).
    parcel_id = db.Column(db.Integer, db.ForeignKey('estates_data_parcel.id'), nullable=True, index=True)
    buyer_entity_id = db.Column(db.Integer, db.ForeignKey('estates_data_entity.id'), nullable=True, index=True)
    seller_entity_id = db.Column(db.Integer, db.ForeignKey('estates_data_entity.id'), nullable=True, index=True)
    total_price = db.Column(db.Float, nullable=True)
    currency = db.Column(db.String(3), nullable=False, default='ILS', server_default='ILS')
    deal_date = db.Column(db.Date, nullable=True, index=True)
    # Contractor/new-build ("first hand") sale flag, when the source marks
    # it -- null when unknown, never guessed.
    is_first_hand = db.Column(db.Boolean, nullable=True)
    status = db.Column(db.String(20), nullable=False, default='reported', server_default='reported')
    source_name = db.Column(db.String(150), nullable=False)
    source_url = db.Column(db.String(500), nullable=True)
    raw_record_id = db.Column(db.Integer, db.ForeignKey('estates_data_raw_record.id'), nullable=True)
    confidence = db.Column(db.Float, nullable=False, default=1.0, server_default='1.0')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    buyer = db.relationship('Entity', foreign_keys=[buyer_entity_id])
    seller = db.relationship('Entity', foreign_keys=[seller_entity_id])
    payments = db.relationship('SalePayment', backref='transaction', lazy=True, cascade='all, delete-orphan')

    def __init__(self, source_name, **kwargs):
        self.source_name = source_name
        for key, value in kwargs.items():
            setattr(self, key, value)

    def __repr__(self):
        return f'SaleTransaction({self.id}) unit={self.unit_id} parcel={self.parcel_id}'


class SalePayment(db.Model):
    __tablename__ = 'estates_data_sale_payment'

    id = db.Column(db.Integer, primary_key=True)
    transaction_id = db.Column(db.Integer, db.ForeignKey('estates_data_sale_transaction.id'), nullable=False, index=True)
    amount = db.Column(db.Float, nullable=True)
    paid_at = db.Column(db.Date, nullable=True)
    note = db.Column(db.String(300), nullable=True)
    raw_record_id = db.Column(db.Integer, db.ForeignKey('estates_data_raw_record.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __init__(self, transaction_id, **kwargs):
        self.transaction_id = transaction_id
        for key, value in kwargs.items():
            setattr(self, key, value)

    def __repr__(self):
        return f'SalePayment({self.id}) transaction={self.transaction_id}'


# ── Arnona -- manually entered, estimate-only ─────────────────────────────
ARNONA_USE_TYPES = ('residential', 'commercial', 'industrial', 'office', 'other')


class ArnonaRate(db.Model):
    """Manually entered from each municipality's own published yearly
    arnona order ("tzav arnona") -- there is no feed for this, nothing here
    is ever fetched automatically. Used only to compute an ESTIMATE
    (rate x a property's size) at query time; never presented as a real
    bill, since actual billed amounts for a specific property are not
    public data (only the municipal rate table is)."""
    __tablename__ = 'estates_data_arnona_rate'

    id = db.Column(db.Integer, primary_key=True)
    municipality = db.Column(db.String(120), nullable=False, index=True)
    year = db.Column(db.Integer, nullable=False, index=True)
    zone = db.Column(db.String(80), nullable=True)
    use_type = db.Column(db.String(20), nullable=False, default='residential', server_default='residential')
    rate_per_sqm = db.Column(db.Float, nullable=False)
    currency = db.Column(db.String(3), nullable=False, default='ILS', server_default='ILS')
    source_name = db.Column(db.String(150), nullable=False)
    source_url = db.Column(db.String(500), nullable=True)
    entered_by = db.Column(db.String(50), db.ForeignKey('user.public_id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('municipality', 'year', 'zone', 'use_type', name='uq_estates_data_arnona_rate'),
    )

    def __init__(self, municipality, year, rate_per_sqm, source_name, **kwargs):
        self.municipality = municipality
        self.year = year
        self.rate_per_sqm = rate_per_sqm
        self.source_name = source_name
        for key, value in kwargs.items():
            setattr(self, key, value)

    def __repr__(self):
        return f'ArnonaRate({self.id}) {self.municipality} {self.year}'
