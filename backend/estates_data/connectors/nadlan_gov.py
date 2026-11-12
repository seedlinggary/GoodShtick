"""Connector for nadlan.gov.il -- the Israel Tax Authority's public sold-
property deals registry.

nadlan.gov.il itself has no API reachable without impersonating a
browser: it's Israeli-IP-only, and every undocumented endpoint found
required spoofed Origin/Referer/User-Agent headers to pass its anti-bot
protection. This connector does not do that. Instead it pays a licensed
data vendor -- Apify's `swerve/nadlan-gov-deals` actor -- through Apify's
own documented, API-key-authenticated REST API (see apify_client.py):
an ordinary paid API client relationship, not scraping. Apify's actor
handles the Israeli residential proxy and any anti-bot handling itself,
as part of its own product, under its own terms.

**Every call to ingest_cities() is billed by Apify** (pricing: from
$10.00 per 1,000 results as of the actor's published pricing) and
requires APIFY_API_TOKEN to be set with billing enabled on the account --
nothing here runs for free, and nothing runs at all without that token.

Confirmed actor input schema (fetched from Apify's public actor-metadata
API, 2026-11 -- not guessed): `cities` (required, array of Hebrew
locality names, from a fixed list of 945 supported localities),
`dealDateRange` ('3m'/'6m'/'12m'/'36m'/'all', default '12m'), `rooms`
(comma-separated string filter, e.g. "3,4"), `minPrice`/`maxPrice` (ILS),
`includeNonResidential` (bool, default false), `maxItems` (optional cost
cap -- left None here fetches ALL matching deals, which can be large and
expensive for a big city + 'all' date range; pass it explicitly to bound
cost on a first run).

Per-deal fields the actor returns (per its own README, matching this
package's model almost field-for-field): signing date, price, price per
sqm, address, neighborhood, rooms, area, property type, floor,
buildingFloors, gush/helka/tat-helka, isFirstHand, and -- for roughly one
deal in five -- the SAME unit's prior sale (prevDeals/trend). Mapping
that payload into GeoParcel/Unit/SaleTransaction is normalize.py's job,
not this file's -- this connector only stages raw rows."""
import hashlib
import json

from config import db
from backend.estates_data.modals.estates_data import RawIngestRecord
from backend.estates_data.connectors.apify_client import run_actor_sync

SOURCE = 'nadlan_gov'
ACTOR_ID = 'swerve~nadlan-gov-deals'

# This plan's pilot cities, in the Hebrew spelling the actor's own
# supported-locality list uses (confirmed present in that list).
PILOT_CITIES_HEBREW = {
    'beit_shemesh': 'בית שמש',
    'jerusalem': 'ירושלים',
}


def _external_id(record):
    """The actor has no single field that uniquely identifies a deal
    across every response, so one is derived from the fields that
    together do (parcel + signing date + price + address) -- stable
    across re-runs, so re-ingesting the same city/date-range stays
    idempotent instead of re-staging the same deals."""
    key_fields = {k: record.get(k) for k in ('gush', 'helka', 'tatHelka', 'dealDate', 'price', 'address')}
    digest = hashlib.sha256(json.dumps(key_fields, sort_keys=True, default=str).encode()).hexdigest()
    return digest[:40]


def ingest_cities(cities_hebrew, deal_date_range='12m', max_items=None, **filters):
    """Runs the actor for the given Hebrew city names and stages every
    returned deal as a RawIngestRecord. Returns the count of NEW rows
    staged (a deal already staged by a previous run is skipped, not
    duplicated, via _external_id above)."""
    run_input = {'cities': list(cities_hebrew), 'dealDateRange': deal_date_range}
    if max_items is not None:
        run_input['maxItems'] = max_items
    run_input.update(filters)

    items = run_actor_sync(ACTOR_ID, run_input)
    staged = 0
    for item in items:
        external_id = _external_id(item)
        if RawIngestRecord.query.filter_by(source=SOURCE, external_id=external_id).first():
            continue
        db.session.add(RawIngestRecord(source=SOURCE, external_id=external_id, payload=item))
        staged += 1
    db.session.commit()
    return staged


# Uniform entrypoint routes/estates_data.py's run_ingest() calls on every
# connector -- see rmi_tenders.py and data_gov_il.py for their own aliases.
ingest = ingest_cities
