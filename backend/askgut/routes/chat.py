"""Ask GUT -- the cross-site chat assistant. POST /askgut/chat is the one
endpoint; everything it can talk about is answered by calling one of the
tools in backend/askgut/tools.py, each a thin wrapper around an existing
query function/model (see that module's own docstring). This is the first
use of OpenAI function/tool-calling anywhere in this codebase -- every
other GPT call here (ai_content.py, estates.py, tachlis_post.py) is a
single JSON-mode prompt producing one fixed shape. A single prompt can't
reliably pick the right one of 7 very different data sources and the right
parameters for it, which is what a chat question actually needs, so this
introduces the standard tool-calling loop instead of stretching JSON mode
further than it fits.

Same OpenAI-availability convention as every other call site: lazy import,
guarded by an env-var check, so this module still imports fine in an
environment without the openai package or key installed."""
import json
import os
from datetime import date

from flask import Blueprint, jsonify, request

from config import db
from security import token_optional
from backend.askgut import tools as askgut_tools
from backend.askgut.modals.usage import AskGutUsage
from backend.business.modals.business import BUSINESS_CATEGORIES
from backend.estates.modals.estates import LISTING_TYPES
from backend.tachlis.modals.tachlis_post import POST_TYPES
from backend.user.modals.user import LINE_OF_WORK_OPTIONS

askgut_api = Blueprint('askgut_api', __name__, url_prefix='/askgut')

MODEL = 'gpt-4o-mini'
MAX_TOOL_ROUNDS = 3
MAX_HISTORY_MESSAGES = 16  # ~8 user/assistant turns, kept client-side and resent each call
DAILY_MESSAGE_CAP = 40
MAX_COMPLETION_TOKENS = 500

SYSTEM_PROMPT = """You are "Ask GUT," the help assistant for The Good Shtick \
-- a family of community sites for a Jewish community: Gut Shtick (a humor/\
pin board and the Hock discussion forum), Gut Community (a local business \
directory), Gut Estates (real-estate listings), Gut Money (a job board and \
financial calculators), and Gut Torah (learning content). Shuls, minyan \
times, and kosher/kashrut info live in the Business directory.

Always call a tool to look up real data before answering anything about \
these sites -- never invent a business, listing, job post, forum thread, \
Torah source, minyan time, or a calculator result from memory. If a \
question is clearly unrelated to these sites and needs no site data \
(general trivia, something you'd just know), say so briefly and decline \
rather than guessing at an answer that isn't your job.

A logged-in caller's rough home area and line of work may be given to you \
as background context below -- use it only to quietly default an \
unspecified location/category in a search (the same "bias, never filter" \
rule the site's own personalized feed already follows), never to exclude \
an otherwise-good result, and never mention these details back to the \
caller unless they bring them up first.

Keep replies short -- a few sentences, not an essay. When a tool returns \
items, don't re-list every field in prose: the app renders the actual \
result cards itself, so just introduce/summarize them naturally ("Here are \
a few shuls in Lakewood with a Shacharit minyan:") and let the cards carry \
the detail."""

