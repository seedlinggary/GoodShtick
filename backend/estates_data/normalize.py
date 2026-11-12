"""Per-source normalizers -- the only place in this package that knows
what a raw nadlan.gov.il deal or RMI tender payload actually looks like.
Each one turns a RawIngestRecord.payload into calls against linking.py's
shared resolve_entity/resolve_parcel/group_payment_into_transaction, then
the driver (run_normalization) marks that record 'normalized' (or
'error', with the exception message, so one bad record is visible and
retryable without blocking the rest of the batch).

Field-name note: nadlan_gov's exact OUTPUT field names were confirmed
from the vendor's own published README for yearBuilt/floor/
buildingFloors/isFirstHand/prevDeals/trend only -- the rest (price,
address, gush/helka, etc) are reasonable guesses pending a first real
run, since no real sample output item has been seen yet. Because every
raw payload is preserved untouched in RawIngestRecord, a wrong guess
costs nothing but re-running this file once the real shape is seen --
never a re-fetch. _first() below also tries the Hebrew column headers a
hand-copied CSV from nadlan.gov.il's own UI would actually have, since
manual_import.py stages those under the same 'nadlan_gov*'/'rmi_tenders*'
source prefix and this dispatches by prefix, not exact source name."""
from datetime import datetime

from config import db
from backend.estates_data.modals.estates_data import RawIngestRecord, LandTender, ArnonaRateCandidate
from backend.estates_data import linking
from backend.estates_data.arnona_parse import parse_arnona_candidates


def _first(payload, *keys):
    for key in keys:
        value = payload.get(key)
        if value not in (None, ''):
            return value
    return None


def _parse_date(value):
    if not value:
        return None
    if isinstance(value, str):
        for fmt in ('%Y-%m-%d', '%d/%m/%Y', '%d/%m/%y'):
            try:
                return datetime.strptime(value, fmt).date()
            except ValueError:
                continue
    return None


def _parse_number(value):
    if value in (None, ''):
        return None
    try:
        return float(str(value).replace(',', '').strip())
    except ValueError:
        return None


def normalize_nadlan_deal(record):
    payload = record.payload
    gush = _first(payload, 'gush', 'Gush', 'גוש')
    helka = _first(payload, 'helka', 'Helka', 'חלקה')
    tat_helka = _first(payload, 'tatHelka', 'tat_helka', 'תת חלקה')
    address = _first(payload, 'address', 'Address', 'כתובת')
    neighborhood = _first(payload, 'neighborhood', 'שכונה')
    price = _parse_number(_first(payload, 'price', 'Price', 'מחיר'))
    deal_date = _parse_date(_first(payload, 'dealDate', 'signingDate', 'date', 'תאריך עסקה', 'תאריך'))
    is_first_hand = _first(payload, 'isFirstHand')
    seller_name = _first(payload, 'sellerName', 'seller', 'מוכר')
    buyer_name = _first(payload, 'buyerName', 'buyer', 'קונה')

    parcel, parcel_confidence = linking.resolve_parcel(
        gush=gush, helka=helka, tat_helka=tat_helka, municipality=neighborhood, address_text=address,
    )

    # Ordinary sale-deal parties default to private_person/is_private=True
    # -- the display-visibility gate (routes/estates_data.py's
    # serializer, once built) decides whether a name is ever shown, never
    # this step. A deal explicitly marked first-hand (new-build/
    # contractor sale) is the one case a "buyer/seller" name is usually a
    # company, but that distinction is left to normalize_nadlan_deal's
    # own future refinement once real sample data is seen, not guessed
    # here.
    buyer = linking.resolve_entity(buyer_name, kind='private_person', is_private=True) if buyer_name else None
    seller = linking.resolve_entity(seller_name, kind='private_person', is_private=True) if seller_name else None

    linking.group_payment_into_transaction(
        source_name='nadlan.gov.il (via Apify)' if record.source == 'nadlan_gov' else 'nadlan.gov.il (manual export)',
        parcel_id=parcel.id if parcel else None,
        buyer_entity_id=buyer.id if buyer else None,
        seller_entity_id=seller.id if seller else None,
        amount=price, paid_at=deal_date,
        is_first_hand=bool(is_first_hand) if is_first_hand is not None else None,
        confidence=parcel_confidence if parcel else 0.3,
        raw_record_id=record.id,
    )


