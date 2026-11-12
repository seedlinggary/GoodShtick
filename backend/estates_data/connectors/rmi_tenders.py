"""Connector for Israel Land Authority (RMI) land tenders -- who bought
the land, how much, how many units they're allowed to build there.

Same reasoning as nadlan_gov.py: the Authority's own tender API
(apps.land.gov.il/MichrazimSite/api) only answers requests that spoof an
Origin/Referer matching its own site, which this package won't do.
Instead this pays a licensed data vendor -- Apify's
`swerve/israel-land-tenders` actor -- through Apify's documented REST API
(see apify_client.py). Every call is billed by Apify and requires
APIFY_API_TOKEN with billing enabled; nothing here runs for free.

Confirmed actor input schema (fetched from Apify's public actor-metadata
API, 2026-11 -- not guessed): no required fields. `settlements` (array of
Hebrew names, empty = whole country), `regions`, `landUse`, `tenderTypes`,
`statuses`, `openForBidsOnly`, `publishedFrom`/`publishedTo` (YYYY-MM-DD),
`minHousingUnits`, `maxItems` (optional cost cap), `enrichDetails`
(reserve price, deposit, lot areas, development costs, winning bidder and
amount where published -- on by default), `outputMode` ('tender' keeps a
tender's lots nested, 'lot' flattens to one row per lot/winner; the actor
itself defaults to 'tender')."""
from config import db
from backend.estates_data.modals.estates_data import RawIngestRecord
from backend.estates_data.connectors.apify_client import run_actor_sync

SOURCE = 'rmi_tenders'
ACTOR_ID = 'swerve~israel-land-tenders'

PILOT_SETTLEMENTS_HEBREW = {
    'beit_shemesh': 'בית שמש',
    'jerusalem': 'ירושלים',
}


def _external_id(record):
    """Tender number is the Authority's own stable identifier -- used
    directly (plus a lot number when output_mode='lot' splits a tender
    into several rows), same idempotency guarantee as data_gov_il.py's
    native `_id` field, no derived hash needed here."""
    number = record.get('tenderNumber') or record.get('michrazNumber')
    lot = record.get('lotNumber') or record.get('lot')
    if not number:
        return None
    return f'{number}:{lot}' if lot else str(number)


def ingest_settlements(settlements_hebrew=None, output_mode='lot', **filters):
    """Runs the actor and stages every returned tender (or lot, depending
    on output_mode) as a RawIngestRecord. Returns the count of NEW rows
    staged. `output_mode='lot'` is the default HERE (not the actor's own
    default of 'tender') because LandTender in this package's model is
    per-lot, matching one winner/price/buildable-units triple each."""
    run_input = {'outputMode': output_mode}
    if settlements_hebrew:
        run_input['settlements'] = list(settlements_hebrew)
    run_input.update(filters)

    items = run_actor_sync(ACTOR_ID, run_input)
    staged = 0
    for item in items:
        external_id = _external_id(item)
        if not external_id:
            continue
        if RawIngestRecord.query.filter_by(source=SOURCE, external_id=external_id).first():
            continue
        db.session.add(RawIngestRecord(source=SOURCE, external_id=external_id, payload=item))
        staged += 1
    db.session.commit()
    return staged


# Uniform entrypoint routes/estates_data.py's run_ingest() calls on every
# connector -- see nadlan_gov.py and data_gov_il.py for their own aliases.
ingest = ingest_settlements