TOOL_SPECS = [
    {'type': 'function', 'function': {
        'name': 'search_shtick_hock',
        'description': "Search Gut Shtick's pin/humor board and the Hock discussion forum by free text.",
        'parameters': {'type': 'object', 'properties': {
            'query': {'type': 'string'},
        }, 'required': ['query']},
    }},
    {'type': 'function', 'function': {
        'name': 'search_business',
        'description': 'Search the Business directory -- shuls, restaurants, stores, services, mikvahs, etc.',
        'parameters': {'type': 'object', 'properties': {
            'q': {'type': 'string', 'description': 'Free-text match against the business name/about.'},
            'category': {'type': 'string', 'enum': list(BUSINESS_CATEGORIES)},
            'city': {'type': 'string'},
            'kashrut_only': {'type': 'boolean', 'description': 'Only businesses with a kashrut certification on file.'},
            'open_now': {'type': 'boolean'},
        }},
    }},
    {'type': 'function', 'function': {
        'name': 'search_estates',
        'description': 'Search real-estate listings (for sale or for rent).',
        'parameters': {'type': 'object', 'properties': {
            'q': {'type': 'string'},
            'listing_type': {'type': 'string', 'enum': list(LISTING_TYPES)},
            'city': {'type': 'string'},
            'min_price': {'type': 'number'}, 'max_price': {'type': 'number'},
            'min_bedrooms': {'type': 'number'}, 'max_bedrooms': {'type': 'number'},
        }},
    }},
    {'type': 'function', 'function': {
        'name': 'search_tachlis',
        'description': 'Search the Job Board -- job openings or resumes/open-to-work posts.',
        'parameters': {'type': 'object', 'properties': {
            'q': {'type': 'string'},
            'post_type': {'type': 'string', 'enum': list(POST_TYPES)},
            'location': {'type': 'string'},
            'category': {'type': 'string'},
            'remote': {'type': 'boolean'},
        }},
    }},
    {'type': 'function', 'function': {
        'name': 'search_torah',
        'description': 'Search Torah learning content (divrei Torah, shiurim, sources).',
        'parameters': {'type': 'object', 'properties': {
            'query': {'type': 'string'},
        }, 'required': ['query']},
    }},
    {'type': 'function', 'function': {
        'name': 'search_minyanim',
        'description': 'Find prayer (minyan) times across shuls. Always confirm with the shul directly -- times can change.',
        'parameters': {'type': 'object', 'properties': {
            'city': {'type': 'string'},
            'tefilah': {'type': 'string', 'enum': ['shacharit', 'mincha', 'maariv', 'other']},
        }},
    }},
    {'type': 'function', 'function': {
        'name': 'run_calculator',
        'description': (
            'Compute a real financial number -- use this instead of estimating math yourself. '
            "'mortgage': monthly payment from a price. 'affordability': max affordable price from income. "
            "'compound_interest': savings growth with contributions. 'debt_payoff': months to pay off a balance. "
            "'fire_number': a retirement target from annual expenses. 'israel_purchase_tax'/'israel_sale_tax': "
            'Israeli real-estate tax (mas rechisha/mas shevach).'
        ),
        'parameters': {'type': 'object', 'properties': {
            'name': {'type': 'string', 'enum': [
                'mortgage', 'affordability', 'compound_interest', 'debt_payoff',
                'fire_number', 'israel_purchase_tax', 'israel_sale_tax',
            ]},
            'inputs': {
                'type': 'object',
                'description': (
                    "Named arguments for the chosen calculator, e.g. mortgage: {price, down_pct, rate, years, "
                    "currency}; affordability: {annual_income, monthly_debts, down_payment, rate, years}; "
                    "compound_interest: {principal, monthly_contribution, rate, years}; debt_payoff: {balance, "
                    "rate, monthly_payment}; fire_number: {annual_expenses, withdrawal_rate_pct}; "
                    "israel_purchase_tax: {property_value, is_additional_dwelling}; israel_sale_tax: "
                    "{purchase_price, sale_price, sole_residence, owned_months}."
                ),
            },
        }, 'required': ['name', 'inputs']},
    }},
]

TOOL_FUNCTIONS = {
    'search_shtick_hock': lambda args: askgut_tools.search_shtick_hock(args['query']),
    'search_business': lambda args: askgut_tools.search_business(**args),
    'search_estates': lambda args: askgut_tools.search_estates(**args),
    'search_tachlis': lambda args: askgut_tools.search_tachlis(**args),
    'search_torah': lambda args: askgut_tools.search_torah(args['query']),
    'search_minyanim': lambda args: askgut_tools.search_minyanim(**args),
    'run_calculator': lambda args: askgut_tools.run_calculator(args['name'], args.get('inputs') or {}),
}


def _caller_identity(current_user):
    """A logged-in user's public_id, or an anonymous caller's IP -- the
    (identity, date) key AskGutUsage caps on. request.remote_addr is used
    as-is (no X-Forwarded-For handling) -- same simple convention the one
    other IP check in this codebase (ads/routes/ads.py's localhost check)
    already uses; fine for a soft abuse cap, not meant to be unspoofable."""
    if current_user:
        return current_user.public_id
    return f'ip:{request.remote_addr or "unknown"}'


def _check_and_increment_usage(identity):
    """Returns True if this message is allowed (and records it), False if
    today's cap is already hit. One row per (identity, date) -- see
    AskGutUsage's own docstring for why this is a bare counter, not a
    ledger."""
    today = date.today()
    row = AskGutUsage.query.filter_by(identity=identity, usage_date=today).first()
    if row is None:
        row = AskGutUsage(identity=identity, usage_date=today, message_count=0)
        db.session.add(row)
    if row.message_count >= DAILY_MESSAGE_CAP:
        return False, row
    row.message_count += 1
    return True, row


def _profile_context(current_user):
    """Same shape/philosophy as backend/feed/routes/aggregate.py's
    _profile_from_user -- bias hints for the system prompt, never a hard
    filter, None when the viewer has nothing set (including when
    anonymous)."""
    if not current_user:
        return None
    area = current_user.profile_area or None
    work = current_user.line_of_work if current_user.line_of_work in LINE_OF_WORK_OPTIONS else None
    if not area and not work:
        return None
    bits = []
    if area:
        bits.append(f'home area: {area}')
    if work:
        bits.append(f'line of work: {work}')
    return 'Caller profile (bias only, never filter): ' + '; '.join(bits)


