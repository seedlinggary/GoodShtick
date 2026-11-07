# A small "compiler" for authoring site_template.py's sections, extracted
# from the same reflow/height-estimation logic built live-testing Altmax
# and KTY earlier this session (fix_altmax_round3.py in that work's
# scratchpad -- never shipped as app code, this is its first time as a
# real module). Hand-computing x/y/w/h percentages for dozens of blocks
# per template, times 4 pages, times 10 templates, is exactly the kind of
# arithmetic that produced the overlap/scrollbar bugs this session spent
# multiple rounds fixing on real businesses' sites. Instead: author each
# section as COLUMNS of blocks (only x/w meaningful, to say which column
# a block is in and how wide it is -- y/h are placeholders), then call
# compile_section() to compute real, non-overlapping y/h from each
# block's actual estimated pixel height, the same way the public site
# renders it.
import math

SECTION_WIDTH_PX = 1012
MIN_SECTION_HEIGHT = 200
BOTTOM_MARGIN_PX = 28
SAFETY = 1.15
FORM_SAFETY = 1.35

FIELD_PX = {
    'long_text': 21.6 + 87 + 10,
    'multi_choice': 21.6 + 70 + 10,
    'multi_text': 21.6 + 80 + 10,
    'name_date_list': 21.6 + 80 + 10,
}
DEFAULT_FIELD_PX = 21.6 + 39 + 10


def _feature_card_height_px(item, card_width_px):
    title = item.get('title') or ''
    desc = item.get('description') or ''
    h = 50
    title_cpl = max(8, (card_width_px - 32) / (16 * 0.55))
    h += max(1, math.ceil(len(title) / title_cpl)) * 20 + 6
    if desc:
        desc_cpl = max(8, (card_width_px - 32) / (13 * 0.54))
        h += max(1, math.ceil(len(desc) / desc_cpl)) * 19.5
    return h + 34


def _row_card_height_px(item, card_width_px):
    text_w = card_width_px - 44 - 16
    title = item.get('title') or ''
    desc = item.get('description') or ''
    title_cpl = max(8, text_w / (15 * 0.55))
    h = max(1, math.ceil(len(title) / title_cpl)) * 19 + 4
    if desc:
        desc_cpl = max(8, text_w / (13 * 0.52))
        h += max(1, math.ceil(len(desc) / desc_cpl)) * 19.5
    return max(44, h)


def _checklist_card_height_px(item, card_width_px):
    text_w = card_width_px - 28 - 10
    title = item.get('title') or ''
    cpl = max(8, text_w / (13 * 0.52))
    return max(1, math.ceil(len(title) / cpl)) * 18 + 28


def _timeline_card_height_px(item, card_width_px):
    text_w = card_width_px - 40
    title = item.get('title') or ''
    desc = item.get('description') or ''
    h = 30
    title_cpl = max(8, text_w / (15 * 0.55))
    h += max(1, math.ceil(len(title) / title_cpl)) * 19 + 8
    if desc:
        desc_cpl = max(8, text_w / (13 * 0.52))
        h += max(1, math.ceil(len(desc) / desc_cpl)) * 19.5
    return h + 40


def _stat_card_height_px(item, card_width_px):
    desc = item.get('description') or ''
    h = 36
    desc_cpl = max(6, card_width_px / (11 * 0.56))
    h += max(1, math.ceil(len(desc) / desc_cpl)) * 15
    return h + 10


def _panel_height_px(item, card_width_px):
    desc = item.get('description') or ''
    h = 36
    desc_cpl = max(8, (card_width_px - 36) / (14 * 0.52))
    h += max(1, math.ceil(len(desc) / desc_cpl)) * 22.4
    return h + 36


def _testimonial_card_height_px(item, card_width_px):
    quote = item.get('quote') or ''
    role = item.get('role')
    h = 20
    cpl = max(8, (card_width_px - 36) / (14 * 0.52))
    h += max(1, math.ceil(len(quote) / cpl)) * 22.4 + 20
    h += 17
    if role:
        h += 16
    return h + 38


