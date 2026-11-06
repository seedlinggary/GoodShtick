"""Household (Family) de-duplication -- Nedarim Plus itself never de-
dupes donors (a husband and wife each submitting their own form becomes
two unrelated records), so this is purely an admin-side grouping layer:
Family CRUD, a global cross-type search ("pull up everything about this
person from one box"), auto-generated merge recommendations (union-find
clustering by normalized email/phone), and the merge/unlink mechanics
themselves. Flagged in this module's own porting notes as genuinely non-
trivial business logic, not a CRUD feature -- ported as faithfully as the
rest of this module.
"""
import re

from flask import Blueprint, jsonify, request

from config import db
from backend.business.modals.nonprofit import (
    NonprofitFamily, NonprofitBill, NonprofitDonation, NonprofitMembership,
    NonprofitPaymentLink, NonprofitExternalTransaction, NonprofitForm, NonprofitFormResponse,
    NonprofitPaymentFollowUp,
)
from backend.business.nonprofit_auth import staff_required
from backend.business.routes.nonprofit_audit import record_audit_log
from backend.business.routes.nonprofit_import_helpers import csv_response

nonprofit_families_api = Blueprint('nonprofit_families_api', __name__, url_prefix='/nonprofit')

# Every record type that can carry a family_id -- shared by search, merge,
# and merge-recommendation clustering so adding a new payable type later
# means touching one list, not four separate functions.
_MERGEABLE_MODELS = (NonprofitBill, NonprofitDonation, NonprofitMembership, NonprofitPaymentLink, NonprofitExternalTransaction)


def _check_business(staff, business_id):
    if staff.business_id != business_id:
        return jsonify({'message': 'Not authorized for this organization'}), 403
    return None


def _serialize_family(f):
    return {
        'id': f.id, 'full_name': f.full_name, 'email': f.email, 'phone': f.phone,
        'address': f.address, 'city': f.city, 'notes': f.notes,
        'created_at': f.created_at.isoformat() if f.created_at else None,
    }


def _record_summary(model, row):
    name_field = getattr(row, 'full_name', None) or getattr(row, 'client_name', None)
    amount = getattr(row, 'amount_cents', None) or getattr(row, 'monthly_cents', None) or getattr(row, 'total_cents', None)
    return {
        'type': model.__name__, 'id': row.id, 'name': name_field, 'amount_cents': amount,
        'status': getattr(row, 'status', None),
    }


@nonprofit_families_api.route('/businesses/<int:business_id>/families', methods=['GET'])
@staff_required
def list_families(staff, business_id):
    err = _check_business(staff, business_id)
    if err:
        return err
    rows = NonprofitFamily.query.filter_by(business_id=business_id).order_by(NonprofitFamily.full_name).all()
    return jsonify({'families': [_serialize_family(f) for f in rows]})


@nonprofit_families_api.route('/businesses/<int:business_id>/families', methods=['POST'])
@staff_required
def create_family(staff, business_id):
    """A standalone "+ Add family" -- every other way a Family row comes
    into existence is a side effect of merging records together
    (merge_into_family below auto-creates one when no target family_id
    is given). This is the one direct path, used by the Families page's
    own create button and by anything that wants to link a record type
    NOT in _MERGEABLE_MODELS (e.g. a form response) to a brand new family
    instead of an existing one."""
    err = _check_business(staff, business_id)
    if err:
        return err
    body = request.get_json() or {}
    full_name = (body.get('full_name') or '').strip()
    if not full_name:
        return jsonify({'message': 'full_name is required'}), 400
    family = NonprofitFamily(
        business_id=business_id, full_name=full_name,
        email=(body.get('email') or '').strip() or None, phone=(body.get('phone') or '').strip() or None,
        address=(body.get('address') or '').strip() or None, city=(body.get('city') or '').strip() or None,
        notes=(body.get('notes') or '').strip() or None,
    )
    db.session.add(family)
    db.session.flush()
    record_audit_log(business_id, staff.email, 'family_create', 'NonprofitFamily', family.id, None)
    db.session.commit()
    return jsonify(_serialize_family(family)), 201


@nonprofit_families_api.route('/businesses/<int:business_id>/families/export', methods=['GET'])
@staff_required
def export_families(staff, business_id):
    err = _check_business(staff, business_id)
    if err:
        return err
    rows = NonprofitFamily.query.filter_by(business_id=business_id).order_by(NonprofitFamily.full_name).all()
    header = ['Name', 'Email', 'Phone', 'Address', 'City', 'Notes', 'Created']
    data = [[f.full_name, f.email or '', f.phone or '', f.address or '', f.city or '', f.notes or '',
             f.created_at.isoformat() if f.created_at else ''] for f in rows]
    return csv_response(header, data, 'families.csv')


