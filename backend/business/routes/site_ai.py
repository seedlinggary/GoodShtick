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
from security import token_optional
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
    return f'ip:{request.remote_addr or "unknown"}'


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
