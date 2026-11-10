from config import db
from datetime import datetime

from backend.business.modals.business import slugify

# Every module below gates one "section" of the owner's own website. A
# module being off doesn't delete anything it controls -- it just hides
# the corresponding owner-dashboard tab and refuses the corresponding
# public routes (404, not a partial/broken page) -- so turning it back on
# later picks up right where the owner left off. New future bolt-ons
# (analytics widget, promo sync) are added here as one more key, not a
# schema change -- that's the whole point of gating this way rather than
# one-column-per-feature.
MODULE_REGISTRY = {
    'pages':            {'label': 'Pages',            'default_enabled': True},
    'products':         {'label': 'Products',         'default_enabled': False},
    'bookings':         {'label': 'Bookings',         'default_enabled': False},
    'crm':              {'label': 'Customers',        'default_enabled': True},
    'invoices':         {'label': 'Invoices',         'default_enabled': True},
    'analytics_widget': {'label': 'Analytics widget', 'default_enabled': False},
    # Donations/memberships/holiday-seat sales/dynamic forms/a separate
    # staff login -- a full port of a real synagogue's back-office system
    # (see backend/business/modals/nonprofit.py). Off by default: this is
    # a fundamentally different kind of site than the storefront/booking
    # modules above (no products/orders), so it should never silently
    # appear for a business that's actually a regular storefront.
    'nonprofit':        {'label': 'Nonprofit / Donations', 'default_enabled': False},
    # The nonprofit module's dynamic form builder (conditional fields,
    # choice/date/name-date-list types, response export), generalized to
    # any business -- see routes/site_forms.py's own docstring. A
    # nonprofit business doesn't need to separately turn this on too (its
    # 'nonprofit' module already includes forms); this is for every OTHER
    # business that just wants a custom intake/proposal/application form
    # without the rest of the nonprofit back-office.
    'custom_forms':     {'label': 'Custom Forms',       'default_enabled': False},
}

DEFAULT_ENABLED_MODULES = {key: cfg['default_enabled'] for key, cfg in MODULE_REGISTRY.items()}

SITE_STATUSES = ('draft', 'published')
CUSTOM_DOMAIN_STATUSES = ('pending', 'verified')

# The content-block schema every page's SitePageVersion.sections will be
# validated against once the page builder (Phase 2) lands. Locked here,
# ahead of the canvas itself, since the canvas, the public renderer, and
# the server-side draft-save validator all need to agree on this shape
# before any of them can be built. A block's x/y/w/h are percentages of
# its OWN section's box, not the page -- sections always stack full-width
# top to bottom, so only the inside of a section is freeform. mobileLayout
# is an optional per-block override; when absent, the public renderer
# auto-stacks blocks within a section by (y, then x) on narrow viewports,
# which is what keeps "full drag-and-drop" from becoming the classic
# Wix absolute-position-everywhere mobile breakage.
BLOCK_TYPES = (
    'text', 'image', 'button', 'spacer', 'form', 'map', 'gallery',
    'product_grid', 'product_detail', 'booking_widget', 'analytics_widget',
    # Nonprofit module -- embeds the actual donate/membership/holiday-
    # seat/dynamic-form flows directly into a built page, not just a
    # fixed /donate-style route the owner has to separately link to.
    'donation_form', 'membership_form', 'holiday_seats_form', 'dynamic_form', 'family_login_button',
    # Generic, every-site structured-content blocks -- added recreating a
    # real business's existing site (Altmax Property Management) surfaced
    # that a services grid / FAQ accordion / testimonial wall had no block
    # equivalent here at all (only loose text blocks, which lose the
    # repeating-card structure). Not nonprofit-specific -- any business
    # site can use these.
    'faq_accordion', 'feature_grid', 'testimonial_grid',
    # Owner-entered (not live-fetched -- no Google Places API key/billing
    # needed), same "update these once the Business Profile is live"
    # manual convention a real business's own prior site used for this
    # exact feature. Content is just {rating, review_count, url}.
    'google_reviews_badge',
    # Same real business's actual Services page structured each item with
    # an icon, a large 01/02/... index, a paragraph, AND a 2-column list
    # of supporting bullet points -- feature_grid only has one description
    # string per item, so that page's real bullet content had to be
    # flattened into a run-on sentence to fit it. Content is
    # {heading, numbered, items: [{icon, title, description, points[]}]}.
    'service_list',
    # A tinted, bordered notice (e.g. "Building emergency? Call ###") --
    # that same real site's FAQ page has exactly this, and a plain text
    # block has no border/background/icon at all, so it had to render as
    # just colored text with none of the "this is a notice" visual
    # framing. Content is {icon, heading, text, colorScheme, headingSize,
    # textSize}.
    'callout',
    # A row of client logos / press mentions / certification or award
    # badges, each optionally linking out -- surfaced comparing against
    # real marketing and nonprofit sites (a client-logo strip, a Charity
    # Navigator/BBB trust-badge row), which feature_grid can't represent
    # cleanly since every one of its card styles pairs the icon/image with
    # a title underneath. Content is {heading, grayscale, items:
    # [{src, alt, href}]}.
    'logo_strip',
)

