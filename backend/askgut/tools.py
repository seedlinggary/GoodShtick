"""Ask GUT's backend "tools" -- the functions the OpenAI tool-calling loop
in backend/askgut/routes/chat.py can invoke. Each one is a thin wrapper
around an EXISTING query function/model where one already exists as a
plain importable function (backend/search/routes/search.py's `_search_*`
helpers are already pure (q, limit) -> list[dict], written exactly for
this kind of reuse). Where no pure helper exists yet -- the extra filters
unified search doesn't cover (kashrut/open-now, bedrooms/price, remote,
minyan city/tefilah) -- this module adds small, additive direct queries
against the same models the existing routes use, rather than duplicating
anything non-trivial. Every function here returns plain dicts (JSON-ready),
never an ORM object, since these results get handed straight to the OpenAI
API and back out to the frontend.

Registered as OpenAI "tools" in chat.py; TOOL_SPECS there must stay in
sync with each function's signature."""
from datetime import datetime

from config import db
from backend.search.routes.search import (
    _search_shtick, _search_hock, _search_business, _search_estates, _search_tachlis, _search_torah,
)
from backend.business.modals.business import Business, BusinessLocation
from backend.business.routes.business import _location_open_now
from backend.business.modals.minyan import Minyan, TEFILAH_TYPES
from backend.tachlis.modals.tachlis_post import TachlisPost

TOOL_RESULT_LIMIT = 5


def search_shtick_hock(query, limit=TOOL_RESULT_LIMIT):
    """Gut Shtick's humor/pin board + the Hock discussion forum."""
    items = _search_shtick(query, limit) + _search_hock(query, limit)
    return {'type': 'shtick_hock', 'items': items[:limit]}


def search_business(q=None, category=None, city=None, kashrut_only=False, open_now=False, limit=TOOL_RESULT_LIMIT):
    """Business directory (Gut Community). `category` must be one of
    Business.BUSINESS_CATEGORIES if given. Free-text `q` uses the same
    full-text search unified search uses; category/city/kashrut/open_now
    are plain filters applied on top (open_now is computed in Python from
    each location's stored hours, same as list_businesses does)."""
    if q:
        items = _search_business(q, limit * 4)  # overfetch so category/city filters below still leave `limit`
        ids = [i['id'] for i in items]
        if not ids:
            return {'type': 'business', 'items': []}
        rows = Business.query.filter(Business.id.in_(ids)).all()
        by_id = {b.id: b for b in rows}
        ordered = [by_id[i['id']] for i in items if i['id'] in by_id]
    else:
        query = Business.query
        if category:
            query = query.filter(Business.category == category)
        ordered = query.order_by(Business.rating_avg.desc().nullslast()).limit(limit * 4).all()

    results = []
    for b in ordered:
        locs = b.locations or []
        if city and not any((l.city or '').lower().find(city.lower()) != -1 for l in locs):
            continue
        if kashrut_only and not any(l.kashrut for l in locs):
            continue
        if open_now and not any(_location_open_now(l) for l in locs):
            continue
        primary = next((l for l in locs if l.is_primary), locs[0] if locs else None)
        results.append({
            'id': b.id, 'title': b.name, 'snippet': (b.about or '')[:160],
            'category': b.category, 'city': primary.city if primary else None,
            'kashrut': primary.kashrut if primary else None,
            'rating_avg': b.rating_avg, 'path': f'/business/{b.slug}', 'site_id': 'business',
        })
        if len(results) >= limit:
            break
    return {'type': 'business', 'items': results}


