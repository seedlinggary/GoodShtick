"""Generic manual-entry connector -- for any source with no free,
automatable access of its own. Arnona rate tables always go through this
path (they're only ever published as a yearly PDF per city). Until/unless
a paid vendor or a real open API exists, nadlan.gov.il sale deals and RMI
tender results go through it too, by exporting them from the source's own
public search page -- used exactly as any visitor would use it -- and
uploading that export here.

Nothing in this file ever reaches out to a government site. A human did
that, through the site's own normal UI, with no automation involved; this
just gets what they found into the pipeline, staged as RawIngestRecord
rows the exact same way every automated connector in this package does
it, so normalize.py treats a hand-entered row no differently from a
scraped one."""
import csv
import hashlib
import io
import json

from config import db
from backend.estates_data.modals.estates_data import RawIngestRecord


def _row_external_id(source, row):
    """Hashes the row's own contents, rather than relying on a column the
    CSV might not have, so re-uploading the same export -- or a refreshed
    export that repeats most of the old rows -- stages only what's
    actually new."""
    digest = hashlib.sha256(json.dumps(row, sort_keys=True, default=str).encode()).hexdigest()
    return digest[:40]


def ingest_csv(source, csv_text):
    """Parses `csv_text` (first row = headers, any column names) and
    stages each row as a RawIngestRecord under the given `source` label.
    Use a label distinct from an automated connector's own SOURCE
    constant -- e.g. 'nadlan_gov_manual' rather than 'nadlan_gov' -- so a
    hand-entered batch stays identifiable from where it came from.
    Returns the count of NEW rows staged."""
    if not csv_text or not csv_text.strip():
        return 0
    reader = csv.DictReader(io.StringIO(csv_text))
    staged = 0
    for row in reader:
        external_id = _row_external_id(source, row)
        if RawIngestRecord.query.filter_by(source=source, external_id=external_id).first():
            continue
        db.session.add(RawIngestRecord(source=source, external_id=external_id, payload=row))
        staged += 1
    db.session.commit()
    return staged


# Uniform entrypoint -- see data_gov_il.py/nadlan_gov.py/rmi_tenders.py for
# their own aliases. Unlike those, this one is called through its own
# dedicated upload route (routes/estates_data.py's import_csv), not the
# generic JSON-body /admin/ingest/<source> route, since it takes a file.
ingest = ingest_csv