# ── Theme (Phase 8) ──────────────────────────────────────────────────────
# BusinessSite.theme is validated against these registries, not an open
# dict -- same Python-level-enum convention as MODULE_REGISTRY/
# BUSINESS_CATEGORIES elsewhere, so a bad frontend build can't silently
# persist a theme key that nothing renders. Colors are the highest-impact
# lever (this is what actually stops every business site looking like a
# copy of Gut Shtick's own orange branding), so that registry is the
# richest; button/form/nav/footer are real variants, just fewer of them --
# "many styles", not "infinite configuration".
THEME_PALETTES = {
    'warm':    {'label': 'Warm',    'primary': '#C8553D', 'secondary': '#E8A87C', 'background': '#FAF3E8', 'surface': '#FFFFFF', 'text': '#2B2118', 'muted': '#8A7A68', 'border': '#E3D5C0'},
    'cool':    {'label': 'Cool',    'primary': '#2E6F95', 'secondary': '#6FA8C9', 'background': '#F4F8FA', 'surface': '#FFFFFF', 'text': '#1B2B33', 'muted': '#5C7A87', 'border': '#D6E4EA'},
    'bold':    {'label': 'Bold',    'primary': '#E63946', 'secondary': '#1D3557', 'background': '#FFFFFF', 'surface': '#F8F9FA', 'text': '#111111', 'muted': '#6C757D', 'border': '#E0E0E0'},
    'minimal': {'label': 'Minimal', 'primary': '#1A1A1A', 'secondary': '#6E6E6E', 'background': '#FFFFFF', 'surface': '#FAFAFA', 'text': '#1A1A1A', 'muted': '#9E9E9E', 'border': '#EAEAEA'},
    'earthy':  {'label': 'Earthy',  'primary': '#4A5D3A', 'secondary': '#8C7851', 'background': '#F5F0E6', 'surface': '#FFFFFF', 'text': '#2D2A22', 'muted': '#7A7260', 'border': '#DCD3BE'},
    'dark':    {'label': 'Dark',    'primary': '#7C9EFF', 'secondary': '#B98CE8', 'background': '#121417', 'surface': '#1C1F24', 'text': '#F0F2F5', 'muted': '#9AA3AE', 'border': '#2C3036'},
    'sunset':  {'label': 'Sunset',  'primary': '#D96C3F', 'secondary': '#F2B872', 'background': '#FFF6ED', 'surface': '#FFFFFF', 'text': '#3A2A1E', 'muted': '#9C7F63', 'border': '#F0DCC4'},
    'forest':  {'label': 'Forest',  'primary': '#2F6B4F', 'secondary': '#8FBF9B', 'background': '#F1F7F2', 'surface': '#FFFFFF', 'text': '#1E2E24', 'muted': '#6E8C78', 'border': '#D7E8DC'},
    'rose':    {'label': 'Rose',    'primary': '#B5456E', 'secondary': '#E8A9C0', 'background': '#FDF2F6', 'surface': '#FFFFFF', 'text': '#3A1F2A', 'muted': '#A6748A', 'border': '#F2D9E3'},
    'slate':   {'label': 'Slate',   'primary': '#475569', 'secondary': '#94A3B8', 'background': '#F1F5F9', 'surface': '#FFFFFF', 'text': '#1E293B', 'muted': '#64748B', 'border': '#E2E8F0'},
}

