from collections import defaultdict

from flask import Blueprint, jsonify, request, redirect
from sqlalchemy import func

from config import db
from security import super_admin_required
from backend.campaigns.modals.campaign import MarketingCampaign, CampaignLink, CampaignLinkClick, CAMPAIGN_STATUSES
from backend.campaigns.schemas.campaign import make_campaign_schema, make_link_schema
from backend.analytics.modals.visitor import VisitorSession, VisitorEvent
from backend.user.modals.user import User

campaign_api = Blueprint('campaign_api', __name__, url_prefix='/campaigns')

PAGE_SIZE = 50


def _stats_for_links(link_ids):
    """clicks/visitors/signups/contributions per link_id. 'visitors' is a
    distinct count of VisitorSession.anonymous_id rows whose first-touch
    landed on that link (see VisitorSession.campaign_link_id, set sticky in
    beacon()). 'signups' and 'contributions' each intersect those same
    anonymous_ids against anyone who has a matching VisitorEvent --
    event_type='signup' is written in add_user() (backend/user/routes/
    user.py); event_type='contribution' is written by each of the guest
    create-listing/post/business routes (backend/estates/routes/estates.py,
    backend/tachlis/routes/tachlis_post.py, backend/business/routes/
    business.py) -- "did this link actually bring in a guest submission",
    the conversion a /contribute-style link cares about, same shape as a
    signup-driving link's conversion."""
    if not link_ids:
        return {}

    clicks_by_link = dict(
        db.session.query(CampaignLinkClick.link_id, func.count(CampaignLinkClick.id))
        .filter(CampaignLinkClick.link_id.in_(link_ids))
        .group_by(CampaignLinkClick.link_id).all()
    )

    sessions = VisitorSession.query.filter(VisitorSession.campaign_link_id.in_(link_ids)).all()
    anon_by_link = defaultdict(set)
    all_anon_ids = set()
    for s in sessions:
        anon_by_link[s.campaign_link_id].add(s.anonymous_id)
        all_anon_ids.add(s.anonymous_id)

    signup_anon_ids = set()
    contribution_anon_ids = set()
    if all_anon_ids:
        rows = (db.session.query(VisitorEvent.anonymous_id, VisitorEvent.event_type)
                .filter(VisitorEvent.event_type.in_(('signup', 'contribution')), VisitorEvent.anonymous_id.in_(all_anon_ids))
                .distinct().all())
        for anon_id, event_type in rows:
            (signup_anon_ids if event_type == 'signup' else contribution_anon_ids).add(anon_id)

    return {
        link_id: {
            'clicks': clicks_by_link.get(link_id, 0),
            'visitors': len(anon_by_link.get(link_id, set())),
            'signups': len(anon_by_link.get(link_id, set()) & signup_anon_ids),
            'contributions': len(anon_by_link.get(link_id, set()) & contribution_anon_ids),
        }
        for link_id in link_ids
    }


def _api_base():
    return request.host_url.rstrip('/')


@campaign_api.route('', methods=['GET'])
@super_admin_required
def list_campaigns(_current_user):
    campaigns = MarketingCampaign.query.order_by(MarketingCampaign.created_at.desc()).all()
    link_ids = [l.id for c in campaigns for l in c.links]
    stats = _stats_for_links(link_ids)
    schema = make_campaign_schema(_api_base(), stats, many=True)
    return jsonify(schema.dump(campaigns))


@campaign_api.route('', methods=['POST'])
@super_admin_required
def create_campaign(current_user):
    body = request.get_json(silent=True) or {}
    name = (body.get('name') or '').strip()
    if not name:
        return jsonify({'message': 'Campaign name is required'}), 400
    campaign = MarketingCampaign(
        name=name,
        description=(body.get('description') or '').strip() or None,
        created_by=current_user.public_id,
    )
    db.session.add(campaign)
    db.session.commit()
    schema = make_campaign_schema(_api_base(), {})
    return jsonify(schema.dump(campaign)), 201


@campaign_api.route('/<int:campaign_id>', methods=['GET'])
@super_admin_required
def get_campaign(_current_user, campaign_id):
    campaign = db.session.get(MarketingCampaign, campaign_id)
    if not campaign:
        return jsonify({'message': 'Campaign not found'}), 404
    link_ids = [l.id for l in campaign.links]
    stats = _stats_for_links(link_ids)
    schema = make_campaign_schema(_api_base(), stats)
    return jsonify(schema.dump(campaign))


@campaign_api.route('/<int:campaign_id>', methods=['PATCH'])
@super_admin_required
def update_campaign(_current_user, campaign_id):
    campaign = db.session.get(MarketingCampaign, campaign_id)
    if not campaign:
        return jsonify({'message': 'Campaign not found'}), 404
    body = request.get_json(silent=True) or {}
    if 'name' in body:
        name = (body.get('name') or '').strip()
        if not name:
            return jsonify({'message': 'Campaign name cannot be blank'}), 400
        campaign.name = name
    if 'description' in body:
        campaign.description = (body.get('description') or '').strip() or None
    if 'status' in body:
        if body['status'] not in CAMPAIGN_STATUSES:
            return jsonify({'message': f'status must be one of {CAMPAIGN_STATUSES}'}), 400
        campaign.status = body['status']
    db.session.commit()
    schema = make_campaign_schema(_api_base(), _stats_for_links([l.id for l in campaign.links]))
    return jsonify(schema.dump(campaign))