@nonprofit_families_api.route('/families/<int:family_id>', methods=['GET'])
@staff_required
def get_family(staff, family_id):
    family = NonprofitFamily.query.get(family_id)
    if not family or family.business_id != staff.business_id:
        return jsonify({'message': 'Family not found'}), 404

    linked = []
    for model in _MERGEABLE_MODELS:
        for row in model.query.filter_by(family_id=family_id).all():
            linked.append(_record_summary(model, row))
    form_responses = NonprofitFormResponse.query.filter_by(family_id=family_id, deleted_at=None).count()

    return jsonify({'family': _serialize_family(family), 'records': linked, 'form_response_count': form_responses})


@nonprofit_families_api.route('/families/<int:family_id>', methods=['PATCH'])
@staff_required
def update_family(staff, family_id):
    family = NonprofitFamily.query.get(family_id)
    if not family or family.business_id != staff.business_id:
        return jsonify({'message': 'Family not found'}), 404
    body = request.get_json() or {}
    for field in ('full_name', 'email', 'phone', 'address', 'city', 'notes'):
        if field in body:
            setattr(family, field, body[field])
    db.session.commit()
    return jsonify(_serialize_family(family))


@nonprofit_families_api.route('/records/unlink', methods=['POST'])
@staff_required
def unlink_record(staff):
    """Unlinks one record from its Family -- auto-deletes the Family if
    it becomes empty (no other record and no form response still pointed
    at it)."""
    body = request.get_json() or {}
    record_type = body.get('record_type')
    record_id = body.get('record_id')
    model = next((m for m in _MERGEABLE_MODELS if m.__name__ == record_type), None)
    if not model:
        return jsonify({'message': 'Unknown record_type'}), 400

    record = model.query.get(record_id)
    if not record or record.business_id != staff.business_id:
        return jsonify({'message': 'Record not found'}), 404

    family_id = record.family_id
    record.family_id = None
    record_audit_log(staff.business_id, staff.email, 'unlink_from_family', record_type, record.id, None)
    db.session.flush()

    if family_id:
        _delete_family_if_empty(family_id)
    db.session.commit()
    return jsonify({'message': 'Unlinked'})


def _delete_family_if_empty(family_id):
    still_linked = any(model.query.filter_by(family_id=family_id).first() for model in _MERGEABLE_MODELS)
    still_linked = still_linked or NonprofitFormResponse.query.filter_by(family_id=family_id).first()
    if not still_linked:
        family = NonprofitFamily.query.get(family_id)
        if family:
            db.session.delete(family)


@nonprofit_families_api.route('/businesses/<int:business_id>/families/merge', methods=['POST'])
@staff_required
def merge_into_family(staff, business_id):
    """Combines a checked set of rows (any mix of record types, and
    optionally rows that already belong to DIFFERENT existing Families)
    onto one Family. If some checked rows already belong to other
    Families, those Families get FOLDED into the target (their other
    records re-pointed, the now-empty duplicate Family rows deleted)
    rather than creating yet another duplicate grouping. Blank fields on
    the target Family get backfilled from the merged records' own
    contact info, but an existing non-blank value is never overwritten.
    """
    err = _check_business(staff, business_id)
    if err:
        return err
    body = request.get_json() or {}
    items = body.get('items') or []  # [{record_type, record_id}]
    target_family_id = body.get('family_id')  # None = create a new Family

    if not items:
        return jsonify({'message': 'No records selected'}), 400

    records = []
    other_family_ids = set()
    for item in items:
        model = next((m for m in _MERGEABLE_MODELS if m.__name__ == item.get('record_type')), None)
        if not model:
            continue
        record = model.query.get(item.get('record_id'))
        if not record or record.business_id != business_id:
            continue
        records.append(record)
        if record.family_id and record.family_id != target_family_id:
            other_family_ids.add(record.family_id)

    if not records:
        return jsonify({'message': 'No valid records selected'}), 400

    if target_family_id:
        family = NonprofitFamily.query.get(target_family_id)
        if not family or family.business_id != business_id:
            return jsonify({'message': 'Target family not found'}), 404
    else:
        first = records[0]
        family = NonprofitFamily(business_id=business_id, full_name=getattr(first, 'full_name', None) or getattr(first, 'client_name', None) or 'Unknown')
        db.session.add(family)
        db.session.flush()

    # Fold any OTHER family these records already belonged to into the
    # target -- re-point every record of that family, then delete the
    # now-empty duplicate, instead of leaving two groupings for the same
    # household.
    for other_id in other_family_ids:
        if other_id == family.id:
            continue
        for model in _MERGEABLE_MODELS:
            for row in model.query.filter_by(family_id=other_id).all():
                row.family_id = family.id
        for resp in NonprofitFormResponse.query.filter_by(family_id=other_id).all():
            resp.family_id = family.id
        other = NonprofitFamily.query.get(other_id)
        if other:
            _backfill_family_fields(family, other)
            db.session.delete(other)

    for record in records:
        record.family_id = family.id
        _backfill_family_fields(family, record)

    record_audit_log(business_id, staff.email, 'families_merge', 'NonprofitFamily', family.id,
                      {'merged_record_count': {'before': None, 'after': len(records)}})
    db.session.commit()
    return jsonify(_serialize_family(family))