FONT_PAIRINGS = {
    'classic':   {'label': 'Classic',   'heading': "'Playfair Display', Georgia, serif", 'body': "'Lato', Arial, sans-serif", 'google': 'Playfair+Display:wght@700&family=Lato:wght@400;600'},
    'modern':    {'label': 'Modern',    'heading': "'Poppins', Arial, sans-serif", 'body': "'Inter', Arial, sans-serif", 'google': 'Poppins:wght@600;700&family=Inter:wght@400;600'},
    'friendly':  {'label': 'Friendly',  'heading': "'Quicksand', Arial, sans-serif", 'body': "'Nunito', Arial, sans-serif", 'google': 'Quicksand:wght@700&family=Nunito:wght@400;600'},
    'elegant':   {'label': 'Elegant',   'heading': "'Cormorant Garamond', Georgia, serif", 'body': "'Work Sans', Arial, sans-serif", 'google': 'Cormorant+Garamond:wght@700&family=Work+Sans:wght@400;600'},
    'bold':      {'label': 'Bold',      'heading': "'Archivo Black', Arial, sans-serif", 'body': "'Archivo', Arial, sans-serif", 'google': 'Archivo+Black&family=Archivo:wght@400;600'},
    'editorial': {'label': 'Editorial', 'heading': "'Libre Baskerville', Georgia, serif", 'body': "'Source Sans 3', Arial, sans-serif", 'google': 'Libre+Baskerville:wght@700&family=Source+Sans+3:wght@400;600'},
    'rounded':   {'label': 'Rounded',   'heading': "'Baloo 2', Arial, sans-serif", 'body': "'Mulish', Arial, sans-serif", 'google': 'Baloo+2:wght@700&family=Mulish:wght@400;600'},
    'technical': {'label': 'Technical', 'heading': "'Space Grotesk', Arial, sans-serif", 'body': "'IBM Plex Sans', Arial, sans-serif", 'google': 'Space+Grotesk:wght@700&family=IBM+Plex+Sans:wght@400;600'},
}

BUTTON_STYLES = {
    'rounded': {'label': 'Rounded', 'radius': '10px'},
    'pill':    {'label': 'Pill', 'radius': '999px'},
    'square':  {'label': 'Square', 'radius': '2px'},
    'outline': {'label': 'Outline', 'radius': '8px'},
    'ghost':   {'label': 'Ghost', 'radius': '8px'},
    'shadow':  {'label': 'Shadow', 'radius': '10px'},
}

FORM_STYLES = {
    'boxed':     {'label': 'Boxed'},
    'underline': {'label': 'Underline'},
    'soft':      {'label': 'Soft'},
}

NAV_STYLES = {
    'top':     {'label': 'Top bar'},
    'side':    {'label': 'Sidebar'},
    'minimal': {'label': 'Minimal (logo only)'},
    'split':   {'label': 'Split (centered logo)'},
}

FOOTER_STYLES = {
    'simple':  {'label': 'Simple'},
    'columns': {'label': 'Columns'},
    'stacked': {'label': 'Stacked (centered, with links)'},
    'none':    {'label': 'No footer'},
}

