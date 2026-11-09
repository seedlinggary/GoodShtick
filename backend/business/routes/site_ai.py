"""The site builder's AI assistant (Phase 12): "build me a page for a
bakery", "make it blue", "add a contact form" -- one endpoint that takes
the current design + an instruction and returns a complete new design.

Same JSON-mode convention as every other single-shot AI call in this
codebase (ai_content.py/estates.py/tachlis_post.py: one prompt, one fixed
JSON shape, no tool-calling loop -- that's only used by askgut/chat.py,
which has a genuinely open-ended "which of 7 data sources" problem this
doesn't). Public, not business-scoped: the free, no-login builder at
/build needs AI help too (see FreeBuilder.js), so this never touches a
business/site/page itself -- the caller applies the returned sections/
theme to whatever local state it already has and saves through the
existing routes, same as a manual edit would.
"""
import json
import os

from flask import Blueprint, jsonify, request

from config import db
from security import token_required, token_optional, real_client_ip
from backend.business.modals.business import Business
from backend.business.modals.business_site import (
    BLOCK_TYPES, THEME_PALETTES, FONT_PAIRINGS, BUTTON_STYLES, FORM_STYLES,
    NAV_STYLES, FOOTER_STYLES, DEFAULT_THEME, validate_theme,
)
from backend.business.modals.site_ai_usage import check_and_record_generate, DAILY_GENERATE_CAP
from backend.business.routes.site_pages import _validate_sections, MAX_SECTIONS, MAX_BLOCKS_PER_SECTION

site_ai_api = Blueprint('site_ai_api', __name__, url_prefix='/business')

MODEL = 'gpt-4o-mini'
MAX_INSTRUCTION_CHARS = 500
MAX_INPUT_SECTIONS_JSON_CHARS = 20000  # defensive cap on what we'll even send back to the model
# Site-wide generate-site (below) works over every page at once, not just
# one -- MAX_INPUT_SECTIONS_JSON_CHARS above is sized for a single page and
# doesn't scale to a whole site, so this is its own, larger cap on the
# TOTAL json across every page sent in one request.
MAX_SITE_PAGES = 30
MAX_INPUT_SITE_JSON_CHARS = 60000
SITE_MODEL_MAX_TOKENS = 8000


def _can_manage(business, user):
    # Same private-per-file helper every sibling site-builder route file
    # already has its own copy of (business_site.py, site_pages.py, ...) --
    # site builder's still super-admin-only while being tested on prod, see
    # BusinessOwnerTools.js's RESTRICTED_TABS comment.
    return bool(user and user.is_super_admin)


def _system_prompt():
    return (
        "You design pages for a small business's own website builder. You "
        "receive the CURRENT page as a JSON `sections` array plus a `theme` "
        "object, and an instruction from the business owner. Return a "
        "complete REPLACEMENT for both -- never a diff/patch.\n\n"
        "Schema (follow exactly, nothing else is valid):\n"
        "sections: a list of {\"id\": string, \"background\": {\"type\": \"color\", "
        "\"value\": a hex color or \"transparent\"}, \"padding\": {\"top\": number, "
        "\"bottom\": number}, \"blocks\": [...]}. Sections stack full-width top to "
        "bottom on the real page -- do not try to place sections side by side.\n"
        "Each block: {\"id\": string, \"type\": one of " + json.dumps(list(BLOCK_TYPES)) + ", "
        "\"x\": number 0-100, \"y\": number 0-100, \"w\": number 0-100, \"h\": number 0-100, "
        "\"content\": object (shape depends on type, see below), \"mobileLayout\": null}. "
        "x/y/w/h are PERCENTAGES OF THE SECTION, not the page -- keep x+w <= 100 and "
        "y+h <= 100, and don't overlap blocks within the same section.\n"
        "content by type: text={\"text\":string,\"fontSize\":number,\"align\":\"left\"|"
        "\"center\"|\"right\"}; image={\"src\":null,\"alt\":string} (never invent a src -- "
        "always null, the owner uploads a real photo themselves); button={\"text\":string,"
        "\"href\":string}; spacer={}; form={\"heading\":string}; map={\"address\":string}; "
        "gallery={\"images\":[]}; product_grid={}; product_detail={\"productId\":null,"
        "\"serviceName\":null}; booking_widget={\"serviceTypeId\":null,\"serviceName\":null}; "
        "analytics_widget={}.\n"
        f"At most {MAX_SECTIONS} sections, at most {MAX_BLOCKS_PER_SECTION} blocks per section.\n\n"
        "theme: {\"palette\": one of " + json.dumps(list(THEME_PALETTES.keys())) + ", "
        "\"fontPairing\": one of " + json.dumps(list(FONT_PAIRINGS.keys())) + ", "
        "\"buttonStyle\": one of " + json.dumps(list(BUTTON_STYLES.keys())) + ", "
        "\"formStyle\": one of " + json.dumps(list(FORM_STYLES.keys())) + ", "
        "\"navStyle\": one of " + json.dumps(list(NAV_STYLES.keys())) + ", "
        "\"footerStyle\": one of " + json.dumps(list(FOOTER_STYLES.keys())) + "}.\n\n"
        "If the instruction only asks for a color/font/style change, return the SAME "
        "sections unchanged and only change theme. If it asks to add/change content, "
        "keep every existing section/block that the instruction doesn't mention, and "
        "only add/modify what it actually asks for. If the current sections are empty "
        "and the instruction asks to build a page, design a real, well-laid-out page "
        "(a hero, then relevant content sections) with genuine, specific-sounding "
        "placeholder copy -- never lorem ipsum, never a literal placeholder like "
        "\"Your Business Name\".\n\n"
        "Respond ONLY with a single JSON object: {\"sections\": [...], \"theme\": {...}, "
        "\"message\": a short one-sentence summary of what you did, written to the "
        "owner (e.g. \"Built a bakery homepage with a hero, about section, and "
        "contact form.\")}. Do not wrap it in markdown fences."
    )