def _backfill_family_fields(family, source):
    """Fills a blank Family field from `source`'s own contact info --
    never overwrites a value the Family already has."""
    for family_field, source_field in (('email', 'email'), ('phone', 'phone'), ('address', 'address'), ('city', 'city')):
        if not getattr(family, family_field, None):
            value = getattr(source, source_field, None)
            if value:
                setattr(family, family_field, value)


# ── Global search ───────────────────────────────────────────────────────

def _matches(text, needle):
    return text and needle.lower() in str(text).lower()


@nonprofit_families_api.route('/businesses/<int:business_id>/search', methods=['GET'])
@staff_required
def search_everything(staff, business_id):
    """Cross-type search across every mergeable record, every standalone
    follow-up, and every dynamic form response -- the last via a JSON-
    text scan of `answers` since FormResponse has no fixed identity
    columns to filter on."""
    err = _check_business(staff, business_id)
    if err:
        return err
    q = (request.args.get('q') or '').strip()
    if not q:
        return jsonify({'results': []})

    results = []
    for model in _MERGEABLE_MODELS:
        for row in model.query.filter_by(business_id=business_id).limit(500).all():
            name = getattr(row, 'full_name', None) or getattr(row, 'client_name', None)
            haystacks = [name, getattr(row, 'email', None), getattr(row, 'phone', None), getattr(row, 'reference_code', None)]
            if any(_matches(h, q) for h in haystacks):
                results.append(_record_summary(model, row))

    standalone = NonprofitPaymentFollowUp.query.filter_by(business_id=business_id).filter(
        NonprofitPaymentFollowUp.bill_id.is_(None), NonprofitPaymentFollowUp.donation_id.is_(None),
        NonprofitPaymentFollowUp.membership_id.is_(None), NonprofitPaymentFollowUp.payment_link_id.is_(None),
    ).limit(200).all()
    for f in standalone:
        if any(_matches(h, q) for h in (f.external_full_name, f.external_email, f.external_phone)):
            results.append({'type': 'NonprofitPaymentFollowUp', 'id': f.id, 'name': f.external_full_name, 'amount_cents': f.external_amount_cents, 'status': f.status})

    like_pattern = f'%{q}%'
    form_rows = (
        NonprofitFormResponse.query.join(NonprofitForm, NonprofitFormResponse.form_id == NonprofitForm.id)
        .filter(
            NonprofitForm.business_id == business_id,
            NonprofitFormResponse.deleted_at.is_(None),
            db.cast(NonprofitFormResponse.answers, db.Text).ilike(like_pattern),
        ).limit(100).all()
    )
    for row in form_rows:
        results.append({'type': 'NonprofitFormResponse', 'id': row.id, 'name': None, 'amount_cents': None, 'status': None})

    return jsonify({'results': results})


# ── Merge recommendations (union-find clustering) ──────────────────────

def _normalize_email(email):
    return (email or '').strip().lower() or None


def _normalize_phone(phone):
    digits = re.sub(r'\D', '', phone or '')
    return digits or None


class _UnionFind:
    def __init__(self):
        self.parent = {}

    def find(self, x):
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            x = self.parent[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[ra] = rb


MAX_CLUSTER_SIZE = 15


@nonprofit_families_api.route('/businesses/<int:business_id>/families/merge-recommendations', methods=['GET'])
@staff_required
def merge_recommendations(staff, business_id):
    """Clusters every mergeable record by normalized email/phone via
    union-find, surfacing "these look like the same household" groups.
    Caps a cluster at MAX_CLUSTER_SIZE -- a shared office email/phone
    (e.g. the organization's own general inbox used on several records)
    would otherwise flag as one giant, useless cluster."""
    err = _check_business(staff, business_id)
    if err:
        return err

    uf = _UnionFind()
    node_info = {}  # node_key -> {'type', 'id', 'name', 'family_id'}
    key_by_email, key_by_phone = {}, {}

    for model in _MERGEABLE_MODELS:
        for row in model.query.filter_by(business_id=business_id).all():
            if row.family_id:
                continue  # already grouped -- nothing to recommend
            node_key = f'{model.__name__}:{row.id}'
            node_info[node_key] = {
                'type': model.__name__, 'id': row.id,
                'name': getattr(row, 'full_name', None) or getattr(row, 'client_name', None),
            }
            email = _normalize_email(getattr(row, 'email', None))
            phone = _normalize_phone(getattr(row, 'phone', None))
            if email:
                if email in key_by_email:
                    uf.union(node_key, key_by_email[email])
                else:
                    key_by_email[email] = node_key
            if phone:
                if phone in key_by_phone:
                    uf.union(node_key, key_by_phone[phone])
                else:
                    key_by_phone[phone] = node_key
            uf.find(node_key)

    clusters = {}
    for node_key in node_info:
        root = uf.find(node_key)
        clusters.setdefault(root, []).append(node_info[node_key])

    recommendations = [
        {'items': members}
        for members in clusters.values()
        if 1 < len(members) <= MAX_CLUSTER_SIZE
    ]
    return jsonify({'recommendations': recommendations})