def _service_card_height_px(item, card_width_px):
    right_w = card_width_px - 72 - 24 - 48
    title = item.get('title') or ''
    desc = item.get('description') or ''
    points = [p for p in (item.get('points') or []) if p]
    h = 0
    title_cpl = max(8, right_w / (20 * 0.55))
    h += max(1, math.ceil(len(title) / title_cpl)) * 25 + 8
    desc_cpl = max(8, right_w / (14 * 0.52))
    h += max(1, math.ceil(len(desc) / desc_cpl)) * 22.4
    if points:
        col_w = (right_w - 24) / 2
        point_cpl = max(8, col_w / (13 * 0.52))
        point_heights = [max(1, math.ceil(len(p) / point_cpl)) * 19.5 for p in points]
        rows = [point_heights[i:i + 2] for i in range(0, len(point_heights), 2)]
        h += 14 + sum(max(r) for r in rows) + (len(rows) - 1) * 6
    return max(h, 56 + 10 + 24) + 48


FEATURE_FNS = {
    'card': (_feature_card_height_px, 216),
    'row': (_row_card_height_px, 216),
    'checklist': (_checklist_card_height_px, 216),
    'timeline': (_timeline_card_height_px, 216),
    'stat': (_stat_card_height_px, 126),
    'panel': (_panel_height_px, 216),
}