def _caller_identity(current_user):
    if current_user:
        return f'user:{current_user.public_id}'
    # real_client_ip(), not request.remote_addr -- see security.py: remote_addr
    # is constant on this deployment regardless of who's connecting, which
    # made this a shared 15-generations-per-day cap for every anonymous
    # caller site-wide instead of per-visitor.
    return f'ip:{real_client_ip() or "unknown"}'


@site_ai_api.route('/site-ai/generate', methods=['POST'])
@token_optional
def generate_design(current_user):
    if not os.environ.get('OPENAI_API_KEY'):
        return jsonify({'message': 'The AI assistant is not configured on this deployment yet'}), 501

    body = request.get_json() or {}
    instruction = (body.get('instruction') or '').strip()
    if not instruction:
        return jsonify({'message': 'instruction is required'}), 400
    if len(instruction) > MAX_INSTRUCTION_CHARS:
        return jsonify({'message': f'instruction must be {MAX_INSTRUCTION_CHARS} characters or fewer'}), 400

    current_sections = body.get('sections') or []
    current_theme = {**DEFAULT_THEME, **(body.get('theme') or {})}
    if not isinstance(current_sections, list):
        return jsonify({'message': 'sections must be a list'}), 400
    if len(json.dumps(current_sections)) > MAX_INPUT_SECTIONS_JSON_CHARS:
        return jsonify({'message': "This page is too large for the AI assistant to edit -- try a smaller change manually first"}), 400

    identity = _caller_identity(current_user)
    if not check_and_record_generate(identity):
        db.session.rollback()
        return jsonify({'message': f"You've used today's {DAILY_GENERATE_CAP} AI requests -- try again tomorrow"}), 429
    db.session.commit()

    from openai import OpenAI
    client = OpenAI()

    user_message = json.dumps({'current_sections': current_sections, 'current_theme': current_theme, 'instruction': instruction})

    try:
        resp = client.chat.completions.create(
            model=MODEL,
            messages=[
                {'role': 'system', 'content': _system_prompt()},
                {'role': 'user', 'content': user_message},
            ],
            response_format={'type': 'json_object'},
            temperature=0.7,
            max_tokens=3000,
        )
        raw = (resp.choices[0].message.content or '').strip()
        data = json.loads(raw)
    except Exception as exc:  # noqa: BLE001 -- surface a clean error, never a stack trace to the browser
        return jsonify({'message': f'The AI assistant had a problem: {exc}'}), 502

    sections = data.get('sections')
    theme = data.get('theme') or {}
    message = (data.get('message') or 'Done.').strip()

    sections_error = _validate_sections(sections if sections is not None else [])
    if sections_error:
        return jsonify({'message': f'The AI assistant returned an invalid design ({sections_error}) -- try rephrasing your request'}), 502
    theme_error = validate_theme(theme)
    if theme_error:
        return jsonify({'message': f'The AI assistant returned an invalid theme ({theme_error}) -- try rephrasing your request'}), 502

    return jsonify({'sections': sections, 'theme': theme, 'message': message})