@askgut_api.route('/chat', methods=['POST'])
@token_optional
def chat(current_user):
    """Body: {message: str, history: [{role, content}]} (history is the
    last few turns of this conversation, kept client-side -- see
    AskGutWidget.js). Returns {reply, results: [{type, items}], usage:
    {used, cap}}."""
    if not os.environ.get('OPENAI_API_KEY'):
        return jsonify({'message': 'Ask GUT is not configured on the server right now.'}), 500

    body = request.get_json(silent=True) or {}
    message = (body.get('message') or '').strip()
    if not message:
        return jsonify({'message': 'message is required'}), 400
    if len(message) > 1000:
        return jsonify({'message': 'Please keep questions under 1000 characters.'}), 400

    identity = _caller_identity(current_user)
    allowed, usage_row = _check_and_increment_usage(identity)
    if not allowed:
        return jsonify({
            'message': "You've hit today's question limit for Ask GUT -- try again tomorrow.",
        }), 429
    db.session.commit()  # commit the usage row even if the OpenAI call below fails

    history = body.get('history') or []
    if not isinstance(history, list):
        history = []
    # Only role/content survive from client-sent history -- never trust a
    # client-supplied tool_call_id/tool role back into the message list.
    clean_history = [
        {'role': h.get('role'), 'content': h.get('content')}
        for h in history[-MAX_HISTORY_MESSAGES:]
        if isinstance(h, dict) and h.get('role') in ('user', 'assistant') and h.get('content')
    ]

    system_content = SYSTEM_PROMPT
    profile_note = _profile_context(current_user)
    if profile_note:
        system_content += f'\n\n{profile_note}'

    messages = [{'role': 'system', 'content': system_content}, *clean_history, {'role': 'user', 'content': message}]

    # Imported lazily, same convention as every other OpenAI call site in
    # this codebase (ai_content.py/estates.py/tachlis_post.py) -- the
    # module still imports fine without the openai package/key present.
    from openai import OpenAI
    client = OpenAI()

    collected_results = []
    try:
        for _round in range(MAX_TOOL_ROUNDS):
            resp = client.chat.completions.create(
                model=MODEL, messages=messages, tools=TOOL_SPECS,
                max_tokens=MAX_COMPLETION_TOKENS,
            )
            choice = resp.choices[0]
            usage_row.prompt_tokens += resp.usage.prompt_tokens or 0
            usage_row.completion_tokens += resp.usage.completion_tokens or 0

            if choice.finish_reason != 'tool_calls' or not choice.message.tool_calls:
                db.session.commit()
                return jsonify({
                    'reply': choice.message.content or '',
                    'results': collected_results,
                    'usage': {'used': usage_row.message_count, 'cap': DAILY_MESSAGE_CAP},
                })

            messages.append(choice.message.model_dump(exclude_none=True))
            for tool_call in choice.message.tool_calls:
                name = tool_call.function.name
                try:
                    args = json.loads(tool_call.function.arguments or '{}')
                except (TypeError, ValueError):
                    args = {}
                fn = TOOL_FUNCTIONS.get(name)
                try:
                    if not fn:
                        raise ValueError(f'Unknown tool: {name}')
                    result = fn(args)
                    if isinstance(result, dict) and result.get('items'):
                        collected_results.append(result)
                    tool_content = json.dumps(result)
                except Exception as exc:  # noqa: BLE001 -- report the failure to the model, don't crash the request
                    tool_content = json.dumps({'error': str(exc)})
                messages.append({
                    'role': 'tool', 'tool_call_id': tool_call.id, 'content': tool_content,
                })

        # Exhausted MAX_TOOL_ROUNDS still wanting to call tools -- ask once
        # more without tool access so it's forced to answer with whatever
        # it already has instead of looping forever.
        final = client.chat.completions.create(
            model=MODEL, messages=messages, max_tokens=MAX_COMPLETION_TOKENS,
        )
        usage_row.prompt_tokens += final.usage.prompt_tokens or 0
        usage_row.completion_tokens += final.usage.completion_tokens or 0
        db.session.commit()
        return jsonify({
            'reply': final.choices[0].message.content or '',
            'results': collected_results,
            'usage': {'used': usage_row.message_count, 'cap': DAILY_MESSAGE_CAP},
        })
    except Exception as exc:  # noqa: BLE001 -- the usage row is already committed either way
        db.session.rollback()
        return jsonify({'message': f"Ask GUT couldn't complete that: {exc}"}), 502