def estimate_block_height_px(block, col_width_pct, form_fields=None):
    """form_fields, if given, is {formSlug: [field_type, ...]} -- only
    needed when a template embeds a real dynamic_form by slug (most
    templates use the static 'form' contact block instead, which doesn't
    need this)."""
    form_fields = form_fields or {}
    t = block['type']
    c = block.get('content') or {}
    col_width_px = SECTION_WIDTH_PX * (col_width_pct / 100)

    if t == 'text':
        text = c.get('text') or ''
        font_size = c.get('fontSize') or 16
        if not text:
            return font_size * 1.6
        chars_per_line = max(12, col_width_px / (font_size * 0.54))
        para_lines = 0
        for para in text.split('\n'):
            para_lines += max(1, math.ceil(len(para) / chars_per_line))
        return para_lines * (font_size * 1.5) + 10
    if t == 'button':
        return 46
    if t == 'image':
        return c.get('_h_px', 220)
    if t == 'map':
        return 240
    if t == 'google_reviews_badge':
        return 60
    if t == 'callout':
        return 90
    if t == 'logo_strip':
        n = len(c.get('items') or [])
        heading_px = 34 if c.get('heading') else 0
        cols = max(1, int(col_width_px // 140))
        rows = math.ceil(max(1, n) / cols)
        return heading_px + rows * 56
    if t == 'gallery':
        n = len(c.get('images') or [])
        if n == 0:
            return 150
        cols = max(1, int((col_width_px + 6) // 96))
        rows = math.ceil(n / cols)
        return rows * 90 + (rows - 1) * 6 + 10
    if t in ('form', 'dynamic_form'):
        fields = form_fields.get(c.get('formSlug'), [])
        if not fields:
            return c.get('_h_px', 280)
        per_field = sum(FIELD_PX.get(ft, DEFAULT_FIELD_PX) for ft in fields)
        gaps = (len(fields) + 1) * 16
        if c.get('cardHeader'):
            heading_px = 38 + 25 + (15 if c.get('headerEyebrow') else 0) + (26 if c.get('headerSubtitle') else 0) + 20
        else:
            heading_px = 30
        submit_px = 46 + 16 + (17 if c.get('helperText') else 34)
        return (heading_px + per_field + submit_px + 8 + gaps) * FORM_SAFETY
    if t == 'feature_grid':
        items = c.get('items') or []
        card_style = c.get('cardStyle') or 'card'
        fn, per_col = FEATURE_FNS.get(card_style, FEATURE_FNS['card'])
        cols = max(1, int((col_width_px + 16) // per_col))
        card_w = (col_width_px - (cols - 1) * 16) / cols
        heights = [fn(it, card_w) for it in items] or [100]
        rows = [heights[i:i + cols] for i in range(0, len(heights), cols)]
        heading_px = 34 if c.get('heading') else 0
        return (heading_px + sum(max(r) for r in rows) + (len(rows) - 1) * 16) * SAFETY
    if t == 'testimonial_grid':
        items = c.get('items') or []
        if c.get('cardStyle') == 'quote':
            heading_px = 34 if c.get('heading') else 0
            total = 0
            for it in items:
                quote = it.get('quote') or ''
                cpl = max(8, min(col_width_px, 640) / (24 * 0.5))
                total += max(1, math.ceil(len(quote) / cpl)) * 34 + 60
            return (heading_px + total) * SAFETY
        cols = max(1, int((col_width_px + 16) // 256))
        card_w = (col_width_px - (cols - 1) * 16) / cols
        heights = [_testimonial_card_height_px(it, card_w) for it in items] or [100]
        rows = [heights[i:i + cols] for i in range(0, len(heights), cols)]
        heading_px = 34 if c.get('heading') else 0
        return (heading_px + sum(max(r) for r in rows) + (len(rows) - 1) * 16) * SAFETY
    if t == 'service_list':
        items = c.get('items') or []
        heading_px = 34 if c.get('heading') else 0
        total = sum(_service_card_height_px(it, col_width_px) for it in items)
        total += (len(items) - 1) * 20 if items else 0
        return (heading_px + total) * SAFETY
    if t == 'faq_accordion':
        items = c.get('items') or []
        heading_px = 34 if c.get('heading') else 0
        return heading_px + len(items) * 54
    return c.get('_h_px', 120)


def blk(block_id, block_type, x, w, content, y=0):
    """One terse constructor for every block type used authoring
    templates -- a block only needs id/type/x/w/content here; y is just
    a hint for button-row grouping (see compile_section) and is
    discarded/recomputed otherwise."""
    return {'id': block_id, 'type': block_type, 'x': x, 'w': w, 'y': y, 'content': content}


def heading(block_id, x, w, text, size=30, color=None, align='left'):
    c = {'text': text, 'fontSize': size, 'align': align, 'heading': True}
    if color:
        c['color'] = color
    return blk(block_id, 'text', x, w, c)


def eyebrow(block_id, x, w, text, size=13, color=None, align='left'):
    c = {'text': text, 'fontSize': size, 'align': align, 'eyebrow': True}
    if color:
        c['color'] = color
    return blk(block_id, 'text', x, w, c)


def para(block_id, x, w, text, size=16, color=None, align='left'):
    c = {'text': text, 'fontSize': size, 'align': align}
    if color:
        c['color'] = color
    return blk(block_id, 'text', x, w, c)


def btn(block_id, x, w, text, href='', y=0, style=None):
    c = {'text': text, 'href': href}
    if style:
        c['buttonStyle'] = style
    return blk(block_id, 'button', x, w, c, y=y)


def img(block_id, x, w, alt='', h_px=220):
    return blk(block_id, 'image', x, w, {'src': None, 'alt': alt, '_h_px': h_px})


def gallery(block_id, x, w, n_images=4):
    return blk(block_id, 'gallery', x, w, {'images': [None] * n_images})


def contact_form(block_id, x, w, heading_text='Get in touch', style=None, h_px=280):
    c = {'heading': heading_text, '_h_px': h_px}
    if style:
        c['formStyle'] = style
    return blk(block_id, 'form', x, w, c)


def map_block(block_id, x, w, address=''):
    return blk(block_id, 'map', x, w, {'address': address})


def feature_grid(block_id, x, w, items, heading_text='', card_style='card'):
    return blk(block_id, 'feature_grid', x, w, {'heading': heading_text, 'cardStyle': card_style, 'items': items})


def service_list(block_id, x, w, items, heading_text='', numbered=True):
    return blk(block_id, 'service_list', x, w, {'heading': heading_text, 'numbered': numbered, 'items': items})


def testimonial_grid(block_id, x, w, items, heading_text='', card_style='card'):
    return blk(block_id, 'testimonial_grid', x, w, {'heading': heading_text, 'cardStyle': card_style, 'items': items})


def faq_accordion(block_id, x, w, items, heading_text=''):
    return blk(block_id, 'faq_accordion', x, w, {'heading': heading_text, 'items': items})


def callout(block_id, x, w, heading_text, text, color_scheme='blue', icon='Info'):
    return blk(block_id, 'callout', x, w, {'icon': icon, 'heading': heading_text, 'text': text, 'colorScheme': color_scheme})


def logo_strip(block_id, x, w, names, heading_text='', grayscale=True):
    return blk(block_id, 'logo_strip', x, w, {
        'heading': heading_text, 'grayscale': grayscale,
        'items': [{'src': None, 'alt': n, 'href': ''} for n in names],
    })


def google_badge(block_id, x, w):
    return blk(block_id, 'google_reviews_badge', x, w, {'rating': None, 'reviewCount': None, 'url': ''})


def compile_section(section_id, blocks, bg=None, dark_bg=False, padding=48):
    """blocks: a list of dicts, each a normal block dict (id/type/content)
    PLUS 'x' and 'w' (percent-of-section, as always) -- 'y'/'h' are
    ignored if present and recomputed here. Blocks sharing an x-bucket
    (rounded to the nearest 8%) stack as one column; two buttons sharing
    nearly the same original 'y' (if given) are aligned side by side as a
    row -- same reflow algorithm used to fix Altmax/KTY's real layouts,
    now the one and only way a template's sections get built, so a
    template can never ship with the overlap bugs those needed several
    live-testing rounds to catch by hand.
    `bg`: a hex color, or None for transparent/inherit. `dark_bg`: pass
    True to also set content.dark=True on every feature_grid/
    testimonial_grid/service_list/faq_accordion/logo_strip block in this
    section (see ContentBlocks.js's DarkBackgroundToggle) -- otherwise
    their text renders in light-page colors against a dark background.
    """
    DARK_AWARE_TYPES = {'feature_grid', 'testimonial_grid', 'service_list', 'faq_accordion', 'logo_strip'}
    prepared = []
    for b in blocks:
        b = dict(b)
        b['content'] = dict(b.get('content') or {})
        if dark_bg and b['type'] in DARK_AWARE_TYPES:
            b['content']['dark'] = True
        b.setdefault('y', 0)
        b.setdefault('z', 0)
        b.setdefault('mobileLayout', None)
        prepared.append(b)

    bands = []
    open_by_x = {}
    for b in sorted(prepared, key=lambda b: (round(b.get('y', 0)), b['x'])):
        if b['w'] >= 85:
            open_by_x.clear()
            bands.append({'full': True, 'blocks': [b]})
            continue
        x_key = round(b['x'] / 8)
        band = open_by_x.get(x_key)
        if band is None:
            band = {'full': False, 'blocks': []}
            open_by_x[x_key] = band
            bands.append(band)
        band['blocks'].append(b)

    cursor_y_px = 0
    max_bottom_px = 0
    out_blocks = []
    pending_columns = []

    def flush_columns():
        nonlocal cursor_y_px, max_bottom_px, pending_columns
        if not pending_columns:
            return
        tallest = 0
        for band in pending_columns:
            y_px = cursor_y_px
            for b in band['blocks']:
                h_px = estimate_block_height_px(b, b['w'])
                out_blocks.append([b, b['x'], y_px, b['w'], h_px])
                y_px += h_px + 14
            tallest = max(tallest, y_px)
        cursor_y_px = tallest
        max_bottom_px = max(max_bottom_px, tallest)
        pending_columns = []

    for band in bands:
        if band['full']:
            flush_columns()
            b = band['blocks'][0]
            h_px = estimate_block_height_px(b, b['w'])
            out_blocks.append([b, b['x'], cursor_y_px, b['w'], h_px])
            cursor_y_px += h_px + 14
            max_bottom_px = max(max_bottom_px, cursor_y_px)
        else:
            pending_columns.append(band)
    flush_columns()

    # Button-row alignment -- two buttons authored at nearly the same y
    # (within 3 units) snap to the deeper of their two independently
    # computed positions, so a lone button (nothing stacked above it in
    # its own column) aligns with its sibling instead of floating to the
    # top of its column. See this session's own Altmax fix for why this
    # has to be a separate pass, not folded into the column stacking above.
    button_entries = [e for e in out_blocks if e[0]['type'] == 'button']
    used = set()
    for i, e in enumerate(button_entries):
        if id(e[0]) in used:
            continue
        group = [e]
        used.add(id(e[0]))
        for e2 in button_entries[i + 1:]:
            if id(e2[0]) not in used and abs(e2[0].get('y', 0) - e[0].get('y', 0)) < 3:
                group.append(e2)
                used.add(id(e2[0]))
        if len(group) > 1:
            target_y = max(g[2] for g in group)
            for g in group:
                g[2] = target_y

    total_height_px = max(MIN_SECTION_HEIGHT, max_bottom_px + BOTTOM_MARGIN_PX)

    new_blocks = []
    for b, x, y_px, w, h_px in out_blocks:
        new_blocks.append({
            **b,
            'x': round(x, 1), 'w': round(w, 1),
            'y': round((y_px / total_height_px) * 100, 2),
            'h': round((h_px / total_height_px) * 100, 2),
        })
    background = {'type': 'color', 'value': bg} if bg else {'type': 'color', 'value': 'transparent'}
    return {
        'id': section_id, 'background': background,
        'padding': {'top': padding, 'bottom': padding},
        'height': round(total_height_px), 'blocks': new_blocks,
    }