def _system_prompt_site():
    """Same block/theme schema as _system_prompt() above, but for a request
    spanning the WHOLE site at once ("make it feel more modern", "update
    the hero on Home and About") -- the input is a LIST of pages, each
    with its own id, and the model may touch any subset of them plus the
    theme in one reply, instead of being limited to one page per call."""
    return (
        "You design pages for a small business's own website builder. You "
        "receive the business's CURRENT pages as a JSON list (each with an "
        "\"id\", \"slug\", \"title\", and its \"sections\" array), a \"theme\" "
        "object shared by every page, and an instruction from the business "
        "owner. You may change the theme and/or any subset of the pages' "
        "sections -- NEVER invent a new page id, and you cannot add or "
        "remove pages (that stays a manual action for the owner).\n\n"
        "Schema for a page's sections (follow exactly, nothing else is valid):\n"
        "sections: a list of {\"id\": string, \"background\": {\"type\": \"color\", "
        "\"value\": a hex color or \"transparent\"}, \"padding\": {\"top\": number, "
        "\"bottom\": number}, \"blocks\": [...]}. Sections stack full-width top to "
        "bottom on the real page -- do not try to place sections side by side.\n"
        "Each block: {\"id\": string, \"type\": one of " + json.dumps(list(BLOCK_TYPES)) + ", "
        "\"x\": number 0-100, \"y\": number 0-100, \"w\": number 0-100, \"h\": number 0-100, "
        "\"content\": object (shape depends on type, see below), \"mobileLayout\": null}. "
        "x/y/w/h are PERCENTAGES OF THE SECTION, not the page -- keep x+w <= 100 and "
        "y+h <= 100, and don't overlap blocks within the same section.\n"
        "content by type: text={\"text\":string,\"fontSize\":number,\"align\":\"left\"|"
        "\"center\"|\"right\"}; image={\"src\":null,\"alt\":string} (never invent a src -- "
        "always null, the owner uploads a real photo themselves); button={\"text\":string,"
        "\"href\":string}; spacer={}; form={\"heading\":string}; map={\"address\":string}; "
        "gallery={\"images\":[]}; product_grid={}; product_detail={\"productId\":null,"
        "\"serviceName\":null}; booking_widget={\"serviceTypeId\":null,\"serviceName\":null}; "
        "analytics_widget={}.\n"
        f"At most {MAX_SECTIONS} sections per page, at most {MAX_BLOCKS_PER_SECTION} blocks per section.\n\n"
        "theme: {\"palette\": one of " + json.dumps(list(THEME_PALETTES.keys())) + ", "
        "\"fontPairing\": one of " + json.dumps(list(FONT_PAIRINGS.keys())) + ", "
        "\"buttonStyle\": one of " + json.dumps(list(BUTTON_STYLES.keys())) + ", "
        "\"formStyle\": one of " + json.dumps(list(FORM_STYLES.keys())) + ", "
        "\"navStyle\": one of " + json.dumps(list(NAV_STYLES.keys())) + ", "
        "\"footerStyle\": one of " + json.dumps(list(FOOTER_STYLES.keys())) + "}.\n\n"
        "If the instruction only asks for a site-wide color/font/style change, set "
        "\"theme\" to the new theme and omit \"pages\" (or return it empty) unless the "
        "instruction also specifically calls out page content. If it names specific "
        "pages or content, only include THOSE pages in your reply, each with its "
        "COMPLETE replacement sections array (every section/block that page keeps, not "
        "just what changed) -- keep every existing section/block the instruction "
        "doesn't mention. Never touch a page the instruction doesn't call for or "
        "clearly imply (a request about \"the homepage\" means only the page whose id "
        "is marked as home).\n\n"
        "Respond ONLY with a single JSON object: {\"theme\": {...} (omit if unchanged), "
        "\"pages\": [{\"id\": \"<must match one of the input ids>\", \"sections\": [...]}, ...] "
        "(omit or empty if no page content changed), \"message\": a short one-sentence "
        "summary of what you did, written to the owner}. Do not wrap it in markdown fences."
    )