def search_estates(q=None, listing_type=None, city=None, min_price=None, max_price=None,
                    min_bedrooms=None, max_bedrooms=None, limit=TOOL_RESULT_LIMIT):
    """Estates listings. `listing_type` is one of sale/long_term_lease/
    short_term_lease. Free-text `q` reuses unified search's full-text
    match; the numeric/type filters are applied directly against
    EstatesListing since unified search doesn't expose them."""
    from backend.estates.modals.estates import EstatesListing
    now = datetime.utcnow()
    if q:
        items = _search_estates(q, limit * 4)
        ids = [i['id'] for i in items]
        if not ids:
            return {'type': 'estates', 'items': []}
        rows = EstatesListing.query.filter(EstatesListing.id.in_(ids)).all()
        by_id = {l.id: l for l in rows}
        ordered = [by_id[i['id']] for i in items if i['id'] in by_id]
    else:
        query = EstatesListing.query.filter(
            db.or_(EstatesListing.expires_at.is_(None), EstatesListing.expires_at > now))
        if listing_type:
            query = query.filter(EstatesListing.listing_type == listing_type)
        if city:
            query = query.filter(db.or_(
                EstatesListing.city.ilike(f'%{city}%'), EstatesListing.neighborhood.ilike(f'%{city}%')))
        if min_price is not None:
            query = query.filter(EstatesListing.price >= min_price)
        if max_price is not None:
            query = query.filter(EstatesListing.price <= max_price)
        if min_bedrooms is not None:
            query = query.filter(EstatesListing.bedrooms >= min_bedrooms)
        if max_bedrooms is not None:
            query = query.filter(EstatesListing.bedrooms <= max_bedrooms)
        ordered = query.order_by(EstatesListing.pub_date.desc()).limit(limit).all()

    results = [{
        'id': l.id, 'title': l.title,
        'snippet': (l.description or '')[:160],
        'price': l.price, 'currency': l.currency, 'bedrooms': l.bedrooms,
        'city': l.city, 'listing_type': l.listing_type,
        'path': f'/listings/{l.slug}', 'site_id': 'estates',
    } for l in ordered[:limit]]
    return {'type': 'estates', 'items': results}


def search_tachlis(q=None, post_type=None, location=None, category=None, remote=None, limit=TOOL_RESULT_LIMIT):
    """Job Board (Gut Money). `post_type` is 'job' or 'resume'."""
    now = datetime.utcnow()
    if q:
        items = _search_tachlis(q, limit * 4)
        ids = [i['id'] for i in items]
        if not ids:
            return {'type': 'tachlis', 'items': []}
        rows = TachlisPost.query.filter(TachlisPost.id.in_(ids)).all()
        by_id = {p.id: p for p in rows}
        ordered = [by_id[i['id']] for i in items if i['id'] in by_id]
    else:
        query = TachlisPost.query.filter(TachlisPost.approved_to_publish.is_(True)).filter(
            db.or_(TachlisPost.expires_at.is_(None), TachlisPost.expires_at > now))
        if post_type:
            query = query.filter(TachlisPost.post_type == post_type)
        if location:
            query = query.filter(TachlisPost.location.ilike(f'%{location}%'))
        if category:
            query = query.filter(TachlisPost.category.ilike(f'%{category}%'))
        if remote is not None:
            query = query.filter(TachlisPost.remote.is_(remote))
        ordered = query.order_by(TachlisPost.pub_date.desc()).limit(limit).all()

    results = [{
        'id': p.id, 'title': p.title,
        'snippet': ' · '.join(x for x in (p.location, p.compensation) if x),
        'post_type': p.post_type, 'location': p.location, 'compensation': p.compensation,
        'remote': p.remote, 'path': f'/tachlis/post/{p.id}', 'site_id': 'money',
    } for p in ordered[:limit]]
    return {'type': 'tachlis', 'items': results}


def search_torah(q, limit=TOOL_RESULT_LIMIT):
    """Torah learning content (Gut Torah)."""
    return {'type': 'torah', 'items': _search_torah(q, limit)}


def search_minyanim(city=None, tefilah=None, limit=TOOL_RESULT_LIMIT):
    """Prayer-time search across every shul, mirroring
    backend/business/routes/minyan.py's own search_minyanim view (that one
    can't be called directly -- it reads request.args itself -- so the same
    filter logic is rebuilt here against the same models)."""
    query = Minyan.query.join(Business, Business.id == Minyan.business_id).filter(Business.category == 'shul')
    if city:
        loc_ids = db.session.query(BusinessLocation.business_id).filter(BusinessLocation.city.ilike(f'%{city}%'))
        query = query.filter(Business.id.in_(loc_ids))
    if tefilah:
        tefilah = tefilah.strip().lower()
        if tefilah in TEFILAH_TYPES:
            query = query.filter(Minyan.tefilah == tefilah)
    rows = query.order_by(Business.name, Minyan.tefilah, Minyan.fixed_time).limit(limit).all()

    results = []
    for m in rows:
        loc = next((l for l in m.business.locations if l.is_primary), None)
        results.append({
            'business_name': m.business.name, 'business_slug': m.business.slug,
            'tefilah': m.tefilah, 'label': m.label,
            'time': m.fixed_time.isoformat() if m.fixed_time else None,
            'relative_anchor': m.relative_anchor, 'relative_offset_minutes': m.relative_offset_minutes,
            'days': m.days, 'city': loc.city if loc else None,
            'path': f'/business/{m.business.slug}', 'site_id': 'business',
        })
    return {'type': 'minyan', 'items': results, 'disclaimer': 'Always confirm times directly with the shul.'}


