import os
import re
import secrets
from collections import defaultdict
from datetime import datetime

from flask import Blueprint, jsonify, request, redirect
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from config import db
from security import super_admin_required, token_optional, real_client_ip
from backend.giveaways.modals.giveaway import (
    GiveawayCampaign, GiveawayEntryAction, GiveawayParticipant, GiveawayParticipation,
    GiveawayEntry, GiveawayReferralClick, GiveawayDrawSnapshot, GiveawayDraw,
    VERIFICATION_METHODS, check_and_record_giveaway_entry,
)
from backend.giveaways.schemas.giveaway import make_campaign_schema, make_entry_action_schema
from backend.giveaways.emails import (
    send_giveaway_verify_email, send_giveaway_confirmed_email, send_giveaway_winner_email,
)
from backend.campaigns.modals.campaign import MarketingCampaign
from backend.user.modals.audit_log import log_admin_action
from backend.business.routes.nonprofit_import_helpers import csv_response

giveaway_api = Blueprint('giveaway_api', __name__, url_prefix='/giveaways')

PAGE_SIZE = 50
MAIN_SITE_URL = os.environ.get('MAIN_SITE_URL', 'https://www.gutshtick.com')
SETTABLE_STATUSES = ('draft', 'scheduled', 'active', 'paused', 'closed')
TERMINAL_STATUSES = ('winner_selected', 'completed')
# Minimum number of DISTINCT participations sharing one IP address before a
# fraud-scan flags them -- a flag only, never an auto-disqualify (the spec
# explicitly says not to auto-disqualify on shared IP alone; a shul/office/
# school WiFi can easily be dozens of real entrants on one address).
IP_CLUSTER_THRESHOLD = 5
EDITABLE_FIELDS = ('name', 'description', 'campaign_type', 'sites', 'prize_details',
                    'terms_text', 'privacy_note', 'image_url', 'entry_rules')

# Same substring list/reasoning as backend/analytics/routes/visitor.py's
# BOT_UA_SUBSTRINGS -- not a security boundary (a bot that sends a normal-
# looking UA sails right through), just enough to stop the obvious case of
# a script hitting this form with its library's default User-Agent.
BOT_UA_SUBSTRINGS = (
    'bot', 'crawl', 'spider', 'slurp', 'headless', 'phantom', 'puppeteer',
    'playwright', 'selenium', 'scrapy', 'curl', 'wget', 'python-requests',
    'python-urllib', 'go-http-client', 'java/', 'libwww-perl', 'axios/',
)


def _looks_like_bot_ua():
    ua = (request.headers.get('User-Agent') or '').lower()
    if not ua:
        return True  # a real browser always sends one
    return any(s in ua for s in BOT_UA_SUBSTRINGS)


# ── helpers ──────────────────────────────────────────────────────────────

def _slugify(text):
    slug = re.sub(r'[^a-z0-9]+', '-', (text or '').lower()).strip('-')
    return slug or secrets.token_hex(3)


def _unique_slug(name):
    base = _slugify(name)
    slug = base
    n = 2
    while GiveawayCampaign.query.filter_by(slug=slug).first():
        slug = f'{base}-{n}'
        n += 1
    return slug