DEFAULT_THEME = {
    'palette': 'warm', 'customColors': None, 'fontPairing': 'modern',
    'customFontPairing': None, 'headingColor': None,
    'buttonStyle': 'rounded', 'formStyle': 'boxed', 'navStyle': 'top', 'footerStyle': 'simple',
    'footerDark': False,
}

CUSTOM_COLOR_KEYS = ('primary', 'secondary', 'background', 'surface', 'text', 'muted', 'border')
HEX_COLOR_RE_SOURCE = r'^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$'


def validate_theme(theme):
    """Returns an error string, or None if valid. Partial themes are fine
    (missing keys fall back to DEFAULT_THEME's at render time) -- this
    only rejects a key that's actually present with a bad value, so a
    caller can PATCH just one picker at a time."""
    import re
    if not isinstance(theme, dict):
        return 'theme must be an object'
    if 'palette' in theme and theme['palette'] not in THEME_PALETTES:
        return f"Unknown palette: {theme['palette']!r}"
    if 'fontPairing' in theme and theme['fontPairing'] not in FONT_PAIRINGS:
        return f"Unknown fontPairing: {theme['fontPairing']!r}"
    custom_fonts = theme.get('customFontPairing')
    if custom_fonts is not None:
        if not isinstance(custom_fonts, dict) or not custom_fonts.get('heading') or not custom_fonts.get('body'):
            return 'customFontPairing must be an object with heading and body CSS font-family strings'
        for key in ('heading', 'body', 'google'):
            if key in custom_fonts and custom_fonts[key] is not None and not isinstance(custom_fonts[key], str):
                return f'customFontPairing.{key} must be a string'
    heading_color = theme.get('headingColor')
    if heading_color is not None:
        import re as _re
        if not isinstance(heading_color, str) or not _re.match(HEX_COLOR_RE_SOURCE, heading_color):
            return 'headingColor must be a hex color like #112233'
    if 'buttonStyle' in theme and theme['buttonStyle'] not in BUTTON_STYLES:
        return f"Unknown buttonStyle: {theme['buttonStyle']!r}"
    if 'formStyle' in theme and theme['formStyle'] not in FORM_STYLES:
        return f"Unknown formStyle: {theme['formStyle']!r}"
    if 'navStyle' in theme and theme['navStyle'] not in NAV_STYLES:
        return f"Unknown navStyle: {theme['navStyle']!r}"
    if 'footerStyle' in theme and theme['footerStyle'] not in FOOTER_STYLES:
        return f"Unknown footerStyle: {theme['footerStyle']!r}"
    if 'footerDark' in theme and not isinstance(theme['footerDark'], bool):
        return 'footerDark must be true or false'
    import re as _re2
    for key in ('footerDarkBg', 'footerDarkText'):
        val = theme.get(key)
        if val is not None and not _re2.match(HEX_COLOR_RE_SOURCE, val):
            return f'{key} must be a hex color like #112233'
    if 'navUppercase' in theme and not isinstance(theme['navUppercase'], bool):
        return 'navUppercase must be true or false'
    if 'footerColumns' in theme and theme['footerColumns'] is not None:
        cols = theme['footerColumns']
        if not isinstance(cols, list) or any(not isinstance(c, dict) for c in cols):
            return 'footerColumns must be a list of {heading, links} objects'
    custom = theme.get('customColors')
    if custom is not None:
        if not isinstance(custom, dict):
            return 'customColors must be an object or null'
        hex_re = re.compile(HEX_COLOR_RE_SOURCE)
        for key, value in custom.items():
            if key not in CUSTOM_COLOR_KEYS:
                return f'Unknown customColors key: {key!r}'
            if value is not None and not hex_re.match(value):
                return f'customColors.{key} must be a hex color like #112233'
    return None