def run_calculator(name, inputs):
    """`name` is one of the keys in CALCULATORS below; `inputs` is a dict of
    that calculator's named arguments. Raises ValueError on an unknown name
    or missing/invalid inputs -- the chat loop (chat.py) catches this and
    reports it back to the model as a tool error rather than crashing the
    request, same as the model would see any other tool failure."""
    from backend.askgut import calculators as calc

    def mortgage(price, down_pct=20, rate=6.5, years=30, currency='USD'):
        loan = price * (1 - down_pct / 100)
        payment = calc.monthly_pi(loan, rate, years)
        return {
            'loan_amount': round(loan), 'monthly_principal_and_interest': round(payment),
            'total_interest_over_life': round(calc.total_interest(loan, rate, years)),
            'currency': currency,
        }

    def affordability(annual_income, monthly_debts=0, down_payment=0, rate=6.5, years=30,
                       front_end_pct=28, back_end_pct=36, currency='USD'):
        monthly_income = annual_income / 12
        max_by_front = monthly_income * (front_end_pct / 100)
        max_by_back = monthly_income * (back_end_pct / 100) - monthly_debts
        max_payment = max(0, min(max_by_front, max_by_back))
        binding = 'front-end' if max_by_front <= max_by_back else 'back-end'
        r = rate / 100 / 12
        n = years * 12
        max_loan = max_payment * ((1 + r) ** n - 1) / (r * (1 + r) ** n) if r else max_payment * n
        return {
            'max_monthly_payment': round(max_payment), 'max_loan': round(max_loan),
            'max_price': round(max_loan + down_payment), 'binding_rule': binding, 'currency': currency,
        }

    def compound_interest(principal, monthly_contribution, rate, years, currency='USD'):
        final_value = calc.future_value_with_contributions(principal, monthly_contribution, rate, years)
        return {
            'final_value': round(final_value), 'total_contributed': round(principal + monthly_contribution * years * 12),
            'total_growth': round(final_value - principal - monthly_contribution * years * 12), 'currency': currency,
        }

    def debt_payoff(balance, rate, monthly_payment, currency='USD'):
        months = calc.months_to_payoff(balance, rate, monthly_payment)
        if months == float('inf'):
            return {'months': None, 'message': 'This payment never covers the interest -- the balance would never shrink.', 'currency': currency}
        return {'months': round(months), 'years': round(months / 12, 1), 'currency': currency}

    def fire_number(annual_expenses, withdrawal_rate_pct=4, currency='USD'):
        number = annual_expenses / (withdrawal_rate_pct / 100)
        return {'fire_number': round(number), 'multiple_of_annual_expenses': round(number / annual_expenses, 1), 'currency': currency}

    def israel_purchase_tax(property_value, is_additional_dwelling=False):
        result = calc.israel_purchase_tax(property_value, is_additional_dwelling)
        return {'total_tax_nis': round(result['total']), 'total_to_close_nis': round(property_value + result['total']),
                'breakdown': result['breakdown'], 'currency': 'ILS'}

    def israel_sale_tax(purchase_price, sale_price, sole_residence=True, owned_months=0):
        result = calc.israel_sale_tax(purchase_price, sale_price, sole_residence, owned_months)
        return {k: round(v) if isinstance(v, (int, float)) else v for k, v in result.items()} | {'currency': 'ILS'}

    calculators = {
        'mortgage': mortgage, 'affordability': affordability, 'compound_interest': compound_interest,
        'debt_payoff': debt_payoff, 'fire_number': fire_number,
        'israel_purchase_tax': israel_purchase_tax, 'israel_sale_tax': israel_sale_tax,
    }
    fn = calculators.get(name)
    if not fn:
        raise ValueError(f"Unknown calculator '{name}'. Valid: {', '.join(calculators)}")
    return fn(**(inputs or {}))