@site_ai_api.route('/businesses/<int:business_id>/site-ai/generate-site', methods=['POST'])
@token_required
def generate_site_design(current_user, business_id):
    """Site-wide sibling of generate_design() above -- one instruction can
    touch multiple pages (plus the theme) in a single reply, for requests
    like "make the whole site feel more modern" that don't make sense
    scoped to whichever one page happens to be open. Owner-authenticated
    (unlike the single-page route, which is also used by the no-login
    FreeBuilder.js) -- see SiteAiAssistant.js for the caller."""
    business = db.session.get(Business, business_id)
    if not business:
        return jsonify({'message': 'Business not found'}), 404
    if not _can_manage(business, current_user):
        return jsonify({'message': 'Not authorized'}), 403

    if not os.environ.get('OPENAI_API_KEY'):
        return jsonify({'message': 'The AI assistant is not configured on this deployment yet'}), 501

    body = request.get_json() or {}
    instruction = (body.get('instruction') or '').strip()
    if not instruction:
        return jsonify({'message': 'instruction is required'}), 400
    if len(instruction) > MAX_INSTRUCTION_CHARS:
        return jsonify({'message': f'instruction must be {MAX_INSTRUCTION_CHARS} characters or fewer'}), 400

    current_theme = {**DEFAULT_THEME, **(body.get('theme') or {})}
    pages = body.get('pages')
    if not isinstance(pages, list) or not pages:
        return jsonify({'message': 'pages must be a non-empty list'}), 400
    if len(pages) > MAX_SITE_PAGES:
        return jsonify({'message': f'This site has too many pages for the AI assistant to edit at once (max {MAX_SITE_PAGES})'}), 400

    input_pages = []
    valid_ids = set()
    for p in pages:
        if not isinstance(p, dict) or p.get('id') is None:
            return jsonify({'message': 'Each page needs an id'}), 400
        page_id = p['id']
        valid_ids.add(page_id)
        input_pages.append({
            'id': page_id,
            'slug': p.get('slug') or '',
            'title': p.get('title') or '',
            'sections': p.get('sections') or [],
        })
    if len(json.dumps(input_pages)) > MAX_INPUT_SITE_JSON_CHARS:
        return jsonify({'message': 'This site is too large for the AI assistant to edit all at once -- try asking about fewer pages, or edit one page at a time instead'}), 400

    identity = _caller_identity(current_user)
    if not check_and_record_generate(identity):
        db.session.rollback()
        return jsonify({'message': f"You've used today's {DAILY_GENERATE_CAP} AI requests -- try again tomorrow"}), 429
    db.session.commit()

    from openai import OpenAI
    client = OpenAI()

    user_message = json.dumps({'current_pages': input_pages, 'current_theme': current_theme, 'instruction': instruction})

    try:
        resp = client.chat.completions.create(
            model=MODEL,
            messages=[
                {'role': 'system', 'content': _system_prompt_site()},
                {'role': 'user', 'content': user_message},
            ],
            response_format={'type': 'json_object'},
            temperature=0.7,
            max_tokens=SITE_MODEL_MAX_TOKENS,
        )
        raw = (resp.choices[0].message.content or '').strip()
        data = json.loads(raw)
    except Exception as exc:  # noqa: BLE001 -- surface a clean error, never a stack trace to the browser
        return jsonify({'message': f'The AI assistant had a problem: {exc}'}), 502

    theme = data.get('theme')
    returned_pages = data.get('pages') or []
    message = (data.get('message') or 'Done.').strip()

    if theme is not None:
        theme_error = validate_theme(theme)
        if theme_error:
            return jsonify({'message': f'The AI assistant returned an invalid theme ({theme_error}) -- try rephrasing your request'}), 502

    if not isinstance(returned_pages, list):
        return jsonify({'message': 'The AI assistant returned an invalid response -- try rephrasing your request'}), 502

    cleaned_pages = []
    for rp in returned_pages:
        if not isinstance(rp, dict) or rp.get('id') not in valid_ids:
            return jsonify({'message': 'The AI assistant referenced a page that doesn\'t exist -- try rephrasing your request'}), 502
        sections_error = _validate_sections(rp.get('sections') or [])
        if sections_error:
            return jsonify({'message': f'The AI assistant returned an invalid design for one of your pages ({sections_error}) -- try rephrasing your request'}), 502
        cleaned_pages.append({'id': rp['id'], 'sections': rp.get('sections') or []})

    return jsonify({'theme': theme, 'pages': cleaned_pages, 'message': message})
