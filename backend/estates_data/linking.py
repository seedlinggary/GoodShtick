"""The actual linking engine: parcel resolution, entity de-duplication,
and grouping several payments into one sale. Shared by every per-source
normalizer in normalize.py -- this file has no idea what a nadlan.gov.il
deal or an RMI tender looks like, it only knows how to resolve a
(gush, helka) into one GeoParcel, a name into one Entity, and a new
payment into either an existing SaleTransaction or a fresh one. Keeping
this shared is what makes "the same builder across two different
sources" or "a sale reported as three payments" actually collapse into
one row instead of three."""
import re
import unicodedata
from datetime import timedelta

from config import db
from backend.estates_data.modals.estates_data import Entity, GeoParcel, Address, SaleTransaction, SalePayment

# How far apart two payments for the same unit/buyer/seller can be and
# still count as installments of one sale, rather than two separate
# sales -- generous on purpose (a new-build sale can span a long
# construction-linked payment schedule), tightened later if real data
# shows it's grouping things that shouldn't be grouped.
PAYMENT_GROUPING_WINDOW_DAYS = 365

_LEGAL_SUFFIXES = re.compile(r'\b(ltd|llc|inc|co|corp|בעמ|בע"מ)\.?\s*$', re.IGNORECASE)


def normalize_name(name):
    """Lowercase, strip legal-entity suffixes and punctuation -- "ABC
    Construction Ltd" and "ABC Construction LTD." both reduce to the same
    string, which is what resolve_entity() matches on."""
    if not name:
        return ''
    text = unicodedata.normalize('NFKC', str(name)).strip().lower()
    text = _LEGAL_SUFFIXES.sub('', text).strip()
    text = re.sub(r'[^\w\s]', '', text)
    text = re.sub(r'\s+', ' ', text)
    return text


def resolve_entity(name, kind='unknown', company_number=None, is_private=False):
    """Find-or-create an Entity by its normalized name. A company_number
    match (when both sides have one) is treated as a stronger signal than
    a name match, and is checked first."""
    if not name:
        return None
    norm = normalize_name(name)
    if not norm:
        return None

    if company_number:
        existing = Entity.query.filter_by(company_number=company_number).first()
        if existing:
            return existing

    existing = Entity.query.filter_by(normalized_name=norm).first()
    if existing:
        if company_number and not existing.company_number:
            existing.company_number = company_number
        return existing

    entity = Entity(name=name, normalized_name=norm, kind=kind, company_number=company_number, is_private=is_private)
    db.session.add(entity)
    db.session.flush()
    return entity


def resolve_parcel(gush=None, helka=None, tat_helka=None, municipality=None, address_text=None, lat=None, lng=None):
    """Exact gush/helka match first (the strong, stable key); falls back
    to an exact normalized-address match against a previously-resolved
    Address when no parcel identifiers are available at all.

    Returns (parcel_or_none, confidence): 1.0 for an existing gush/helka
    match or an already-resolved address; 0.6 for a brand-new parcel
    created from gush/helka alone (no cross-source confirmation yet);
    0.0 when nothing could be resolved -- an Address row is still saved
    unresolved so the raw location isn't lost, just not yet linked."""
    if gush and helka:
        tat = str(tat_helka) if tat_helka else None
        existing = GeoParcel.query.filter_by(gush=str(gush), helka=str(helka), tat_helka=tat).first()
        if existing:
            return existing, 1.0
        parcel = GeoParcel(gush=str(gush), helka=str(helka), tat_helka=tat,
                            municipality=municipality or '', lat=lat, lng=lng)
        db.session.add(parcel)
        db.session.flush()
        return parcel, 0.6

    if address_text:
        norm = re.sub(r'\s+', ' ', address_text.strip().lower())
        existing_address = Address.query.filter_by(normalized_text=norm).first()
        if existing_address and existing_address.parcel_id:
            return GeoParcel.query.get(existing_address.parcel_id), 1.0
        if not existing_address:
            db.session.add(Address(raw_text=address_text, normalized_text=norm, city=municipality, lat=lat, lng=lng))
            db.session.flush()
        return None, 0.0

    return None, 0.0


def group_payment_into_transaction(source_name, unit_id=None, parcel_id=None, buyer_entity_id=None,
                                    seller_entity_id=None, amount=None, paid_at=None, is_first_hand=None,
                                    currency='ILS', confidence=1.0, raw_record_id=None):
    """Finds an open SaleTransaction for the same unit (or parcel, for a
    land-only sale) and buyer/seller within PAYMENT_GROUPING_WINDOW_DAYS
    of `paid_at`, and attaches a new SalePayment to it instead of
    creating a second transaction -- the "a sale arrives as several
    payments" grouping the data model promises. No match -- a brand new
    SaleTransaction, with this as its first payment, is created instead.
    Returns (transaction, created_bool)."""
    transaction = None
    if unit_id or parcel_id:
        query = SaleTransaction.query.filter_by(unit_id=unit_id) if unit_id else SaleTransaction.query.filter_by(parcel_id=parcel_id)
        if buyer_entity_id:
            query = query.filter_by(buyer_entity_id=buyer_entity_id)
        if seller_entity_id:
            query = query.filter_by(seller_entity_id=seller_entity_id)
        if paid_at:
            window_start = paid_at - timedelta(days=PAYMENT_GROUPING_WINDOW_DAYS)
            window_end = paid_at + timedelta(days=PAYMENT_GROUPING_WINDOW_DAYS)
            query = query.filter(SaleTransaction.deal_date.between(window_start, window_end))
        transaction = query.first()

    if transaction:
        if amount:
            transaction.total_price = (transaction.total_price or 0) + amount
        db.session.add(SalePayment(transaction_id=transaction.id, amount=amount, paid_at=paid_at, raw_record_id=raw_record_id))
        return transaction, False

    transaction = SaleTransaction(
        source_name=source_name, unit_id=unit_id, parcel_id=parcel_id,
        buyer_entity_id=buyer_entity_id, seller_entity_id=seller_entity_id,
        total_price=amount, currency=currency, deal_date=paid_at,
        is_first_hand=is_first_hand, confidence=confidence, raw_record_id=raw_record_id,
    )
    db.session.add(transaction)
    db.session.flush()
    db.session.add(SalePayment(transaction_id=transaction.id, amount=amount, paid_at=paid_at, raw_record_id=raw_record_id))
    return transaction, True