def _parse_dt(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00')).replace(tzinfo=None)
    except (ValueError, AttributeError):
        return None


def _entry_total(participation_id):
    # pending_review (a 'manual' action awaiting admin approval) never
    # counts until approved -- auto/self_certify entries are written
    # straight to 'verified' (trusted immediately, reviewed after the
    # fact via invalidate, see GiveawayEntry's own docstring), so this
    # exclusion only ever affects manual-verification entries.
    total = db.session.query(func.coalesce(func.sum(GiveawayEntry.entry_quantity), 0)).filter(
        GiveawayEntry.participation_id == participation_id, GiveawayEntry.invalidated.is_(False),
        GiveawayEntry.verification_status != 'pending_review',
    ).scalar()
    return int(total or 0)


def _entry_totals(participation_ids):
    if not participation_ids:
        return {}
    rows = (db.session.query(GiveawayEntry.participation_id, func.sum(GiveawayEntry.entry_quantity))
            .filter(GiveawayEntry.participation_id.in_(participation_ids), GiveawayEntry.invalidated.is_(False),
                    GiveawayEntry.verification_status != 'pending_review')
            .group_by(GiveawayEntry.participation_id).all())
    return {pid: int(total) for pid, total in rows}


def _stats_for_campaigns(campaign_ids):
    if not campaign_ids:
        return {}
    participations = GiveawayParticipation.query.filter(GiveawayParticipation.campaign_id.in_(campaign_ids)).all()
    by_campaign = defaultdict(list)
    for p in participations:
        by_campaign[p.campaign_id].append(p)
    totals = _entry_totals([p.id for p in participations])

    click_counts = dict(
        db.session.query(GiveawayParticipation.campaign_id, func.count(GiveawayReferralClick.id))
        .join(GiveawayReferralClick, GiveawayReferralClick.participation_id == GiveawayParticipation.id)
        .filter(GiveawayParticipation.campaign_id.in_(campaign_ids))
        .group_by(GiveawayParticipation.campaign_id).all()
    )
    qualified_counts = dict(
        db.session.query(GiveawayParticipation.campaign_id, func.count(GiveawayEntry.id))
        .join(GiveawayEntry, GiveawayEntry.participation_id == GiveawayParticipation.id)
        .filter(GiveawayParticipation.campaign_id.in_(campaign_ids), GiveawayEntry.action_key == 'referral_qualified',
                GiveawayEntry.invalidated.is_(False))
        .group_by(GiveawayParticipation.campaign_id).all()
    )

    stats = {}
    for cid in campaign_ids:
        plist = by_campaign.get(cid, [])
        participants = len(plist)
        verified = sum(1 for p in plist if p.verified_at)
        entries = sum(totals.get(p.id, 0) for p in plist)
        stats[cid] = {
            'participants': participants,
            'verified': verified,
            'entries': entries,
            'referral_clicks': click_counts.get(cid, 0),
            'qualified_referrals': qualified_counts.get(cid, 0),
            'conversion_rate': round(verified / participants * 100, 1) if participants else 0,
        }
    return stats


def _participation_dict(p, entry_total=None):
    participant = p.participant
    return {
        'id': p.id,
        'campaign_id': p.campaign_id,
        'participant_id': p.participant_id,
        'name': participant.name if participant else None,
        'email': participant.email if participant else None,
        'phone': participant.phone if participant else None,
        'email_verified': participant.email_verified if participant else False,
        'referral_code': p.referral_code,
        'referrer_participation_id': p.referrer_participation_id,
        'first_touch': p.first_touch,
        'last_touch': p.last_touch,
        'consent_marketing': p.consent_marketing,
        'status': p.status,
        'fraud_flags': p.fraud_flags or [],
        'entry_total': entry_total if entry_total is not None else _entry_total(p.id),
        'verified_at': p.verified_at.isoformat() if p.verified_at else None,
        'created_at': p.created_at.isoformat() if p.created_at else None,
    }


def _eligible_participations(campaign_id):
    """Participations eligible for a draw: verified, not disqualified, every
    currently-enabled REQUIRED entry action actually completed (verified,
    not just pending manual review), and at least one entry. Returns
    [(participation, entry_total)] with entry_total capped at
    entry_rules.max_entries_per_participant if the campaign sets one -- the
    cap is applied only here, at eligibility-computation time, never by
    rejecting a ledger write, so the append-only ledger itself is never
    touched by a campaign-wide rule."""
    campaign = db.session.get(GiveawayCampaign, campaign_id)
    cap = (campaign.entry_rules or {}).get('max_entries_per_participant') if campaign else None
    required_keys = {a.action_key for a in (campaign.entry_actions if campaign else []) if a.is_required and a.is_enabled}

    rows = (GiveawayParticipation.query
            .filter_by(campaign_id=campaign_id)
            .filter(GiveawayParticipation.status != 'disqualified')
            .filter(GiveawayParticipation.verified_at.isnot(None))
            .all())
    totals = _entry_totals([p.id for p in rows])

    completed_required_by_pid = defaultdict(set)
    if required_keys and rows:
        completed_rows = (db.session.query(GiveawayEntry.participation_id, GiveawayEntry.action_key)
                           .filter(GiveawayEntry.participation_id.in_([p.id for p in rows]),
                                   GiveawayEntry.action_key.in_(required_keys),
                                   GiveawayEntry.invalidated.is_(False),
                                   GiveawayEntry.verification_status != 'pending_review').all())
        for pid, action_key in completed_rows:
            completed_required_by_pid[pid].add(action_key)

    result = []
    for p in rows:
        if required_keys and not required_keys.issubset(completed_required_by_pid.get(p.id, set())):
            continue
        entries = totals.get(p.id, 0)
        if cap:
            entries = min(entries, cap)
        if entries > 0:
            result.append((p, entries))
    return result


# ── admin: campaign CRUD ─────────────────────────────────────────────────

@giveaway_api.route('', methods=['GET'])
@super_admin_required
def list_campaigns(_current_user):
    campaigns = GiveawayCampaign.query.order_by(GiveawayCampaign.created_at.desc()).all()
    stats = _stats_for_campaigns([c.id for c in campaigns])
    return jsonify(make_campaign_schema(stats, many=True).dump(campaigns))


@giveaway_api.route('', methods=['POST'])
@super_admin_required
def create_campaign(current_user):
    body = request.get_json(silent=True) or {}
    name = (body.get('name') or '').strip()
    if not name:
        return jsonify({'message': 'Campaign name is required'}), 400
    slug = _slugify(body['slug']) if body.get('slug') else _unique_slug(name)
    if GiveawayCampaign.query.filter_by(slug=slug).first():
        return jsonify({'message': 'That slug is already in use'}), 409

    # Auto-create a MarketingCampaign so this giveaway's outbound channel
    # links (WhatsApp, Instagram, email blast...) come from the existing
    # /campaigns link-tracking system for free -- see AdminCampaigns.js.
    marketing_campaign = MarketingCampaign(
        name=name, description=f'Auto-created for giveaway "{name}"', created_by=current_user.public_id,
    )
    db.session.add(marketing_campaign)
    db.session.flush()

    campaign = GiveawayCampaign(
        name=name, slug=slug,
        description=(body.get('description') or '').strip() or None,
        campaign_type=(body.get('campaign_type') or 'giveaway').strip() or 'giveaway',
        sites=body.get('sites') or None,
        prize_details=body.get('prize_details') or None,
        terms_text=body.get('terms_text') or None,
        privacy_note=body.get('privacy_note') or None,
        image_url=body.get('image_url') or None,
        entry_rules=body.get('entry_rules') or None,
        starts_at=_parse_dt(body.get('starts_at')),
        ends_at=_parse_dt(body.get('ends_at')),
        marketing_campaign_id=marketing_campaign.id,
        created_by=current_user.public_id,
    )
    db.session.add(campaign)
    db.session.commit()
    return jsonify(make_campaign_schema().dump(campaign)), 201


@giveaway_api.route('/<int:campaign_id>', methods=['GET'])
@super_admin_required
def get_campaign(_current_user, campaign_id):
    campaign = db.session.get(GiveawayCampaign, campaign_id)
    if not campaign:
        return jsonify({'message': 'Campaign not found'}), 404
    return jsonify(make_campaign_schema(_stats_for_campaigns([campaign_id])).dump(campaign))


@giveaway_api.route('/<int:campaign_id>', methods=['PATCH'])
@super_admin_required
def update_campaign(current_user, campaign_id):
    campaign = db.session.get(GiveawayCampaign, campaign_id)
    if not campaign:
        return jsonify({'message': 'Campaign not found'}), 404
    body = request.get_json(silent=True) or {}
    for field in EDITABLE_FIELDS:
        if field in body:
            setattr(campaign, field, body[field])
    if 'starts_at' in body:
        campaign.starts_at = _parse_dt(body['starts_at'])
    if 'ends_at' in body:
        campaign.ends_at = _parse_dt(body['ends_at'])
    if 'status' in body:
        if campaign.status in TERMINAL_STATUSES:
            return jsonify({'message': 'This campaign already has a winner selected and its status can no '
                                        'longer be changed here'}), 409
        new_status = body['status']
        if new_status not in SETTABLE_STATUSES:
            return jsonify({'message': f'status must be one of {SETTABLE_STATUSES} '
                                        '(winner_selected/completed are set automatically by the draw)'}), 400
        if new_status == 'active' and not any(a.is_enabled for a in campaign.entry_actions):
            return jsonify({'message': 'Add at least one enabled entry action before activating this campaign'}), 400
        if campaign.status != new_status:
            log_admin_action(current_user, 'giveaway_status_change', 'giveaway_campaign', campaign.id,
                              f'"{campaign.name}": {campaign.status} -> {new_status}')
            campaign.status = new_status
    db.session.commit()
    return jsonify(make_campaign_schema(_stats_for_campaigns([campaign_id])).dump(campaign))


# ── admin: entry actions ─────────────────────────────────────────────────

@giveaway_api.route('/<int:campaign_id>/entry-actions', methods=['POST'])
@super_admin_required
def create_entry_action(_current_user, campaign_id):
    campaign = db.session.get(GiveawayCampaign, campaign_id)
    if not campaign:
        return jsonify({'message': 'Campaign not found'}), 404
    body = request.get_json(silent=True) or {}
    action_key = (body.get('action_key') or '').strip()
    label = (body.get('label') or '').strip()
    if not action_key or not label:
        return jsonify({'message': 'action_key and label are required'}), 400
    verification_method = body.get('verification_method') or 'self_certify'
    if verification_method not in VERIFICATION_METHODS:
        return jsonify({'message': f'verification_method must be one of {VERIFICATION_METHODS}'}), 400
    if GiveawayEntryAction.query.filter_by(campaign_id=campaign_id, action_key=action_key).first():
        return jsonify({'message': 'An action with this key already exists on this campaign'}), 409

    action = GiveawayEntryAction(
        campaign_id=campaign_id, action_key=action_key, label=label,
        description=body.get('description') or None,
        action_url=body.get('action_url') or None,
        entry_quantity=max(1, int(body.get('entry_quantity', 1) or 1)),
        is_required=bool(body.get('is_required', False)),
        verification_method=verification_method,
        max_completions=body.get('max_completions', 1),
        is_enabled=bool(body.get('is_enabled', True)),
        sort_order=int(body.get('sort_order', 0) or 0),
    )
    db.session.add(action)
    db.session.commit()
    return jsonify(make_entry_action_schema().dump(action)), 201


@giveaway_api.route('/entry-actions/<int:action_id>', methods=['PATCH'])
@super_admin_required
def update_entry_action(_current_user, action_id):
    action = db.session.get(GiveawayEntryAction, action_id)
    if not action:
        return jsonify({'message': 'Entry action not found'}), 404
    body = request.get_json(silent=True) or {}
    for field in ('label', 'description', 'action_url'):
        if field in body:
            setattr(action, field, body[field] or None)
    if 'entry_quantity' in body:
        action.entry_quantity = max(1, int(body['entry_quantity'] or 1))
    if 'is_required' in body:
        action.is_required = bool(body['is_required'])
    if 'verification_method' in body:
        if body['verification_method'] not in VERIFICATION_METHODS:
            return jsonify({'message': f'verification_method must be one of {VERIFICATION_METHODS}'}), 400
        action.verification_method = body['verification_method']
    if 'max_completions' in body:
        action.max_completions = body['max_completions']
    if 'is_enabled' in body:
        action.is_enabled = bool(body['is_enabled'])
    if 'sort_order' in body:
        action.sort_order = int(body['sort_order'] or 0)
    db.session.commit()
    return jsonify(make_entry_action_schema().dump(action))


# ── admin: completing a campaign, fraud review ──────────────────────────

@giveaway_api.route('/<int:campaign_id>/complete', methods=['POST'])
@super_admin_required
def complete_campaign(current_user, campaign_id):
    campaign = db.session.get(GiveawayCampaign, campaign_id)
    if not campaign:
        return jsonify({'message': 'Campaign not found'}), 404
    if campaign.status != 'winner_selected':
        return jsonify({'message': 'A campaign can only be marked completed after a winner has been selected'}), 409
    campaign.status = 'completed'
    log_admin_action(current_user, 'giveaway_status_change', 'giveaway_campaign', campaign.id,
                      f'"{campaign.name}": winner_selected -> completed')
    db.session.commit()
    return jsonify(make_campaign_schema(_stats_for_campaigns([campaign_id])).dump(campaign))


@giveaway_api.route('/<int:campaign_id>/fraud-scan', methods=['POST'])
@super_admin_required
def fraud_scan(current_user, campaign_id):
    """Heuristic-only, flags never auto-disqualify (spec: don't auto-
    disqualify on shared IP alone). Groups every ledger entry's ip_address
    by participation; any IP shared by IP_CLUSTER_THRESHOLD or more
    DISTINCT participations gets a 'shared_ip:<ip>' flag added to each of
    those participations, for a human to review and decide on."""
    if not db.session.get(GiveawayCampaign, campaign_id):
        return jsonify({'message': 'Campaign not found'}), 404

    participations = GiveawayParticipation.query.filter_by(campaign_id=campaign_id).all()
    pids = [p.id for p in participations]
    if not pids:
        return jsonify({'flagged': 0})

    ip_rows = (db.session.query(GiveawayEntry.participation_id, GiveawayEntry.ip_address)
               .filter(GiveawayEntry.participation_id.in_(pids), GiveawayEntry.ip_address.isnot(None)).all())
    ip_to_pids = defaultdict(set)
    for pid, ip in ip_rows:
        ip_to_pids[ip].add(pid)

    by_id = {p.id: p for p in participations}
    flagged = 0
    for ip, pid_set in ip_to_pids.items():
        if len(pid_set) < IP_CLUSTER_THRESHOLD:
            continue
        flag = f'shared_ip:{ip}'
        for pid in pid_set:
            p = by_id[pid]
            flags = p.fraud_flags or []
            if flag not in flags:
                p.fraud_flags = flags + [flag]
                flagged += 1
    log_admin_action(current_user, 'giveaway_fraud_scan', 'giveaway_campaign', campaign_id,
                      f'Flagged {flagged} participation(s) across {len([s for s in ip_to_pids.values() if len(s) >= IP_CLUSTER_THRESHOLD])} shared IP(s)')
    db.session.commit()
    return jsonify({'flagged': flagged})


@giveaway_api.route('/<int:campaign_id>/fraud-flags', methods=['GET'])
@super_admin_required
def fraud_flags_list(_current_user, campaign_id):
    rows = GiveawayParticipation.query.filter_by(campaign_id=campaign_id).all()
    flagged = [p for p in rows if p.fraud_flags or p.status == 'disqualified']
    totals = _entry_totals([p.id for p in flagged])
    return jsonify({'items': [_participation_dict(p, totals.get(p.id, 0)) for p in flagged]})


@giveaway_api.route('/participations/<int:participation_id>/clear-flags', methods=['POST'])
@super_admin_required
def clear_flags(current_user, participation_id):
    p = db.session.get(GiveawayParticipation, participation_id)
    if not p:
        return jsonify({'message': 'Participation not found'}), 404
    p.fraud_flags = []
    if p.status == 'disqualified':
        p.status = 'active' if p.verified_at else 'pending_verification'
    log_admin_action(current_user, 'giveaway_participation_clear_flags', 'giveaway_participation', p.id, None)
    db.session.commit()
    return jsonify(_participation_dict(p))


# ── admin: participants ──────────────────────────────────────────────────

@giveaway_api.route('/<int:campaign_id>/participants', methods=['GET'])
@super_admin_required
def list_participants(_current_user, campaign_id):
    if not db.session.get(GiveawayCampaign, campaign_id):
        return jsonify({'message': 'Campaign not found'}), 404

    query = GiveawayParticipation.query.filter_by(campaign_id=campaign_id)
    status_filter = request.args.get('status')
    if status_filter:
        query = query.filter(GiveawayParticipation.status == status_filter)
    verified_filter = request.args.get('verified')
    if verified_filter == 'true':
        query = query.filter(GiveawayParticipation.verified_at.isnot(None))
    elif verified_filter == 'false':
        query = query.filter(GiveawayParticipation.verified_at.is_(None))
    q = (request.args.get('q') or '').strip()
    if q:
        query = query.join(GiveawayParticipant).filter(
            db.or_(GiveawayParticipant.email.ilike(f'%{q}%'), GiveawayParticipant.name.ilike(f'%{q}%'))
        )

    # Small-dataset-sized query pattern (fetch then enrich/sort in Python),
    # same reasoning backend/analytics/routes/visitor.py's list_sessions()
    # already uses -- entry_total is computed, not a column, so it can't be
    # ORDER BY'd at the DB layer without a subquery this doesn't need yet.
    rows = query.all()
    totals = _entry_totals([p.id for p in rows])
    items = [_participation_dict(p, totals.get(p.id, 0)) for p in rows]

    sort = request.args.get('sort', 'created_at:desc')
    field, _, direction = sort.partition(':')
    if field not in ('created_at', 'entry_total', 'email', 'status'):
        field = 'created_at'
    items.sort(key=lambda r: (r.get(field) or 0) if field == 'entry_total' else (r.get(field) or ''),
               reverse=(direction != 'asc'))

    try:
        page = max(1, int(request.args.get('page', 1)))
    except (TypeError, ValueError):
        page = 1
    total = len(items)
    page_items = items[(page - 1) * PAGE_SIZE: page * PAGE_SIZE]

    return jsonify({'items': page_items, 'total': total, 'page': page, 'per_page': PAGE_SIZE,
                     'has_more': page * PAGE_SIZE < total})


@giveaway_api.route('/participations/<int:participation_id>', methods=['GET'])
@super_admin_required
def get_participation(_current_user, participation_id):
    p = db.session.get(GiveawayParticipation, participation_id)
    if not p:
        return jsonify({'message': 'Participation not found'}), 404

    entries = GiveawayEntry.query.filter_by(participation_id=participation_id).order_by(GiveawayEntry.created_at.desc()).all()
    referred = GiveawayParticipation.query.filter_by(referrer_participation_id=participation_id).all()
    referred_totals = _entry_totals([r.id for r in referred])

    data = _participation_dict(p)
    data['entries'] = [{
        'id': e.id, 'action_key': e.action_key, 'entry_quantity': e.entry_quantity,
        'verification_status': e.verification_status, 'invalidated': e.invalidated,
        'invalidated_reason': e.invalidated_reason,
        'created_at': e.created_at.isoformat() if e.created_at else None,
    } for e in entries]
    data['referred_participants'] = [{
        'id': r.id, 'email': r.participant.email if r.participant else None,
        'status': r.status, 'entry_total': referred_totals.get(r.id, 0),
        'created_at': r.created_at.isoformat() if r.created_at else None,
    } for r in referred]
    data['referral_clicks_count'] = GiveawayReferralClick.query.filter_by(participation_id=participation_id).count()
    return jsonify(data)


@giveaway_api.route('/entries/<int:entry_id>/invalidate', methods=['POST'])
@super_admin_required
def invalidate_entry(current_user, entry_id):
    entry = db.session.get(GiveawayEntry, entry_id)
    if not entry:
        return jsonify({'message': 'Entry not found'}), 404
    body = request.get_json(silent=True) or {}
    reason = (body.get('reason') or '').strip()
    if not reason:
        return jsonify({'message': 'A reason is required'}), 400
    entry.invalidated = True
    entry.invalidated_reason = reason
    entry.invalidated_by = current_user.public_id
    log_admin_action(current_user, 'giveaway_entry_invalidate', 'giveaway_entry', entry.id, reason)
    db.session.commit()
    return jsonify({'id': entry.id, 'invalidated': True})


@giveaway_api.route('/<int:campaign_id>/pending-review', methods=['GET'])
@super_admin_required
def pending_review_entries(_current_user, campaign_id):
    """Every 'manual'-verification entry awaiting approval -- these are
    excluded from every entry-total sum (see _entry_total) until approved,
    so this is the queue that makes a 'manual' entry action mean anything
    at all, rather than a config option nothing ever acts on."""
    # Explicit join condition -- GiveawayEntry has TWO FKs into
    # GiveawayParticipation (participation_id and related_participation_id),
    # so a bare .join(GiveawayParticipation) would be ambiguous.
    rows = (GiveawayEntry.query.join(GiveawayParticipation, GiveawayEntry.participation_id == GiveawayParticipation.id)
            .filter(GiveawayParticipation.campaign_id == campaign_id,
                    GiveawayEntry.verification_status == 'pending_review',
                    GiveawayEntry.invalidated.is_(False))
            .order_by(GiveawayEntry.created_at.asc()).all())
    return jsonify({'items': [{
        'id': e.id, 'participation_id': e.participation_id,
        'name': e.participation.participant.name if e.participation.participant else None,
        'email': e.participation.participant.email if e.participation.participant else None,
        'action_key': e.action_key, 'entry_quantity': e.entry_quantity, 'evidence': e.evidence,
        'created_at': e.created_at.isoformat() if e.created_at else None,
    } for e in rows]})


@giveaway_api.route('/entries/<int:entry_id>/approve', methods=['POST'])
@super_admin_required
def approve_entry(current_user, entry_id):
    entry = db.session.get(GiveawayEntry, entry_id)
    if not entry:
        return jsonify({'message': 'Entry not found'}), 404
    if entry.verification_status != 'pending_review':
        return jsonify({'message': 'This entry is not awaiting review'}), 409
    entry.verification_status = 'verified'
    log_admin_action(current_user, 'giveaway_entry_approve', 'giveaway_entry', entry.id, None)
    db.session.commit()
    return jsonify({'id': entry.id, 'verification_status': 'verified'})


@giveaway_api.route('/participations/<int:participation_id>/disqualify', methods=['POST'])
@super_admin_required
def disqualify_participation(current_user, participation_id):
    p = db.session.get(GiveawayParticipation, participation_id)
    if not p:
        return jsonify({'message': 'Participation not found'}), 404
    body = request.get_json(silent=True) or {}
    reason = (body.get('reason') or '').strip()
    if not reason:
        return jsonify({'message': 'A reason is required'}), 400
    p.status = 'disqualified'
    p.fraud_flags = (p.fraud_flags or []) + [reason]
    log_admin_action(current_user, 'giveaway_participation_disqualify', 'giveaway_participation', p.id, reason)
    db.session.commit()
    return jsonify(_participation_dict(p))


@giveaway_api.route('/<int:campaign_id>/export/participants', methods=['GET'])
@super_admin_required
def export_participants(_current_user, campaign_id):
    rows = GiveawayParticipation.query.filter_by(campaign_id=campaign_id).all()
    totals = _entry_totals([p.id for p in rows])
    header = ['Name', 'Email', 'Phone', 'Verified', 'Status', 'Entries', 'Referral Code', 'Referred By', 'Entered At']
    data = [[
        (p.participant.name or '') if p.participant else '',
        p.participant.email if p.participant else '',
        (p.participant.phone or '') if p.participant else '',
        'yes' if p.verified_at else 'no', p.status, totals.get(p.id, 0),
        p.referral_code, p.referrer_participation_id or '',
        p.created_at.isoformat() if p.created_at else '',
    ] for p in rows]
    return csv_response(header, data, f'giveaway-{campaign_id}-participants.csv')


@giveaway_api.route('/<int:campaign_id>/export/eligible', methods=['GET'])
@super_admin_required
def export_eligible(_current_user, campaign_id):
    header = ['Name', 'Email', 'Entries']
    data = [[(p.participant.name or '') if p.participant else '',
              p.participant.email if p.participant else '', entries]
             for p, entries in _eligible_participations(campaign_id)]
    return csv_response(header, data, f'giveaway-{campaign_id}-eligible.csv')


# ── admin: leaderboard, acquisition, comparison ─────────────────────────

@giveaway_api.route('/<int:campaign_id>/leaderboard', methods=['GET'])
@super_admin_required
def leaderboard(_current_user, campaign_id):
    participations = GiveawayParticipation.query.filter_by(campaign_id=campaign_id).all()
    pids = [p.id for p in participations]

    click_counts, referred_counts, qualified_counts, referral_entries = {}, {}, {}, {}
    if pids:
        click_counts = dict(
            db.session.query(GiveawayReferralClick.participation_id, func.count(GiveawayReferralClick.id))
            .filter(GiveawayReferralClick.participation_id.in_(pids))
            .group_by(GiveawayReferralClick.participation_id).all()
        )
        referred_counts = dict(
            db.session.query(GiveawayParticipation.referrer_participation_id, func.count(GiveawayParticipation.id))
            .filter(GiveawayParticipation.referrer_participation_id.in_(pids))
            .group_by(GiveawayParticipation.referrer_participation_id).all()
        )
        qualified_counts = dict(
            db.session.query(GiveawayEntry.participation_id, func.count(GiveawayEntry.id))
            .filter(GiveawayEntry.participation_id.in_(pids), GiveawayEntry.action_key == 'referral_qualified',
                    GiveawayEntry.invalidated.is_(False))
            .group_by(GiveawayEntry.participation_id).all()
        )
        referral_entries = dict(
            db.session.query(GiveawayEntry.participation_id, func.sum(GiveawayEntry.entry_quantity))
            .filter(GiveawayEntry.participation_id.in_(pids), GiveawayEntry.action_key == 'referral_qualified',
                    GiveawayEntry.invalidated.is_(False))
            .group_by(GiveawayEntry.participation_id).all()
        )

    board = []
    for p in participations:
        clicks = click_counts.get(p.id, 0)
        registrations = referred_counts.get(p.id, 0)
        if clicks == 0 and registrations == 0:
            continue
        board.append({
            'participation_id': p.id,
            'name': p.participant.name if p.participant else None,
            'email': p.participant.email if p.participant else None,
            'referral_clicks': clicks,
            'registrations': registrations,
            'qualified_referrals': qualified_counts.get(p.id, 0),
            'entries_from_referrals': int(referral_entries.get(p.id, 0) or 0),
        })
    board.sort(key=lambda r: r['entries_from_referrals'], reverse=True)
    return jsonify({'leaderboard': board[:200]})


@giveaway_api.route('/<int:campaign_id>/acquisition', methods=['GET'])
@super_admin_required
def acquisition(_current_user, campaign_id):
    participations = GiveawayParticipation.query.filter_by(campaign_id=campaign_id).all()
    by_source, by_medium, by_day = defaultdict(lambda: [0, 0]), defaultdict(lambda: [0, 0]), defaultdict(lambda: [0, 0])
    for p in participations:
        touch = p.first_touch or {}
        source = touch.get('source') or 'direct'
        medium = touch.get('medium') or 'none'
        day = p.created_at.date().isoformat() if p.created_at else 'unknown'
        for bucket, key in ((by_source, source), (by_medium, medium), (by_day, day)):
            bucket[key][0] += 1
            if p.verified_at:
                bucket[key][1] += 1

    def _rows(bucket):
        return sorted(
            [{'key': k, 'participants': v[0], 'verified': v[1],
              'conversion_rate': round(v[1] / v[0] * 100, 1) if v[0] else 0} for k, v in bucket.items()],
            key=lambda r: r['participants'], reverse=True,
        )

    return jsonify({'by_source': _rows(by_source), 'by_medium': _rows(by_medium), 'by_day': _rows(by_day)})


@giveaway_api.route('/compare', methods=['GET'])
@super_admin_required
def compare_campaigns(_current_user):
    try:
        ids = [int(x) for x in (request.args.get('ids') or '').split(',') if x.strip()]
    except ValueError:
        return jsonify({'message': 'ids must be a comma-separated list of campaign ids'}), 400
    campaigns = GiveawayCampaign.query.filter(GiveawayCampaign.id.in_(ids)).all()
    stats = _stats_for_campaigns(ids)
    return jsonify({'campaigns': [
        {'id': c.id, 'name': c.name, 'status': c.status, **stats.get(c.id, {})} for c in campaigns
    ]})


# ── admin: winner draw ───────────────────────────────────────────────────

@giveaway_api.route('/<int:campaign_id>/draw/freeze', methods=['POST'])
@super_admin_required
def freeze_draw(current_user, campaign_id):
    campaign = db.session.get(GiveawayCampaign, campaign_id)
    if not campaign:
        return jsonify({'message': 'Campaign not found'}), 404

    pool = [{'participation_id': p.id, 'entries': entries} for p, entries in _eligible_participations(campaign_id)]
    snapshot = GiveawayDrawSnapshot(
        campaign_id=campaign_id, eligible_count=len(pool), pool_json=pool,
        rules_applied=campaign.entry_rules, created_by=current_user.public_id,
    )
    db.session.add(snapshot)
    campaign.status = 'closed'
    log_admin_action(current_user, 'giveaway_draw_freeze', 'giveaway_campaign', campaign.id,
                      f'Froze {len(pool)} eligible participations')
    db.session.commit()
    return jsonify({'snapshot_id': snapshot.id, 'eligible_count': snapshot.eligible_count, 'pool': pool}), 201


@giveaway_api.route('/<int:campaign_id>/draw', methods=['POST'])
@super_admin_required
def run_draw(current_user, campaign_id):
    """Weighted-random draw over a frozen snapshot: cumulative-sum each
    participation's entries, pick a point uniformly in [0, total) with
    secrets.SystemRandom (cryptographic, not reproducible/predictable), and
    walk the cumulative sums to find the winner -- standard weighted-choice,
    no need to materialize one "ticket" row per entry. Calling this again
    against the same snapshot adds backup winners rather than re-picking
    the original winner (excluded via already_drawn)."""
    campaign = db.session.get(GiveawayCampaign, campaign_id)
    if not campaign:
        return jsonify({'message': 'Campaign not found'}), 404

    body = request.get_json(silent=True) or {}
    snapshot_id = body.get('snapshot_id')
    snapshot = (db.session.get(GiveawayDrawSnapshot, snapshot_id) if snapshot_id else
                GiveawayDrawSnapshot.query.filter_by(campaign_id=campaign_id)
                .order_by(GiveawayDrawSnapshot.created_at.desc()).first())
    if not snapshot:
        return jsonify({'message': 'No frozen pool yet -- call draw/freeze first'}), 400
    if not snapshot.pool_json:
        return jsonify({'message': 'The frozen pool is empty -- no eligible entries to draw from'}), 400

    prior_draws = GiveawayDraw.query.filter_by(snapshot_id=snapshot.id).all()
    already_drawn = {d.winner_participation_id for d in prior_draws}
    is_first_draw_ever = not prior_draws
    backup_rank_counter = max([d.backup_rank for d in prior_draws if d.backup_rank] or [0])

    pool = [row for row in snapshot.pool_json if row['participation_id'] not in already_drawn]
    if not pool:
        return jsonify({'message': 'Every eligible participation has already been drawn from this pool'}), 400

    backup_count = max(0, int(body.get('backup_count', 0) or 0))
    rng = secrets.SystemRandom()
    results = []

    for i in range(1 + backup_count):
        if not pool:
            break
        total = sum(row['entries'] for row in pool)
        pick = rng.uniform(0, total)
        running, chosen = 0, pool[-1]
        for row in pool:
            running += row['entries']
            if pick <= running:
                chosen = row
                break
        pool = [row for row in pool if row['participation_id'] != chosen['participation_id']]

        is_backup = not (is_first_draw_ever and i == 0)
        if is_backup:
            backup_rank_counter += 1

        draw = GiveawayDraw(
            campaign_id=campaign_id, snapshot_id=snapshot.id,
            winner_participation_id=chosen['participation_id'],
            is_backup=is_backup, backup_rank=(backup_rank_counter if is_backup else None),
            drawn_by=current_user.public_id,
        )
        db.session.add(draw)
        db.session.flush()
        results.append(draw)

        winner_participation = db.session.get(GiveawayParticipation, chosen['participation_id'])
        if winner_participation:
            winner_participation.status = 'backup_winner' if is_backup else 'winner'

    campaign.status = 'winner_selected'
    log_admin_action(current_user, 'giveaway_draw', 'giveaway_campaign', campaign.id,
                      f'Drew {len(results)} winner(s) from snapshot {snapshot.id}')
    db.session.commit()

    for draw in results:
        winner_p = draw.winner_participation
        if winner_p and winner_p.participant and not draw.is_backup:
            try:
                send_giveaway_winner_email(winner_p.participant.email, campaign.name, campaign.prize_details)
            except Exception:
                pass  # the draw is already recorded either way

    return jsonify({'drawn': [{
        'draw_id': d.id, 'participation_id': d.winner_participation_id, 'is_backup': d.is_backup,
        'backup_rank': d.backup_rank,
        'name': d.winner_participation.participant.name if d.winner_participation and d.winner_participation.participant else None,
        'email': d.winner_participation.participant.email if d.winner_participation and d.winner_participation.participant else None,
    } for d in results]}), 201


@giveaway_api.route('/<int:campaign_id>/draw/report', methods=['GET'])
@super_admin_required
def draw_report(_current_user, campaign_id):
    draws = (GiveawayDraw.query.filter_by(campaign_id=campaign_id)
             .order_by(GiveawayDraw.is_backup, GiveawayDraw.backup_rank, GiveawayDraw.drawn_at).all())
    header = ['Draw ID', 'Role', 'Backup Rank', 'Name', 'Email', 'Snapshot ID', 'Algorithm', 'Drawn At']
    data = []
    for d in draws:
        p = d.winner_participation
        data.append([
            d.id, 'Backup' if d.is_backup else 'Winner', d.backup_rank or '',
            (p.participant.name or '') if p and p.participant else '',
            p.participant.email if p and p.participant else '',
            d.snapshot_id, d.algorithm, d.drawn_at.isoformat() if d.drawn_at else '',
        ])
    return csv_response(header, data, f'giveaway-{campaign_id}-draw-report.csv')


# ── public: landing page + entry flow ───────────────────────────────────

@giveaway_api.route('/public/<slug>', methods=['GET'])
def public_campaign(slug):
    campaign = GiveawayCampaign.query.filter_by(slug=slug).first()
    if not campaign or campaign.status == 'draft':
        return jsonify({'message': 'This giveaway could not be found'}), 404
    actions = [a for a in campaign.entry_actions if a.is_enabled]
    return jsonify({
        'name': campaign.name, 'slug': campaign.slug, 'description': campaign.description,
        'status': campaign.status,
        'starts_at': campaign.starts_at.isoformat() if campaign.starts_at else None,
        'ends_at': campaign.ends_at.isoformat() if campaign.ends_at else None,
        'prize_details': campaign.prize_details, 'terms_text': campaign.terms_text,
        'privacy_note': campaign.privacy_note, 'image_url': campaign.image_url,
        'participants_count': GiveawayParticipation.query.filter_by(campaign_id=campaign.id).count(),
        'entry_actions': make_entry_action_schema(many=True).dump(actions),
    })


@giveaway_api.route('/public/<slug>/referral-click', methods=['POST'])
def referral_click(slug):
    """Logged as soon as someone lands on /campaign/<slug>?ref=<code>,
    before they necessarily enter -- parallel to CampaignLinkClick's role
    for channel links, but keyed by a participant's own referral_code.
    Always 200s, even on an unknown code/campaign, since this is a passive
    logging call the landing page fires on mount and a bad code here isn't
    something the visitor did wrong."""
    body = request.get_json(silent=True) or {}
    ref_code = (body.get('ref') or '').strip().upper()
    campaign = GiveawayCampaign.query.filter_by(slug=slug).first() if ref_code else None
    participation = (GiveawayParticipation.query.filter_by(campaign_id=campaign.id, referral_code=ref_code).first()
                      if campaign else None)
    if participation:
        db.session.add(GiveawayReferralClick(
            participation_id=participation.id, referrer=request.headers.get('Referer'),
            user_agent=request.headers.get('User-Agent'), country=request.headers.get('x-vercel-ip-country'),
            ip_address=real_client_ip(),
        ))
        db.session.commit()
    return jsonify({'ok': True})


@giveaway_api.route('/public/<slug>/enter', methods=['POST'])
@token_optional
def enter_giveaway(current_user, slug):
    campaign = GiveawayCampaign.query.filter_by(slug=slug).first()
    if not campaign:
        return jsonify({'message': 'This giveaway could not be found'}), 404
    if campaign.status != 'active':
        return jsonify({'message': 'This giveaway is not currently open for entries'}), 409
    if _looks_like_bot_ua():
        return jsonify({'message': 'Could not submit your entry -- please try again from a web browser.'}), 400

    body = request.get_json(silent=True) or {}
    name = (body.get('name') or '').strip()
    email = GiveawayParticipant.normalize_email(body.get('email'))
    if not name or not email or '@' not in email:
        return jsonify({'message': 'Name and a valid email are required'}), 400

    if not check_and_record_giveaway_entry(request):
        db.session.commit()
        return jsonify({'message': 'Too many entries from this connection today -- please try again tomorrow'}), 429

    participant = GiveawayParticipant.query.filter_by(email=email).first()
    if participant is None:
        participant = GiveawayParticipant(name=name, email=email, phone=(body.get('phone') or '').strip() or None)
        db.session.add(participant)
        db.session.flush()
    else:
        if not participant.name:
            participant.name = name
        if body.get('phone') and not participant.phone:
            participant.phone = body['phone'].strip()
    if current_user and not participant.user_id:
        participant.user_id = current_user.public_id

    existing = GiveawayParticipation.query.filter_by(campaign_id=campaign.id, participant_id=participant.id).first()
    if existing:
        db.session.commit()
        return jsonify({
            'message': 'You already entered this giveaway.',
            'participation_token': existing.verify_token,
            'referral_code': existing.referral_code,
            'status': existing.status,
            'entry_total': _entry_total(existing.id),
        }), 200

    referrer = None
    ref_code = (body.get('ref') or '').strip().upper()
    if ref_code:
        candidate = GiveawayParticipation.query.filter_by(campaign_id=campaign.id, referral_code=ref_code).first()
        # A self-referral (candidate belongs to the SAME participant) or an
        # unknown code is silently dropped rather than surfaced as an error
        # -- the entry still goes through, just without a referral credit.
        if candidate and candidate.participant_id != participant.id:
            referrer = candidate

    touch = {
        'source': body.get('source'), 'medium': body.get('medium'), 'channel': body.get('channel'),
        'promotion': body.get('promotion'), 'creative': body.get('creative'), 'partner': body.get('partner'),
        'landing_page': body.get('landing_page'), 'referral_code': ref_code or None,
    }

    referral_code = GiveawayParticipation.generate_referral_code()
    while GiveawayParticipation.query.filter_by(referral_code=referral_code).first():
        referral_code = GiveawayParticipation.generate_referral_code()

    participation = GiveawayParticipation(
        campaign_id=campaign.id, participant_id=participant.id,
        referral_code=referral_code, referrer_participation_id=referrer.id if referrer else None,
        first_touch=touch, last_touch=touch,
        consent_marketing=bool(body.get('consent_marketing', False)),
        consent_at=datetime.utcnow() if body.get('consent_marketing') else None,
        consent_source='giveaway_entry_form' if body.get('consent_marketing') else None,
        verify_token=secrets.token_urlsafe(32),
    )
    db.session.add(participation)
    db.session.flush()

    entry_action = GiveawayEntryAction.query.filter_by(
        campaign_id=campaign.id, action_key='email_signup', is_enabled=True).first()
    if entry_action:
        db.session.add(GiveawayEntry(
            participation_id=participation.id, action_key='email_signup',
            related_participation_id=participation.id, entry_quantity=entry_action.entry_quantity,
            verification_status='verified', verification_method='auto',
            ip_address=real_client_ip(), user_agent=request.headers.get('User-Agent'),
        ))
    db.session.commit()

    verify_url = f"{request.host_url.rstrip('/')}/giveaways/public/verify/{participation.verify_token}"
    try:
        send_giveaway_verify_email(participant.email, campaign.name, verify_url)
    except Exception:
        pass  # the participation is still created either way

    return jsonify({
        'message': 'Check your email to confirm your entry.',
        'participation_token': participation.verify_token,
        'referral_code': participation.referral_code,
        'status': participation.status,
    }), 201


@giveaway_api.route('/public/<slug>/resend-verify', methods=['POST'])
def resend_verify(slug):
    campaign = GiveawayCampaign.query.filter_by(slug=slug).first()
    if not campaign:
        return jsonify({'message': 'This giveaway could not be found'}), 404
    email = GiveawayParticipant.normalize_email((request.get_json(silent=True) or {}).get('email'))
    if not email:
        return jsonify({'message': 'Email is required'}), 400

    if not check_and_record_giveaway_entry(request):
        db.session.commit()
        return jsonify({'message': 'Too many requests from this connection today -- please try again tomorrow'}), 429

    # Same response either way, whether or not that email/participation
    # actually exists -- don't let this endpoint be used to probe which
    # emails have entered (same shape as a password-reset flow).
    participant = GiveawayParticipant.query.filter_by(email=email).first()
    participation = (GiveawayParticipation.query.filter_by(campaign_id=campaign.id, participant_id=participant.id).first()
                      if participant else None)
    if participation and participation.verified_at is None:
        verify_url = f"{request.host_url.rstrip('/')}/giveaways/public/verify/{participation.verify_token}"
        try:
            send_giveaway_verify_email(participant.email, campaign.name, verify_url)
        except Exception:
            pass
    db.session.commit()
    return jsonify({'message': 'If that email has a pending entry, we just sent a new confirmation link.'})


@giveaway_api.route('/public/verify/<token>', methods=['GET'])
def verify_participation(token):
    participation = GiveawayParticipation.query.filter_by(verify_token=token).first()
    if not participation:
        return jsonify({'message': 'This confirmation link is invalid or has expired.'}), 404
    campaign = db.session.get(GiveawayCampaign, participation.campaign_id)

    if participation.verified_at is None:
        participation.verified_at = datetime.utcnow()
        if participation.status == 'pending_verification':
            participation.status = 'active'
        if participation.participant and not participation.participant.email_verified:
            participation.participant.email_verified = True

        verify_action = GiveawayEntryAction.query.filter_by(
            campaign_id=participation.campaign_id, action_key='email_verify', is_enabled=True).first()
        if verify_action:
            db.session.add(GiveawayEntry(
                participation_id=participation.id, action_key='email_verify',
                related_participation_id=participation.id, entry_quantity=verify_action.entry_quantity,
                verification_status='verified', verification_method='auto',
            ))

        if participation.referrer_participation_id:
            referral_action = GiveawayEntryAction.query.filter_by(
                campaign_id=participation.campaign_id, action_key='referral_qualified', is_enabled=True).first()
            if referral_action:
                db.session.add(GiveawayEntry(
                    participation_id=participation.referrer_participation_id, action_key='referral_qualified',
                    related_participation_id=participation.id, entry_quantity=referral_action.entry_quantity,
                    verification_status='verified', verification_method='auto',
                ))
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()  # a concurrent duplicate call -- already handled, not an error

        if campaign and participation.participant:
            referral_url = f'{MAIN_SITE_URL}/campaign/{campaign.slug}?ref={participation.referral_code}'
            unsubscribe_url = f"{request.host_url.rstrip('/')}/giveaways/public/unsubscribe/{participation.verify_token}"
            try:
                send_giveaway_confirmed_email(
                    participation.participant.email, campaign.name, _entry_total(participation.id),
                    referral_url, unsubscribe_url)
            except Exception:
                pass

    slug = campaign.slug if campaign else ''
    return redirect(f'{MAIN_SITE_URL}/campaign/{slug}?verified=1&participation_token={token}', code=302)


@giveaway_api.route('/public/<slug>/me', methods=['GET'])
def my_participation(slug):
    token = request.args.get('token') or request.args.get('participation_token')
    if not token:
        return jsonify({'message': 'Missing participation token'}), 400
    campaign = GiveawayCampaign.query.filter_by(slug=slug).first()
    if not campaign:
        return jsonify({'message': 'This giveaway could not be found'}), 404
    participation = GiveawayParticipation.query.filter_by(verify_token=token, campaign_id=campaign.id).first()
    if not participation:
        return jsonify({'message': 'Invalid participation token'}), 404

    own_entries = GiveawayEntry.query.filter_by(participation_id=participation.id, invalidated=False).all()
    completed_keys = {e.action_key for e in own_entries if e.verification_status != 'pending_review'}
    pending_keys = {e.action_key for e in own_entries if e.verification_status == 'pending_review'}
    actions = [a for a in campaign.entry_actions if a.is_enabled]
    return jsonify({
        'referral_code': participation.referral_code,
        'referral_url': f'{MAIN_SITE_URL}/campaign/{campaign.slug}?ref={participation.referral_code}',
        'status': participation.status,
        'verified': participation.verified_at is not None,
        'entry_total': _entry_total(participation.id),
        'actions': [{**make_entry_action_schema().dump(a), 'completed': a.action_key in completed_keys,
                     'pending_review': a.action_key in pending_keys}
                    for a in actions],
    })


@giveaway_api.route('/public/<slug>/action', methods=['POST'])
def complete_action(slug):
    body = request.get_json(silent=True) or {}
    token = body.get('token') or body.get('participation_token')
    action_key = (body.get('action_key') or '').strip()
    if not token or not action_key:
        return jsonify({'message': 'token and action_key are required'}), 400

    campaign = GiveawayCampaign.query.filter_by(slug=slug).first()
    if not campaign:
        return jsonify({'message': 'This giveaway could not be found'}), 404
    participation = GiveawayParticipation.query.filter_by(verify_token=token, campaign_id=campaign.id).first()
    if not participation:
        return jsonify({'message': 'Invalid participation token'}), 404
    if participation.verified_at is None:
        return jsonify({'message': 'Confirm your email before completing other actions'}), 409

    action = GiveawayEntryAction.query.filter_by(campaign_id=campaign.id, action_key=action_key, is_enabled=True).first()
    if not action:
        return jsonify({'message': 'This action is not available on this campaign'}), 404

    # auto/self_certify count their entry immediately (trusted now, reviewed
    # after the fact via an admin invalidate -- see GiveawayEntry's own
    # docstring); 'manual' instead goes in as pending_review, excluded from
    # every entry-total sum until an admin explicitly approves it.
    verification_status = 'pending_review' if action.verification_method == 'manual' else 'verified'

    db.session.add(GiveawayEntry(
        participation_id=participation.id, action_key=action_key,
        related_participation_id=participation.id, entry_quantity=action.entry_quantity,
        verification_status=verification_status,
        verification_method=action.verification_method, evidence=body.get('evidence') or None,
        ip_address=real_client_ip(), user_agent=request.headers.get('User-Agent'),
    ))
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()  # already submitted -- idempotent, not an error

    return jsonify({
        'entry_total': _entry_total(participation.id),
        'pending_review': verification_status == 'pending_review',
    })


@giveaway_api.route('/public/unsubscribe/<token>', methods=['GET'])
def unsubscribe(token):
    participation = GiveawayParticipation.query.filter_by(verify_token=token).first()
    if not participation:
        return jsonify({'message': 'Invalid link'}), 404
    participation.consent_marketing = False
    db.session.commit()
    return jsonify({'message': 'You have been unsubscribed from marketing emails for this giveaway.'})
