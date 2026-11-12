from flask import Blueprint, jsonify, request

from security import admin_required
from backend.estates_data.modals.estates_data import RawIngestRecord, ArnonaRate
from backend.estates_data.connectors import data_gov_il, nadlan_gov, rmi_tenders, manual_import
from backend.estates_data.connectors.apify_client import ApifyNotConfigured

estates_data_api = Blueprint('estates_data_api', __name__, url_prefix='/estates-data')

# Every connector exposes one `ingest(**kwargs)` entrypoint (see each
# module's own `ingest = ...` alias) so run_ingest() below can call any of
# them the same way, passing the request body straight through as kwargs.
# nadlan_gov and rmi_tenders are billed Apify actor runs (see their
# docstrings) -- registering them here does not run anything by itself,
# they only run when POSTed to explicitly.
CONNECTORS = {
    'data_gov_il': data_gov_il,
    'nadlan_gov': nadlan_gov,
    'rmi_tenders': rmi_tenders,
}


def _raw_record_dict(r):
    return {
        'id': r.id,
        'source': r.source,
        'external_id': r.external_id,
        'fetched_at': r.fetched_at.isoformat() if r.fetched_at else None,
        'status': r.status,
        'error': r.error,
        'payload': r.payload,
    }


@estates_data_api.route('/admin/raw', methods=['GET'])
@admin_required
def list_raw_records(current_user):
    source = request.args.get('source')
    status = request.args.get('status')
    page = max(1, int(request.args.get('page', 1)))
    page_size = min(100, max(1, int(request.args.get('page_size', 25))))

    query = RawIngestRecord.query
    if source:
        query = query.filter_by(source=source)
    if status:
        query = query.filter_by(status=status)
    query = query.order_by(RawIngestRecord.fetched_at.desc())

    total = query.count()
    rows = query.offset((page - 1) * page_size).limit(page_size).all()
    return jsonify({
        'total': total,
        'page': page,
        'page_size': page_size,
        'results': [_raw_record_dict(r) for r in rows],
    })


@estates_data_api.route('/admin/ingest/<source>', methods=['POST'])
@admin_required
def run_ingest(current_user, source):
    """Body is passed straight through as kwargs to that connector's
    ingest() -- see each connector module's docstring for what it takes
    (e.g. data_gov_il needs `resource_id`; nadlan_gov needs
    `cities_hebrew`; rmi_tenders takes everything optionally). nadlan_gov
    and rmi_tenders are BILLED Apify actor runs -- nothing about this
    route caps that spend beyond whatever `max_items`/`maxItems` is
    passed in the body, so pass one explicitly on a first run."""
    connector = CONNECTORS.get(source)
    if not connector:
        return jsonify({'error': f'Unknown source "{source}". Known: {list(CONNECTORS)}'}), 400

    body = request.get_json(silent=True) or {}
    try:
        staged = connector.ingest(**body)
    except ApifyNotConfigured as exc:
        return jsonify({'error': str(exc)}), 400
    except TypeError as exc:
        return jsonify({'error': f'Bad arguments for "{source}": {exc}'}), 400
    except Exception as exc:
        return jsonify({'error': str(exc)}), 502
    return jsonify({'staged': staged})


@estates_data_api.route('/admin/import-csv/<source>', methods=['POST'])
@admin_required
def import_csv(current_user, source):
    """Hand-pulled data goes here, not through /admin/ingest/<source> --
    this takes a CSV file (multipart form field "file"), not a JSON body.
    Use a source label distinct from an automated connector's own SOURCE
    constant, e.g. "nadlan_gov_manual" for a nadlan.gov.il export, so it
    stays identifiable as hand-entered. See connectors/manual_import.py."""
    upload = request.files.get('file')
    if not upload:
        return jsonify({'error': 'file is required (multipart form field "file")'}), 400

    try:
        csv_text = upload.read().decode('utf-8-sig')
    except UnicodeDecodeError:
        return jsonify({'error': 'Could not read the file as UTF-8 CSV text'}), 400

    staged = manual_import.ingest(source, csv_text)
    return jsonify({'staged': staged})


@estates_data_api.route('/admin/search-sources', methods=['GET'])
@admin_required
def search_sources(current_user):
    """Thin pass-through to data_gov_il's package_search -- lets an admin
    look up a dataset's resource_id to feed into run_ingest() above,
    without needing to hit data.gov.il directly from a browser."""
    q = request.args.get('q', '')
    if not q:
        return jsonify({'error': 'q is required'}), 400
    try:
        result = data_gov_il.search_packages(q)
    except Exception as exc:
        return jsonify({'error': str(exc)}), 502
    return jsonify(result)


# ── Arnona rates -- manually entered, admin-only ──────────────────────────
ARNONA_FIELDS = ('municipality', 'year', 'zone', 'use_type', 'rate_per_sqm', 'currency', 'source_name', 'source_url')


def _arnona_dict(r):
    return {f: getattr(r, f) for f in ARNONA_FIELDS} | {'id': r.id}


@estates_data_api.route('/admin/arnona-rates', methods=['GET'])
@admin_required
def list_arnona_rates(current_user):
    municipality = request.args.get('municipality')
    query = ArnonaRate.query
    if municipality:
        query = query.filter_by(municipality=municipality)
    rows = query.order_by(ArnonaRate.municipality, ArnonaRate.year.desc()).all()
    return jsonify({'results': [_arnona_dict(r) for r in rows]})


@estates_data_api.route('/admin/arnona-rates', methods=['POST'])
@admin_required
def create_arnona_rate(current_user):
    from config import db

    body = request.get_json(silent=True) or {}
    missing = [f for f in ('municipality', 'year', 'rate_per_sqm', 'source_name') if not body.get(f)]
    if missing:
        return jsonify({'error': f'Missing required field(s): {", ".join(missing)}'}), 400

    rate = ArnonaRate(
        municipality=body['municipality'],
        year=body['year'],
        rate_per_sqm=body['rate_per_sqm'],
        source_name=body['source_name'],
        zone=body.get('zone'),
        use_type=body.get('use_type', 'residential'),
        currency=body.get('currency', 'ILS'),
        source_url=body.get('source_url'),
        entered_by=current_user.public_id,
    )
    db.session.add(rate)
    db.session.commit()
    return jsonify(_arnona_dict(rate)), 201
