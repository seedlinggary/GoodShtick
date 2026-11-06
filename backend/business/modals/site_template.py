from config import db
from datetime import datetime


class SiteTemplate(db.Model):
    """A starting point for a new business site -- a theme + a pre-built
    home page an owner can apply instead of starting from a blank canvas.
    The 5 system defaults (is_system_default=True) are seeded once by a
    migration-adjacent script (see seed_default_templates in this file);
    a SuperAdmin can add more on top via the admin routes, same "defaults
    plus owner-extensible catalog" shape as nothing else in this codebase
    needed before, but conceptually close to how MODULE_REGISTRY/
    BUSINESS_CATEGORIES are Python-level catalogs -- this one just also
    needs to grow at runtime, so it's a real table instead."""
    __tablename__ = 'site_template'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.String(300), nullable=True)
    category = db.Column(db.String(40), nullable=True)
    # Full URL (not a bare filename) -- same convention as Product.images,
    # since this is either a hand-provided URL or resolved once at upload
    # time by whatever admin UI creates the template, never re-resolved here.
    preview_image = db.Column(db.String(500), nullable=True)

    theme = db.Column(db.JSON, nullable=True)
    home_sections = db.Column(db.JSON, nullable=False, default=list)
    nav_links = db.Column(db.JSON, nullable=True)
    footer_text = db.Column(db.String(300), nullable=True)

    is_system_default = db.Column(db.Boolean, nullable=False, default=False, server_default='false')
    active = db.Column(db.Boolean, nullable=False, default=True, server_default='true', index=True)
    position = db.Column(db.Integer, nullable=False, default=0, server_default='0')

    created_by = db.Column(db.String(50), db.ForeignKey('user.public_id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    creator = db.relationship('User', foreign_keys=[created_by])

    def __init__(self, name, home_sections, description=None, category=None, preview_image=None,
                 theme=None, nav_links=None, footer_text=None, is_system_default=False,
                 active=True, position=0, created_by=None):
        self.name = name
        self.home_sections = home_sections
        self.description = description
        self.category = category
        self.preview_image = preview_image
        self.theme = theme
        self.nav_links = nav_links
        self.footer_text = footer_text
        self.is_system_default = is_system_default
        self.active = active
        self.position = position
        self.created_by = created_by

    def __repr__(self):
        return f'SiteTemplate({self.id}) {self.name!r}'


def _text(block_id, x, y, w, h, text, font_size=18, align='left'):
    return {'id': block_id, 'type': 'text', 'x': x, 'y': y, 'w': w, 'h': h,
            'content': {'text': text, 'fontSize': font_size, 'align': align}, 'mobileLayout': None}


def _image(block_id, x, y, w, h, alt=''):
    return {'id': block_id, 'type': 'image', 'x': x, 'y': y, 'w': w, 'h': h,
            'content': {'src': None, 'alt': alt}, 'mobileLayout': None}


def _button(block_id, x, y, w, h, text, href=''):
    return {'id': block_id, 'type': 'button', 'x': x, 'y': y, 'w': w, 'h': h,
            'content': {'text': text, 'href': href}, 'mobileLayout': None}


def _form(block_id, x, y, w, h, heading):
    return {'id': block_id, 'type': 'form', 'x': x, 'y': y, 'w': w, 'h': h,
            'content': {'heading': heading}, 'mobileLayout': None}


def _gallery(block_id, x, y, w, h):
    return {'id': block_id, 'type': 'gallery', 'x': x, 'y': y, 'w': w, 'h': h, 'content': {'images': []}, 'mobileLayout': None}


def _map(block_id, x, y, w, h):
    return {'id': block_id, 'type': 'map', 'x': x, 'y': y, 'w': w, 'h': h, 'content': {'address': ''}, 'mobileLayout': None}


def _product_grid(block_id, x, y, w, h):
    return {'id': block_id, 'type': 'product_grid', 'x': x, 'y': y, 'w': w, 'h': h, 'content': {}, 'mobileLayout': None}


def _booking_widget(block_id, x, y, w, h):
    return {'id': block_id, 'type': 'booking_widget', 'x': x, 'y': y, 'w': w, 'h': h,
            'content': {'serviceTypeId': None, 'serviceName': None}, 'mobileLayout': None}


def _section(section_id, blocks, bg_color='transparent', height=420):
    # height: explicit pixels, not left to CSS min-height -- see
    # good-shtick's src/business/site-builder/sectionDefaults.js for why a
    # section's box needs a real height for its blocks' x/y/w/h percentages
    # to resolve against (420 is that frontend's own default, repeated here
    # so a template looks the same whether or not it ever gets re-saved).
    return {'id': section_id, 'background': {'type': 'color', 'value': bg_color}, 'padding': {'top': 48, 'bottom': 48}, 'height': height, 'blocks': blocks}


DEFAULT_TEMPLATES = [
    {
        'name': 'Simple Storefront', 'category': 'retail',
        'description': 'A clean hero, an about blurb, and your products front and center -- good for shops and food businesses.',
        'theme': {'palette': 'warm', 'fontPairing': 'classic', 'buttonStyle': 'rounded', 'formStyle': 'boxed', 'navStyle': 'top', 'footerStyle': 'simple'},
        'home_sections': [
            _section('hero', [
                _text('hero-title', 10, 15, 80, 20, 'Your Business Name', font_size=36, align='center'),
                _text('hero-sub', 15, 38, 70, 12, 'A short, friendly line about what you offer.', font_size=18, align='center'),
                _button('hero-cta', 40, 55, 20, 10, 'Shop Now', '/cart'),
            ]),
            _section('products', [
                _text('products-title', 10, 2, 80, 10, 'What We Offer', font_size=26, align='center'),
                _product_grid('products-grid', 5, 15, 90, 70),
            ], bg_color='#FFFFFF'),
        ],
        'nav_links': [{'label': 'Shop', 'path': '/cart'}],
        'footer_text': None,
    },
    {
        'name': 'Professional Services', 'category': 'professional_services',
        'description': 'A trust-building layout for consultants, contractors, and service providers -- about, services, and a contact form.',
        'theme': {'palette': 'cool', 'fontPairing': 'modern', 'buttonStyle': 'square', 'formStyle': 'underline', 'navStyle': 'top', 'footerStyle': 'columns'},
        'home_sections': [
            _section('hero', [
                _text('hero-title', 10, 15, 80, 18, 'Expert Help When You Need It', font_size=34, align='center'),
                _text('hero-sub', 15, 36, 70, 14, 'Tell visitors who you help and how, in one honest sentence.', font_size=17, align='center'),
            ]),
            _section('about', [
                _text('about-title', 5, 5, 40, 10, 'About Us', font_size=24),
                _text('about-body', 5, 18, 40, 60, 'A paragraph about your experience, credentials, and what makes your work trustworthy.', font_size=16),
                _image('about-image', 52, 5, 43, 80, alt='Our team'),
            ], bg_color='#FFFFFF'),
            _section('contact', [
                _text('contact-title', 10, 2, 80, 10, "Let's Talk", font_size=24, align='center'),
                _form('contact-form', 25, 15, 50, 75, "Get in touch"),
            ]),
        ],
        'nav_links': [{'label': 'About', 'path': '/about'}, {'label': 'Contact', 'path': '/contact'}],
        'footer_text': None,
    },
    {
        'name': 'Restaurant & Food', 'category': 'restaurant',
        'description': 'A warm, appetizing layout with photos front and center, plus a map so people can find you.',
        'theme': {'palette': 'earthy', 'fontPairing': 'elegant', 'buttonStyle': 'pill', 'formStyle': 'soft', 'navStyle': 'top', 'footerStyle': 'simple'},
        'home_sections': [
            _section('hero', [
                _image('hero-image', 0, 0, 100, 60, alt='Food photo'),
                _text('hero-title', 10, 65, 80, 15, 'Delicious, Made Fresh Daily', font_size=32, align='center'),
            ]),
            _section('gallery', [
                _text('gallery-title', 10, 2, 80, 10, 'A Taste of What We Make', font_size=24, align='center'),
                _gallery('gallery-grid', 5, 15, 90, 70),
            ], bg_color='#FFFFFF'),
            _section('visit', [
                _text('visit-title', 5, 5, 40, 10, 'Visit Us', font_size=24),
                _text('visit-hours', 5, 18, 40, 30, 'Add your hours and a line about reservations or walk-ins here.', font_size=16),
                _map('visit-map', 52, 5, 43, 80),
            ]),
        ],
        'nav_links': [{'label': 'Menu', 'path': '/menu'}],
        'footer_text': None,
    },
    {
        'name': 'Booking & Appointments', 'category': 'health_beauty',
        'description': 'Built around letting people book you directly -- a hero, your services, and the booking widget.',
        'theme': {'palette': 'bold', 'fontPairing': 'modern', 'buttonStyle': 'rounded', 'formStyle': 'boxed', 'navStyle': 'top', 'footerStyle': 'simple'},
        'home_sections': [
            _section('hero', [
                _text('hero-title', 10, 15, 80, 20, 'Book Your Appointment', font_size=34, align='center'),
                _text('hero-sub', 15, 38, 70, 12, 'Pick a time that works for you -- confirmed instantly.', font_size=17, align='center'),
            ]),
            _section('booking', [
                _booking_widget('booking-widget', 10, 5, 80, 85),
            ], bg_color='#FFFFFF'),
        ],
        'nav_links': [],
        'footer_text': None,
    },
    {
        'name': 'Minimal Portfolio', 'category': 'other',
        'description': 'A quiet, image-forward layout for showing off work -- gallery, a short bio, and a way to reach you.',
        'theme': {'palette': 'minimal', 'fontPairing': 'friendly', 'buttonStyle': 'outline', 'formStyle': 'underline', 'navStyle': 'minimal', 'footerStyle': 'simple'},
        'home_sections': [
            _section('intro', [
                _text('intro-title', 10, 30, 80, 15, 'Your Name', font_size=36, align='center'),
                _text('intro-sub', 20, 50, 60, 10, 'A one-line description of what you do.', font_size=16, align='center'),
            ]),
            _section('work', [
                _gallery('work-gallery', 5, 5, 90, 90),
            ], bg_color='#FAFAFA'),
            _section('contact', [
                _form('contact-form', 25, 10, 50, 80, 'Say hello'),
            ]),
        ],
        'nav_links': [],
        'footer_text': None,
    },
]


def seed_default_templates():
    """Idempotent -- safe to call on every deploy. Only ever inserts a
    missing default by name; never overwrites one a SuperAdmin has since
    edited (that would silently discard their changes), matching this
    migration chain's own "guarded, re-runnable" convention."""
    existing_names = {t.name for t in SiteTemplate.query.filter_by(is_system_default=True).all()}
    created = 0
    for position, tpl in enumerate(DEFAULT_TEMPLATES):
        if tpl['name'] in existing_names:
            continue
        db.session.add(SiteTemplate(
            name=tpl['name'], description=tpl['description'], category=tpl['category'],
            theme=tpl['theme'], home_sections=tpl['home_sections'],
            nav_links=tpl['nav_links'], footer_text=tpl['footer_text'],
            is_system_default=True, position=position,
        ))
        created += 1
    if created:
        db.session.commit()
    return created