@campaign_api.route('/<int:campaign_id>/links', methods=['POST'])
@super_admin_required
def create_link(_current_user, campaign_id):
    campaign = db.session.get(MarketingCampaign, campaign_id)
    if not campaign:
        return jsonify({'message': 'Campaign not found'}), 404
    body = request.get_json(silent=True) or {}
    destination_url = (body.get('destination_url') or '').strip()
    label = (body.get('label') or '').strip()
    if not destination_url or not destination_url.startswith(('http://', 'https://')):
        return jsonify({'message': 'destination_url must be a full http(s) URL'}), 400
    if not label:
        return jsonify({'message': 'label is required'}), 400
    link = CampaignLink(campaign_id=campaign_id, label=label, destination_url=destination_url)
    db.session.add(link)
    db.session.commit()
    schema = make_link_schema(_api_base(), {})
    return jsonify(schema.dump(link)), 201


@campaign_api.route('/links/<int:link_id>', methods=['PATCH'])
@super_admin_required
def update_link(_current_user, link_id):
    link = db.session.get(CampaignLink, link_id)
    if not link:
        return jsonify({'message': 'Link not found'}), 404
    body = request.get_json(silent=True) or {}
    if 'label' in body:
        label = (body.get('label') or '').strip()
        if not label:
            return jsonify({'message': 'label cannot be blank'}), 400
        link.label = label
    if 'destination_url' in body:
        destination_url = (body.get('destination_url') or '').strip()
        if not destination_url.startswith(('http://', 'https://')):
            return jsonify({'message': 'destination_url must be a full http(s) URL'}), 400
        link.destination_url = destination_url
    if 'is_active' in body:
        link.is_active = bool(body['is_active'])
    db.session.commit()
    schema = make_link_schema(_api_base(), _stats_for_links([link.id]))
    return jsonify(schema.dump(link))


@campaign_api.route('/links/<int:link_id>/activity', methods=['GET'])
@super_admin_required
def link_activity(_current_user, link_id):
    """Drill-down behind one link's stats tile -- raw clicks (paginated,
    newest first) plus every visitor session attributed to this link, each
    flagged with whether/when they signed up. Small-dataset-sized query
    pattern (fetch then enrich in Python), same reasoning list_sessions()
    in backend/analytics/routes/visitor.py already uses."""
    link = db.session.get(CampaignLink, link_id)
    if not link:
        return jsonify({'message': 'Link not found'}), 404

    try:
        page = max(1, int(request.args.get('page', 1)))
    except (TypeError, ValueError):
        page = 1

    clicks_query = CampaignLinkClick.query.filter_by(link_id=link_id).order_by(CampaignLinkClick.created_at.desc())
    total_clicks = clicks_query.count()
    click_rows = clicks_query.offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE).all()

    sessions = (VisitorSession.query.filter_by(campaign_link_id=link_id)
                .order_by(VisitorSession.first_seen.desc()).all())
    anon_ids = [s.anonymous_id for s in sessions]
    signup_events = {}
    if anon_ids:
        rows = (VisitorEvent.query
                .filter(VisitorEvent.event_type == 'signup', VisitorEvent.anonymous_id.in_(anon_ids))
                .all())
        for ev in rows:
            signup_events[ev.anonymous_id] = ev.created_at

    user_ids = {s.user_id for s in sessions if s.user_id}
    users_by_id = {u.public_id: u for u in User.query.filter(User.public_id.in_(user_ids)).all()} if user_ids else {}

    visitors = [{
        'anonymous_id': s.anonymous_id[:12],
        'user_name': users_by_id[s.user_id].profile_name if s.user_id in users_by_id else None,
        'country': s.country or 'Unknown',
        'first_seen': s.first_seen.isoformat() if s.first_seen else None,
        'last_seen': s.last_seen.isoformat() if s.last_seen else None,
        'page_view_count': s.page_view_count or 0,
        'signed_up_at': signup_events[s.anonymous_id].isoformat() if s.anonymous_id in signup_events else None,
    } for s in sessions]

    return jsonify({
        'link': make_link_schema(_api_base(), _stats_for_links([link_id])).dump(link),
        'clicks': {
            'items': [{
                'id': c.id,
                'created_at': c.created_at.isoformat() if c.created_at else None,
                'referrer': c.referrer,
                'user_agent': c.user_agent,
                'country': c.country,
            } for c in click_rows],
            'total': total_clicks,
            'page': page,
            'per_page': PAGE_SIZE,
            'has_more': page * PAGE_SIZE < total_clicks,
        },
        'visitors': visitors,
    })


@campaign_api.route('/r/<code>', methods=['GET'])
def redirect_link(code):
    """Public, no auth -- this is the URL that actually gets pasted into
    Facebook/Instagram/email. Logs the click, then 302s on to the link's
    destination with ?gs_ad=<code> appended, which VisitorTracker.js picks
    up client-side (see its own comment) to attribute the resulting
    session/signup back to this link."""
    link = CampaignLink.query.filter_by(code=code).first()
    if not link or not link.is_active:
        return jsonify({'message': 'This link is no longer active.'}), 404

    db.session.add(CampaignLinkClick(
        link_id=link.id,
        referrer=request.headers.get('Referer'),
        user_agent=request.headers.get('User-Agent'),
        country=request.headers.get('x-vercel-ip-country'),
    ))
    db.session.commit()

    sep = '&' if '?' in link.destination_url else '?'
    return redirect(f'{link.destination_url}{sep}gs_ad={code}', code=302)