class BusinessSite(db.Model):
    __tablename__ = 'business_site'

    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(db.Integer, db.ForeignKey('business.id'), nullable=False, unique=True, index=True)

    subdomain = db.Column(db.String(160), unique=True, nullable=False, index=True)
    status = db.Column(db.String(20), nullable=False, default='draft', server_default='draft', index=True)

    enabled_modules = db.Column(db.JSON, nullable=False, default=dict)
    theme = db.Column(db.JSON, nullable=True)

    # Site-wide chrome (Phase 9) -- configured once, shown on every page,
    # which is what "add something for all pages" means here: a small
    # structured nav/footer content list rather than a second full block-
    # canvas for header/footer regions (that would double the page-builder
    # surface for not much real benefit over this). nav_links/footer_links
    # are each a JSON list of {label, path}; path is either an internal
    # page path ("/", "/about") or an absolute https:// URL.
    nav_links = db.Column(db.JSON, nullable=True)
    footer_text = db.Column(db.String(300), nullable=True)
    footer_links = db.Column(db.JSON, nullable=True)

    # Custom (foreign) domain support. custom_domain is the bare host the
    # owner wants their site to answer on (e.g. "www.shmuelsbakery.com"),
    # entered by the owner and never trusted until ownership is proven --
    # custom_domain_token is a random value the owner must publish as a
    # DNS TXT record, and custom_domain_status only ever flips 'pending' ->
    # 'verified' once that TXT lookup actually matches (see
    # routes/business_site.py's /domain/verify). The public resolver
    # (business_site_public.py's by-domain lookup) only ever honors a
    # 'verified' domain -- an unverified one is exactly as inert as if the
    # column were still NULL, which is what makes it safe to let an owner
    # type in ANY domain here (including one they don't actually own)
    # without that alone granting them anything.
    custom_domain = db.Column(db.String(255), unique=True, nullable=True)
    custom_domain_status = db.Column(db.String(20), nullable=True)
    custom_domain_token = db.Column(db.String(64), nullable=True)

    # Default ON (unlike every module above, which defaults off) -- per
    # explicit user request: a new site's products/active discounts should
    # surface onto the main Gut Community feed (see routes/promo_sync.py)
    # unless the owner opts OUT, not the other way around. Two separate
    # flags, not one, since an owner may want their catalog visible
    # community-wide without also broadcasting every discount they run.
    share_products_with_community = db.Column(db.Boolean, nullable=False, default=True, server_default='true')
    share_deals_with_community = db.Column(db.Boolean, nullable=False, default=True, server_default='true')

    # Browser-tab icon for the public site -- an uploaded image URL (same
    # upload pipeline as everything else uploaded via upload.py), not a
    # generated favicon set. NULL falls back to this platform's own icon.
    favicon_url = db.Column(db.String(500), nullable=True)

    # One-time "finish setting up your site" wizard (domain/Stripe ->
    # Google Calendar -> Green Invoice -> favicon) -- true once the owner
    # has dismissed or finished it. Never reset automatically; the owner can
    # still reopen the same steps anytime from a small entry point in the
    # section tabs, this flag only controls whether it shows unprompted.
    setup_wizard_dismissed = db.Column(db.Boolean, nullable=False, default=False, server_default='false')

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    published_at = db.Column(db.DateTime, nullable=True)

    business = db.relationship('Business', backref=db.backref('site', uselist=False, cascade='all, delete-orphan'))

    def __init__(self, business_id, subdomain, enabled_modules=None, theme=None):
        self.business_id = business_id
        self.subdomain = subdomain
        self.enabled_modules = enabled_modules if enabled_modules is not None else dict(DEFAULT_ENABLED_MODULES)
        self.theme = theme

    def has_module(self, key):
        return bool((self.enabled_modules or {}).get(key))

    def __repr__(self):
        return f'BusinessSite({self.id}) business={self.business_id} subdomain={self.subdomain!r} [{self.status}]'


def default_subdomain_for(business):
    """Best-effort starting subdomain, derived from the business's own slug.
    Uniqueness against other BusinessSite rows is the caller's job (same
    division of responsibility as Business.slug generation elsewhere)."""
    return slugify(business.name) if business else slugify('business')
