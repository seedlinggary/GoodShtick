"""CKAN client for data.gov.il -- the one source in this package with an
actual documented, officially-sanctioned API (confirmed reachable: see the
plan's source-landscape table). Every function here only reads from
data.gov.il and writes RawIngestRecord rows -- it never touches a canonical
table, same contract as every other connector in this package (see
normalize.py for that step)."""
import requests

from config import db
from backend.estates_data.modals.estates_data import RawIngestRecord

BASE_URL = 'https://data.gov.il/api/3/action'
SOURCE = 'data_gov_il'
TIMEOUT = 20


def search_packages(query, rows=20):
    """Keyword search over data.gov.il's dataset catalog -- for finding a
    resource_id to pass to ingest_resource(), not used by ingestion itself."""
    resp = requests.get(f'{BASE_URL}/package_search', params={'q': query, 'rows': rows}, timeout=TIMEOUT)
    resp.raise_for_status()
    return resp.json().get('result', {})


def fetch_datastore(resource_id, limit=1000, offset=0):
    resp = requests.get(
        f'{BASE_URL}/datastore_search',
        params={'resource_id': resource_id, 'limit': limit, 'offset': offset},
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json().get('result', {})


def ingest_resource(resource_id, id_field='_id', page_size=1000, max_pages=50):
    """Pages through one CKAN resource and stages every row as a
    RawIngestRecord, keyed by (SOURCE, "<resource_id>:<row[id_field]>") --
    a row already staged by a previous run is skipped, not duplicated, so
    this is safe to schedule repeatedly. Returns the count of NEW rows
    staged."""
    staged = 0
    offset = 0
    for _ in range(max_pages):
        result = fetch_datastore(resource_id, limit=page_size, offset=offset)
        records = result.get('records', [])
        if not records:
            break
        for row in records:
            external_id = f'{resource_id}:{row.get(id_field)}'
            exists = RawIngestRecord.query.filter_by(source=SOURCE, external_id=external_id).first()
            if exists:
                continue
            db.session.add(RawIngestRecord(source=SOURCE, external_id=external_id, payload=row))
            staged += 1
        db.session.commit()
        if len(records) < page_size:
            break
        offset += page_size
    return staged


# Uniform entrypoint routes/estates_data.py's run_ingest() calls on every
# connector -- see nadlan_gov.py and rmi_tenders.py for their own aliases.
ingest = ingest_resource
