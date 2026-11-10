"""Shared by site_template_layout.py (template generation) and
routes/site_pages.py's reset-section-colors action. A section's
background -- and a template-built page's section backgrounds in
particular -- used to be stored as a literal hex chosen to roughly match
whatever palette the template's author had in mind at the time, completely
disconnected from the live theme afterward: a button already reads
`var(--sb-primary)` straight from CSS and updates the moment the owner
picks a different palette, but a section's literal `#0f2a4a` never does,
which is exactly why changing the palette visibly moved the buttons and
nothing else. resolve_bg_var maps a literal hex to the matching `--sb-*`
CSS variable instead, so it keeps tracking the palette like a button does.

Classified by actual luminance, not any dark/light flag the caller may or
may not have passed, since that flag is set inconsistently across the
existing templates (several dark hero sections share one of these dark
literals without it) -- computing it directly from the color itself is
reliable regardless.
"""


def _hex_luminance(hex_color):
    h = (hex_color or '').lstrip('#')
    if len(h) != 6:
        return 1.0
    try:
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    except ValueError:
        return 1.0
    return (0.299 * r + 0.587 * g + 0.114 * b) / 255


# Below this, a literal is treated as a "dark/accent" section background
# (-> primary); at or above it, a "light" one (-> background/surface). The
# two groups found across the existing templates sit at ~0.07-0.46 and
# ~0.93-1.0 respectively -- comfortably far from this line either way.
DARK_LUMINANCE_THRESHOLD = 0.7


def resolve_bg_var(bg):
    """bg: a literal hex string, or None/''/'transparent'. Returns the CSS
    value to actually store -- a `var(--sb-*)` reference for a real color,
    or 'transparent' unchanged. Idempotent: calling this again on an
    already-resolved `var(--sb-primary)` string just returns it as-is."""
    if not bg or bg == 'transparent' or bg.startswith('var('):
        return bg or 'transparent'
    if bg.upper() == '#FFFFFF':
        return 'var(--sb-surface)'
    if _hex_luminance(bg) < DARK_LUMINANCE_THRESHOLD:
        return 'var(--sb-primary)'
    return 'var(--sb-background)'