def normalize_rmi_tender(record):
    payload = record.payload
    tender_number = _first(payload, 'tenderNumber', 'michrazNumber', 'מספר מכרז')
    settlement = _first(payload, 'settlement', 'city', 'יישוב')
    gush = _first(payload, 'gush', 'גוש')
    helka = _first(payload, 'helka', 'חלקה')
    price = _parse_number(_first(payload, 'winningPrice', 'price', 'מחיר זכייה', 'מחיר'))
    units = _first(payload, 'buildableUnits', 'housingUnits', 'units', 'יחידות דיור')
    decision_date = _parse_date(_first(payload, 'decisionDate', 'committeeDate', 'תאריך ועדה'))
    winner_name = _first(payload, 'winnerName', 'winningBidder', 'winner', 'זוכה')

    parcel, parcel_confidence = linking.resolve_parcel(gush=gush, helka=helka, municipality=settlement)
    winner = linking.resolve_entity(winner_name, kind='developer') if winner_name else None

    units_int = None
    if units is not None:
        try:
            units_int = int(float(str(units)))
        except ValueError:
            units_int = None

    tender = LandTender(
        source_name='Israel Land Authority (via Apify)' if record.source == 'rmi_tenders' else 'Israel Land Authority (manual export)',
        parcel_id=parcel.id if parcel else None,
        tender_number=str(tender_number) if tender_number else None,
        winner_entity_id=winner.id if winner else None,
        price=price,
        buildable_units=units_int,
        decision_date=decision_date,
        confidence=parcel_confidence if parcel else 0.3,
        raw_record_id=record.id,
    )
    db.session.add(tender)


def normalize_arnona_pdf(record):
    """Unlike the other normalizers, this never writes to a trusted
    canonical table -- parse_arnona_candidates' guesses land in
    ArnonaRateCandidate, reviewed and approved (or rejected) by an admin
    via /estates-data/admin/arnona-candidates, same reasoning as the
    linking engine's own review queue for low-confidence parcels/sales."""
    payload = record.payload
    candidates = parse_arnona_candidates(payload.get('text') or '')
    for c in candidates:
        db.session.add(ArnonaRateCandidate(
            municipality=payload.get('municipality'), year=payload.get('year'),
            zone=c['zone'], use_type=c['use_type'], area_component=c['area_component'],
            rate_per_sqm=c['rate_per_sqm'], confidence=c['confidence'], raw_line=c['raw_line'],
            source_url=payload.get('pdf_url'), raw_record_id=record.id,
        ))


# Dispatched by source PREFIX, not exact match -- 'nadlan_gov_manual'
# (manual_import.py's label for a hand-exported CSV) goes through the
# same normalizer as 'nadlan_gov' (the automated Apify connector).
NORMALIZERS = (
    ('nadlan_gov', normalize_nadlan_deal),
    ('rmi_tenders', normalize_rmi_tender),
    ('arnona_pdf', normalize_arnona_pdf),
)


def run_normalization(limit=500):
    """Processes up to `limit` pending RawIngestRecords. A record whose
    source matches no known normalizer prefix is left 'pending'
    untouched (not errored), so adding a new normalizer later can still
    pick it up. Returns {'normalized': n, 'errored': n, 'skipped': n}."""
    records = RawIngestRecord.query.filter_by(status='pending').order_by(RawIngestRecord.fetched_at).limit(limit).all()
    counts = {'normalized': 0, 'errored': 0, 'skipped': 0}

    for record in records:
        normalizer = next((fn for prefix, fn in NORMALIZERS if record.source.startswith(prefix)), None)
        if not normalizer:
            counts['skipped'] += 1
            continue
        try:
            normalizer(record)
            record.status = 'normalized'
            record.normalized_at = datetime.utcnow()
            db.session.commit()
            counts['normalized'] += 1
        except Exception as exc:
            db.session.rollback()
            record.status = 'error'
            record.error = str(exc)
            db.session.commit()
            counts['errored'] += 1

    return counts
