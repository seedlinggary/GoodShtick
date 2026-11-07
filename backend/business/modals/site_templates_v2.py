# 10 new starter templates (on top of the original 5 in site_template.py),
# each a genuinely complete site -- Home/About/Services/Contact, not just
# a home page -- built with the full block catalog this session added
# (feature_grid's 5 cardStyle variants, service_list, testimonial pull-
# quotes, callout, logo_strip, gradient section backgrounds, custom font
# pairings) instead of the plain text/image/button/form the original 5
# were limited to. Positions are computed by site_template_layout.py's
# compile_section(), never hand-typed, so none of these can ship with the
# overlap/scrollbar bugs recreating two real businesses' sites this same
# session needed multiple live-testing rounds to catch by hand.
#
# Every page's copy uses {{business_name}}/{{business_category}} tokens
# (substituted for the real business's data when applied -- see
# routes/site_templates.py's _apply_tokens_to_sections) instead of a
# generic "Your Business Name" placeholder, so a template reads as
# written FOR the business applying it, not as a fill-in-the-blank form.
#
# Color palette is intentionally the ONLY thing that's expected to
# change without touching layout (per the request this was built for):
# every block's text relies on the theme's own color tokens (heading
# color, muted, primary) rather than a hardcoded hex, EXCEPT text sitting
# directly on a dark hero/CTA section background, which needs an
# explicit light color regardless of palette (content.dark=True on the
# content blocks that support it; plain text blocks get an explicit
# color since they have no such flag) -- switching palettes keeps every
# light-section heading/body color correct and every dark-section
# white-on-dark pairing correct, in both directions.
from backend.business.modals.site_template_layout import (
    compile_section, heading, eyebrow, para, btn, img, gallery, contact_form, map_block,
    feature_grid, service_list, testimonial_grid, faq_accordion, callout, logo_strip, google_badge,
)

NAME = '{{business_name}}'
CATEGORY = '{{business_category}}'


def _standard_nav():
    return [
        {'label': 'Home', 'path': '/'},
        {'label': 'About', 'path': '/about'},
        {'label': 'Services', 'path': '/services'},
        {'label': 'Contact', 'path': '/contact'},
    ]


def _page(slug, title, sections):
    return {'slug': slug, 'title': title, 'sections': sections}


# ──────────────────────────────────────────────────────────────────────
# 1. Modern Professional -- consultants, agencies, B2B services
# ──────────────────────────────────────────────────────────────────────
def modern_professional():
    theme = {
        'palette': 'cool', 'fontPairing': 'modern', 'buttonStyle': 'rounded', 'formStyle': 'boxed',
        'navStyle': 'top', 'navUppercase': True, 'footerStyle': 'columns', 'footerDark': True,
    }
    home = [
        compile_section('hero', [
            eyebrow('h-eyebrow', 4, 60, 'TRUSTED BY TEAMS LIKE YOURS'),
            heading('h-title', 4, 60, f'{NAME} helps you get it right the first time.', size=40, color='#ffffff'),
            para('h-sub', 4, 54, f'Straightforward {CATEGORY} work, no jargon, no surprises on the invoice.', size=17, color='#e3edf7'),
            btn('h-cta1', 4, 24, 'Get a Proposal', '/contact', y=50),
            btn('h-cta2', 30, 22, 'See Our Work', '/services', y=50),
        ], bg='#0f2a4a'),
        compile_section('stats', [
            feature_grid('h-stats', 4, 92, [
                {'title': '10+', 'description': 'Years in Business'},
                {'title': '200+', 'description': 'Projects Delivered'},
                {'title': '98%', 'description': 'Client Satisfaction'},
                {'title': '24/7', 'description': 'Support Available'},
            ], card_style='stat'),
        ], bg='#F4F8FA'),
        compile_section('why', [
            eyebrow('h-why-eyebrow', 4, 50, 'WHY CLIENTS CHOOSE US'),
            heading('h-why-title', 4, 70, 'We treat your business like our own.', size=28),
            feature_grid('h-why-grid', 4, 92, [
                {'icon': 'HeartHandshake', 'title': 'Honest & Direct', 'description': "We'll tell you what you need to hear, not just what's easy to say."},
                {'icon': 'Zap', 'title': 'Fast Response', 'description': 'Real people answer, usually within the hour.'},
                {'icon': 'Award', 'title': 'Proven Results', 'description': 'A track record you can check -- just ask for references.'},
                {'icon': 'Calculator', 'title': 'Transparent Pricing', 'description': 'You know the cost before we start, every time.'},
            ], card_style='row'),
        ], bg='#FFFFFF'),
        compile_section('services-preview', [
            eyebrow('h-svc-eyebrow', 4, 50, 'WHAT WE DO'),
            heading('h-svc-title', 4, 70, 'Full-service support, start to finish.', size=28),
            para('h-svc-sub', 4, 70, f'Whatever stage your {CATEGORY} needs are at, we meet you there.', size=15),
            feature_grid('h-svc-grid', 4, 92, [
                {'icon': 'Building2', 'title': 'Planning & Strategy', 'description': 'A clear plan before any work begins.'},
                {'icon': 'Wrench', 'title': 'Hands-On Delivery', 'description': 'We do the work, not just advise on it.'},
                {'icon': 'LineChart', 'title': 'Reporting', 'description': 'Know exactly where things stand, always.'},
                {'icon': 'ShieldCheck', 'title': 'Ongoing Support', 'description': "We don't disappear after the invoice."},
            ]),
            btn('h-svc-cta', 4, 24, 'View All Services', '/services', y=90),
        ], bg='#F4F8FA'),
        compile_section('testimonial', [
            testimonial_grid('h-quote', 4, 92, [
                {'quote': f'{NAME} made a complicated process feel simple. We knew what was happening every step of the way.', 'author': 'A Recent Client', 'role': 'Business Owner'},
            ], card_style='quote'),
        ], bg='#FFFFFF'),
        compile_section('cta', [
            heading('h-cta-title', 4, 55, 'Ready to get started?', size=28, color='#ffffff'),
            para('h-cta-sub', 4, 55, "Tell us what you need -- we'll follow up within one business day.", size=15, color='#e3edf7'),
            btn('h-cta-btn', 65, 28, 'Get a Proposal', '/contact', y=20),
        ], bg='#0f2a4a', dark_bg=True),
    ]
    about = [
        compile_section('a-hero', [
            eyebrow('a-eyebrow', 4, 60, 'ABOUT US'),
            heading('a-title', 4, 80, f'The team behind {NAME}.', size=36, color='#ffffff'),
            para('a-sub', 4, 60, f'We started {NAME} because we were tired of seeing {CATEGORY} done halfway. So we do it right.', size=16, color='#e3edf7'),
        ], bg='#0f2a4a'),
        compile_section('a-story', [
            heading('a-story-title', 4, 45, 'Our Story', size=26),
            para('a-story-p', 4, 45, f'{NAME} was built on a simple idea: clients deserve straight answers and real accountability. Every project gets a dedicated point of contact -- not a rotating cast of strangers -- and a plan built around your actual situation, not a one-size-fits-all template.', size=15),
            feature_grid('a-values', 52, 44, [
                {'icon': 'HeartHandshake', 'title': 'Integrity First', 'description': "We'd rather lose a sale than oversell you."},
                {'icon': 'Users', 'title': 'Real Relationships', 'description': "You'll work with the same people every time."},
                {'icon': 'TrendingUp', 'title': 'Always Improving', 'description': 'We invest in getting better at this every year.'},
            ], card_style='row'),
        ], bg='#FFFFFF'),
        compile_section('a-cta', [
            heading('a-cta-title', 4, 55, f'Curious what {NAME} could do for you?', size=26, color='#ffffff'),
            para('a-cta-sub', 4, 55, "We'll follow up within one business day.", size=14, color='#e3edf7'),
            btn('a-cta-btn', 65, 28, 'Get in Touch', '/contact', y=20),
        ], bg='#0f2a4a', dark_bg=True),
    ]
    services = [
        compile_section('s-hero', [
            eyebrow('s-eyebrow', 4, 60, 'OUR SERVICES'),
            heading('s-title', 4, 80, 'Everything you need, under one roof.', size=36, color='#ffffff'),
        ], bg='#0f2a4a'),
        compile_section('s-list', [
            service_list('s-services', 4, 92, [
                {'icon': 'Building2', 'title': 'Planning & Strategy', 'description': f'We start every {CATEGORY} engagement with a real plan, not guesswork, built around your specific goals and budget.', 'points': ['A written plan before any work begins', 'Realistic timelines, set up front', 'Budget clarity from day one', 'Regular check-ins, not just a final report']},
                {'icon': 'Wrench', 'title': 'Hands-On Delivery', 'description': 'We execute the plan ourselves -- not just advise from the sidelines -- so nothing gets lost between strategy and execution.', 'points': ['A dedicated point of contact', 'Milestone updates, not radio silence', 'Vetted, insured partners when we bring in help', 'Problems flagged early, not after the fact']},
                {'icon': 'ShieldCheck', 'title': 'Ongoing Support', 'description': "The relationship doesn't end at delivery. We're here for the long run.", 'points': ['Priority response for existing clients', 'Regular check-ins after launch', 'Clear escalation path if something goes wrong', 'No surprise fees for reasonable support']},
            ]),
        ], bg='#FFFFFF'),
        compile_section('s-cta', [
            heading('s-cta-title', 4, 55, 'Not sure which service you need?', size=26, color='#ffffff'),
            para('s-cta-sub', 4, 55, "Tell us about your situation -- we'll recommend a starting point.", size=14, color='#e3edf7'),
            btn('s-cta-btn', 65, 28, 'Get a Proposal', '/contact', y=20),
        ], bg='#0f2a4a', dark_bg=True),
    ]
    contact = [
        compile_section('c-hero', [
            eyebrow('c-eyebrow', 4, 60, 'GET IN TOUCH'),
            heading('c-title', 4, 80, "Let's talk about your project.", size=36, color='#ffffff'),
            para('c-sub', 4, 60, "We'll follow up within one business day.", size=16, color='#e3edf7'),
        ], bg='#0f2a4a'),
        compile_section('c-form', [
            heading('c-info-title', 4, 44, 'Contact Information', size=22),
            feature_grid('c-info', 4, 44, [
                {'icon': 'MapPin', 'title': 'Address', 'description': 'Add your address in the site editor.'},
                {'icon': 'Phone', 'title': 'Phone', 'description': 'Add your phone number in the site editor.'},
                {'icon': 'Mail', 'title': 'Email', 'description': 'Add your email in the site editor.'},
            ], card_style='row'),
            google_badge('c-google', 4, 40),
            heading('c-form-title', 52, 44, 'Send a Message', size=22),
            contact_form('c-contact-form', 52, 44, 'Send a Message', style='boxed'),
        ], bg='#FFFFFF'),
    ]
    return {
        'name': 'Modern Professional', 'category': 'professional_services',
        'description': 'A trust-building layout for consultants, agencies, and B2B services -- stats, a services breakdown, and a clear path to contact.',
        'theme': theme, 'nav_links': _standard_nav(), 'footer_text': f'© {NAME}. All rights reserved.',
        'home_sections': home,
        'extra_pages': [_page('about', 'About', about), _page('services', 'Services', services), _page('contact', 'Contact', contact)],
    }


# ──────────────────────────────────────────────────────────────────────
# 2. Elegant Hospitality -- restaurants, cafes, boutique hotels, venues
# ──────────────────────────────────────────────────────────────────────
def elegant_hospitality():
    theme = {
        'palette': 'earthy', 'fontPairing': 'elegant', 'buttonStyle': 'pill', 'formStyle': 'soft',
        'navStyle': 'split', 'footerStyle': 'stacked',
    }
    home = [
        compile_section('hero', [
            eyebrow('h-eyebrow', 10, 80, 'WELCOME TO', align='center'),
            heading('h-title', 10, 80, NAME, size=42, color='#2D2A22', align='center'),
            para('h-sub', 20, 60, f'A warm, welcoming {CATEGORY} experience, made with care.', size=17, align='center'),
            btn('h-cta1', 38, 24, 'Reserve a Table', '/contact', y=45),
        ], bg='#F5F0E6'),
        compile_section('gallery', [
            eyebrow('h-g-eyebrow', 10, 80, 'A LOOK INSIDE', align='center'),
            gallery('h-gallery', 4, 92, n_images=6),
        ], bg='#FFFFFF'),
        compile_section('highlights', [
            eyebrow('h-hi-eyebrow', 4, 60, 'WHAT MAKES US DIFFERENT'),
            heading('h-hi-title', 4, 70, 'Made with care, every time.', size=28),
            feature_grid('h-hi-grid', 4, 92, [
                {'icon': 'Leaf', 'title': 'Fresh Ingredients', 'description': 'Sourced thoughtfully, prepared daily.'},
                {'icon': 'HeartHandshake', 'title': 'Warm Hospitality', 'description': "You're a guest here, not a transaction."},
                {'icon': 'Award', 'title': 'A Local Favorite', 'description': 'Trusted by the community for years.'},
            ], card_style='panel'),
        ], bg='#F5F0E6'),
        compile_section('testimonial', [
            testimonial_grid('h-quote', 4, 92, [
                {'quote': f'{NAME} feels like a second home. Every visit is a little different, always wonderful.', 'author': 'A Loyal Regular'},
            ], card_style='quote'),
        ], bg='#FFFFFF'),
        compile_section('visit', [
            heading('h-visit-title', 4, 45, 'Visit Us', size=26),
            para('h-visit-hours', 4, 45, 'Add your hours and a line about reservations or walk-ins in the site editor.', size=15),
            btn('h-visit-cta', 4, 24, 'Get Directions', '/contact', y=60),
            map_block('h-visit-map', 52, 44),
        ], bg='#F5F0E6'),
    ]
    about = [
        compile_section('a-hero', [
            eyebrow('a-eyebrow', 10, 80, 'OUR STORY', align='center'),
            heading('a-title', 10, 80, f'The story behind {NAME}.', size=36, align='center'),
        ], bg='#F5F0E6'),
        compile_section('a-story', [
            para('a-story-p', 15, 70, f'{NAME} started with a simple goal: create a place people genuinely want to come back to. Every detail, from what we serve to how we welcome you, comes from that same idea.', size=16, align='center'),
        ], bg='#FFFFFF'),
        compile_section('a-values', [
            feature_grid('a-values-grid', 4, 92, [
                {'icon': 'Leaf', 'title': 'Quality First', 'description': 'We never cut corners on what matters most.'},
                {'icon': 'Users', 'title': 'Community Roots', 'description': "We're part of this neighborhood, not just in it."},
                {'icon': 'Sparkles', 'title': 'Always Evolving', 'description': "We're never quite finished improving."},
            ], card_style='panel'),
        ], bg='#F5F0E6'),
    ]
    services = [
        compile_section('s-hero', [
            eyebrow('s-eyebrow', 10, 80, 'WHAT WE OFFER', align='center'),
            heading('s-title', 10, 80, f'A taste of what {NAME} does best.', size=36, align='center'),
        ], bg='#F5F0E6'),
        compile_section('s-grid', [
            feature_grid('s-items', 4, 92, [
                {'icon': 'Leaf', 'title': 'Seasonal Menu', 'description': 'Updated regularly to make the most of what\'s fresh.'},
                {'icon': 'Users', 'title': 'Private Events', 'description': 'Celebrations, gatherings, and everything in between.'},
                {'icon': 'Truck', 'title': 'Catering', 'description': 'Bring the experience to your own event.'},
                {'icon': 'HeartHandshake', 'title': 'Gift Cards', 'description': 'Share the experience with someone else.'},
            ]),
        ], bg='#FFFFFF'),
        compile_section('s-cta', [
            heading('s-cta-title', 10, 80, 'Ready to join us?', size=28, align='center'),
            btn('s-cta-btn', 40, 20, 'Reserve a Table', '/contact', y=45),
        ], bg='#F5F0E6'),
    ]
    contact = [
        compile_section('c-hero', [
            eyebrow('c-eyebrow', 10, 80, 'GET IN TOUCH', align='center'),
            heading('c-title', 10, 80, 'Reserve Your Table', size=36, align='center'),
        ], bg='#F5F0E6'),
        compile_section('c-body', [
            heading('c-info-title', 4, 44, 'Find Us', size=22),
            para('c-info-body', 4, 44, 'Add your address, phone, and hours in the site editor.', size=15),
            map_block('c-map', 4, 44),
            heading('c-form-title', 52, 44, 'Send a Message', size=22),
            contact_form('c-contact-form', 52, 44, 'Send a Message', style='soft'),
        ], bg='#FFFFFF'),
    ]
    return {
        'name': 'Elegant Hospitality', 'category': 'restaurant',
        'description': 'A warm, photo-forward layout for restaurants, cafes, and venues -- gallery, hours and location, and an easy way to reserve.',
        'theme': theme, 'nav_links': _standard_nav(), 'footer_text': f'© {NAME}. All rights reserved.',
        'home_sections': home,
        'extra_pages': [_page('about', 'About', about), _page('services', 'Services', services), _page('contact', 'Contact', contact)],
    }


# ──────────────────────────────────────────────────────────────────────
# 3. Bold Creative Studio -- design, marketing, branding agencies
# ──────────────────────────────────────────────────────────────────────
def bold_creative_studio():
    theme = {
        'palette': 'bold', 'fontPairing': 'bold', 'buttonStyle': 'square', 'formStyle': 'underline',
        'navStyle': 'top', 'navUppercase': True, 'footerStyle': 'columns', 'footerDark': True,
        'footerDarkBg': '#111111', 'footerDarkText': '#CCCCCC',
    }
    home = [
        compile_section('hero', [
            heading('h-title', 4, 92, f'{NAME} makes bold work that gets noticed.', size=46, align='left'),
            para('h-sub', 4, 60, f'We help brands stand out in a crowded {CATEGORY} market -- no safe, forgettable work.', size=18),
            btn('h-cta1', 4, 26, 'Start a Project', '/contact', y=60),
            btn('h-cta2', 32, 24, 'See Our Work', '/services', y=60, style='outline'),
        ], bg='#FFFFFF'),
        compile_section('clients', [
            logo_strip('h-logos', 4, 92, ['Client One', 'Client Two', 'Client Three', 'Client Four', 'Client Five'], heading_text='TRUSTED BY'),
        ], bg='#F8F9FA'),
        compile_section('stats', [
            feature_grid('h-stats', 4, 92, [
                {'title': '150+', 'description': 'Brands Launched'},
                {'title': '12', 'description': 'Industry Awards'},
                {'title': '9', 'description': 'Years Making Noise'},
            ], card_style='stat'),
        ], bg='#111111', dark_bg=True),
        compile_section('services-preview', [
            eyebrow('h-svc-eyebrow', 4, 60, 'WHAT WE MAKE'),
            heading('h-svc-title', 4, 70, 'Work that works.', size=30),
            feature_grid('h-svc-grid', 4, 92, [
                {'icon': 'Sparkles', 'title': 'Brand Identity', 'description': 'A look and voice people actually remember.'},
                {'icon': 'Camera', 'title': 'Content & Photography', 'description': 'Visuals built for how people actually scroll.'},
                {'icon': 'LineChart', 'title': 'Campaigns', 'description': 'Strategy and execution, not just a pretty deck.'},
            ], card_style='row'),
            btn('h-svc-cta', 4, 26, 'See All Services', '/services', y=90),
        ], bg='#FFFFFF'),
        compile_section('testimonial', [
            testimonial_grid('h-quote', 4, 92, [
                {'quote': f'{NAME} understood what we wanted before we could fully explain it.', 'author': 'A Happy Client'},
            ], card_style='quote', ),
        ], bg='#F8F9FA'),
        compile_section('cta', [
            heading('h-cta-title', 4, 92, "Got a project? Let's make it loud.", size=32, align='center'),
            btn('h-cta-btn', 38, 24, 'Start a Project', '/contact', y=70),
        ], bg='#FFFFFF'),
    ]
    about = [
        compile_section('a-hero', [
            heading('a-title', 4, 92, f'This is {NAME}.', size=40),
            para('a-sub', 4, 70, f"We're a small {CATEGORY} studio that doesn't believe in boring work.", size=17),
        ], bg='#FFFFFF'),
        compile_section('a-values', [
            feature_grid('a-values-grid', 4, 92, [
                {'icon': 'Zap', 'title': 'No Safe Choices', 'description': "If it's forgettable, we won't ship it."},
                {'icon': 'Users', 'title': 'Real Collaboration', 'description': "You're in the room, not just the invoice."},
                {'icon': 'Award', 'title': 'Craft Matters', 'description': 'Details other studios skip are where we spend our time.'},
            ], card_style='row'),
        ], bg='#F8F9FA'),
        compile_section('a-cta', [
            heading('a-cta-title', 4, 92, "Let's build something worth talking about.", size=28, align='center'),
            btn('a-cta-btn', 38, 24, 'Get in Touch', '/contact', y=70),
        ], bg='#111111', dark_bg=True),
    ]
    services = [
        compile_section('s-hero', [
            heading('s-title', 4, 92, 'What We Make', size=40),
        ], bg='#FFFFFF'),
        compile_section('s-list', [
            service_list('s-services', 4, 92, [
                {'icon': 'Sparkles', 'title': 'Brand Identity', 'description': 'Logo, color, type, voice -- a complete system built to hold up everywhere your brand shows up.', 'points': ['Full visual identity system', 'Brand guidelines document', 'Voice & messaging framework', 'Launch-ready asset library']},
                {'icon': 'Camera', 'title': 'Content & Photography', 'description': 'Visuals built for how people actually consume content today -- fast, scroll-stopping, on-brand.', 'points': ['Product & lifestyle photography', 'Short-form video content', 'Social-ready templates', 'A content calendar that keeps going after launch']},
                {'icon': 'LineChart', 'title': 'Campaigns', 'description': 'Strategy and execution in one place -- a campaign built to hit a real number, not just look nice.', 'points': ['Audience & channel strategy', 'Creative built for the channel', 'Launch + mid-campaign optimization', 'A real report, not just impressions']},
            ]),
        ], bg='#F8F9FA'),
        compile_section('s-cta', [
            heading('s-cta-title', 4, 92, 'Ready to start?', size=30, align='center'),
            btn('s-cta-btn', 38, 24, 'Start a Project', '/contact', y=70),
        ], bg='#FFFFFF'),
    ]
    contact = [
        compile_section('c-hero', [
            heading('c-title', 4, 92, "Let's talk.", size=40),
            para('c-sub', 4, 60, "Tell us what you're working on -- we'll follow up fast.", size=16),
        ], bg='#FFFFFF'),
        compile_section('c-body', [
            feature_grid('c-info', 4, 44, [
                {'icon': 'MapPin', 'title': 'Studio', 'description': 'Add your address in the site editor.'},
                {'icon': 'Phone', 'title': 'Phone', 'description': 'Add your phone number in the site editor.'},
                {'icon': 'Mail', 'title': 'Email', 'description': 'Add your email in the site editor.'},
            ], card_style='row'),
            contact_form('c-contact-form', 52, 44, 'Send a Message', style='underline'),
        ], bg='#F8F9FA'),
    ]
    return {
        'name': 'Bold Creative Studio', 'category': 'other',
        'description': 'A high-contrast, confident layout for design/branding/marketing studios -- client logos, bold stats, and portfolio-style services.',
        'theme': theme, 'nav_links': _standard_nav(), 'footer_text': f'© {NAME}. All rights reserved.',
        'home_sections': home,
        'extra_pages': [_page('about', 'About', about), _page('services', 'Services', services), _page('contact', 'Contact', contact)],
    }


# ──────────────────────────────────────────────────────────────────────
# 4. Warm Community -- nonprofits, shuls, community organizations
# ──────────────────────────────────────────────────────────────────────
def warm_community():
    theme = {
        'palette': 'warm', 'fontPairing': 'friendly', 'buttonStyle': 'rounded', 'formStyle': 'soft',
        'navStyle': 'top', 'footerStyle': 'columns',
    }
    home = [
        compile_section('hero', [
            eyebrow('h-eyebrow', 4, 60, 'WELCOME HOME'),
            heading('h-title', 4, 80, f'{NAME} is a place to belong.', size=38, color='#ffffff'),
            para('h-sub', 4, 60, f'A warm, welcoming {CATEGORY} community -- everyone is welcome here.', size=16, color='#fdf0e6'),
            btn('h-cta1', 4, 26, 'Get Involved', '/contact', y=50),
            btn('h-cta2', 32, 24, 'Learn More', '/about', y=50, style='outline'),
        ], bg='#C8553D'),
        compile_section('mission', [
            eyebrow('h-m-eyebrow', 4, 50, 'OUR MISSION'),
            heading('h-m-title', 4, 70, 'Building community, one relationship at a time.', size=28),
            feature_grid('h-m-grid', 4, 92, [
                {'icon': 'HeartHandshake', 'title': 'Belonging', 'description': 'A genuine home for everyone who walks through the door.'},
                {'icon': 'Users', 'title': 'Connection', 'description': 'Real relationships, not just events on a calendar.'},
                {'icon': 'Sparkles', 'title': 'Growth', 'description': 'Programs and support that help people thrive.'},
            ], card_style='panel'),
        ], bg='#FAF3E8'),
        compile_section('get-involved', [
            callout('h-callout', 4, 92, 'Want to get involved?', f'There are many ways to support {NAME} -- volunteering, donating, or just showing up. Reach out and we\'ll help you find the right fit.', color_scheme='amber', icon='HeartHandshake'),
        ], bg='#FFFFFF'),
        compile_section('testimonial', [
            testimonial_grid('h-quote', 4, 92, [
                {'quote': f'{NAME} welcomed us from day one. It genuinely feels like family.', 'author': 'A Community Member'},
            ], card_style='quote'),
        ], bg='#FAF3E8'),
        compile_section('cta', [
            heading('h-cta-title', 4, 55, 'Join us this week.', size=28, color='#ffffff'),
            para('h-cta-sub', 4, 55, "We'd love to have you.", size=15, color='#fdf0e6'),
            btn('h-cta-btn', 65, 28, 'Get in Touch', '/contact', y=20),
        ], bg='#C8553D', dark_bg=True),
    ]
    about = [
        compile_section('a-hero', [
            eyebrow('a-eyebrow', 4, 60, 'OUR STORY'),
            heading('a-title', 4, 80, f'How {NAME} began.', size=34, color='#ffffff'),
        ], bg='#C8553D'),
        compile_section('a-story', [
            para('a-story-p', 10, 80, f'{NAME} started small, with a handful of people who believed community mattered. Today it\'s grown into something much bigger -- but the idea is the same: everyone deserves a place to belong.', size=16, align='center'),
        ], bg='#FFFFFF'),
        compile_section('a-values', [
            feature_grid('a-values-grid', 4, 92, [
                {'icon': 'HeartHandshake', 'title': 'Open to Everyone', 'description': 'No matter where you are in your journey.'},
                {'icon': 'Users', 'title': 'Volunteer-Driven', 'description': "So much of what we do runs on generosity."},
                {'icon': 'Sparkles', 'title': 'Always Growing', 'description': "New programs as the community's needs grow."},
            ], card_style='panel'),
        ], bg='#FAF3E8'),
    ]
    services = [
        compile_section('s-hero', [
            eyebrow('s-eyebrow', 4, 60, 'WHAT WE OFFER'),
            heading('s-title', 4, 80, 'Programs & Support', size=34, color='#ffffff'),
        ], bg='#C8553D'),
        compile_section('s-grid', [
            feature_grid('s-items', 4, 92, [
                {'icon': 'Users', 'title': 'Weekly Programs', 'description': 'Regular gatherings for every age and stage.'},
                {'icon': 'HeartHandshake', 'title': 'Community Support', 'description': 'Real help when people need it most.'},
                {'icon': 'Sparkles', 'title': 'Events', 'description': 'Celebrations that bring everyone together.'},
                {'icon': 'Award', 'title': 'Volunteer Opportunities', 'description': 'Meaningful ways to give back.'},
            ]),
        ], bg='#FFFFFF'),
        compile_section('s-cta', [
            callout('s-callout', 4, 92, 'New here?', "We'd love to meet you. Reach out any time and we'll help you get started.", color_scheme='amber', icon='HeartHandshake'),
        ], bg='#FAF3E8'),
    ]
    contact = [
        compile_section('c-hero', [
            eyebrow('c-eyebrow', 4, 60, 'GET IN TOUCH'),
            heading('c-title', 4, 80, "We'd love to hear from you.", size=34, color='#ffffff'),
        ], bg='#C8553D'),
        compile_section('c-body', [
            feature_grid('c-info', 4, 44, [
                {'icon': 'MapPin', 'title': 'Address', 'description': 'Add your address in the site editor.'},
                {'icon': 'Phone', 'title': 'Phone', 'description': 'Add your phone number in the site editor.'},
                {'icon': 'Mail', 'title': 'Email', 'description': 'Add your email in the site editor.'},
            ], card_style='panel'),
            contact_form('c-contact-form', 52, 44, 'Send a Message', style='soft'),
        ], bg='#FFFFFF'),
    ]
    return {
        'name': 'Warm Community', 'category': 'nonprofit',
        'description': 'A welcoming layout for nonprofits, shuls, and community organizations -- mission, ways to get involved, and a genuine welcome.',
        'theme': theme, 'nav_links': _standard_nav(), 'footer_text': f'© {NAME}. All rights reserved.',
        'home_sections': home,
        'extra_pages': [_page('about', 'About', about), _page('services', 'Services', services), _page('contact', 'Contact', contact)],
    }


# ──────────────────────────────────────────────────────────────────────
# 5. Tech Startup -- SaaS, apps, tech-forward services
# ──────────────────────────────────────────────────────────────────────
def tech_startup():
    theme = {
        'palette': 'dark', 'fontPairing': 'technical', 'buttonStyle': 'rounded', 'formStyle': 'boxed',
        'navStyle': 'top', 'footerStyle': 'columns', 'footerDark': True, 'footerDarkBg': '#121417', 'footerDarkText': '#9AA3AE',
    }
    home = [
        compile_section('hero', [
            eyebrow('h-eyebrow', 4, 60, f'{CATEGORY.upper()}, SIMPLIFIED', color='#7C9EFF'),
            heading('h-title', 4, 70, f'{NAME} helps you move faster.', size=42, color='#F0F2F5'),
            para('h-sub', 4, 60, 'Less busywork, more of what actually matters -- built for teams that want to move.', size=17, color='#9AA3AE'),
            btn('h-cta1', 4, 24, 'Get Started', '/contact', y=50),
            btn('h-cta2', 30, 22, 'See How It Works', '/services', y=50, style='outline'),
        ], bg='#121417'),
        compile_section('logos', [
            logo_strip('h-logos', 4, 92, ['Company A', 'Company B', 'Company C', 'Company D'], heading_text='TRUSTED BY TEAMS AT'),
        ], bg='#1C1F24', dark_bg=True),
        compile_section('features', [
            eyebrow('h-f-eyebrow', 4, 60, 'WHY TEAMS SWITCH'),
            heading('h-f-title', 4, 70, 'Built for how you actually work.', size=28),
            feature_grid('h-f-grid', 4, 92, [
                {'icon': 'Zap', 'title': 'Fast by Default', 'description': 'No waiting around for things to load or sync.'},
                {'icon': 'ShieldCheck', 'title': 'Secure by Design', 'description': 'Your data is protected, always.'},
                {'icon': 'Cpu', 'title': 'Actually Smart', 'description': 'Automation that saves real time, not gimmicks.'},
                {'icon': 'Users', 'title': 'Built for Teams', 'description': 'Everyone stays in sync without the extra meetings.'},
            ]),
        ], bg='#FFFFFF'),
        compile_section('stats', [
            feature_grid('h-stats', 4, 92, [
                {'title': '10,000+', 'description': 'Active Users'},
                {'title': '99.9%', 'description': 'Uptime'},
                {'title': '4.9/5', 'description': 'Average Rating'},
            ], card_style='stat'),
        ], bg='#121417', dark_bg=True),
        compile_section('testimonial', [
            testimonial_grid('h-quote', 4, 92, [
                {'quote': f'We switched to {NAME} and never looked back. It just works.', 'author': 'A Happy Customer'},
            ], card_style='quote'),
        ], bg='#FFFFFF'),
        compile_section('cta', [
            heading('h-cta-title', 10, 80, 'Ready to see it in action?', size=30, color='#F0F2F5', align='center'),
            btn('h-cta-btn', 40, 20, 'Get Started', '/contact', y=55),
        ], bg='#121417', dark_bg=True),
    ]
    about = [
        compile_section('a-hero', [
            eyebrow('a-eyebrow', 4, 60, 'ABOUT US', color='#7C9EFF'),
            heading('a-title', 4, 80, f'Why we built {NAME}.', size=36, color='#F0F2F5'),
        ], bg='#121417'),
        compile_section('a-story', [
            para('a-story-p', 10, 80, f'We built {NAME} because we were frustrated with {CATEGORY} tools that made simple things complicated. So we built the tool we actually wanted to use.', size=16, align='center'),
        ], bg='#FFFFFF'),
        compile_section('a-values', [
            feature_grid('a-values-grid', 4, 92, [
                {'icon': 'Zap', 'title': 'Simplicity Wins', 'description': "If it's not simple, we haven't finished building it."},
                {'icon': 'Users', 'title': 'Customer-Led', 'description': 'Our roadmap comes from real feedback, not guesswork.'},
                {'icon': 'ShieldCheck', 'title': 'Trust First', 'description': 'Your data is yours. Always.'},
            ], card_style='row'),
        ], bg='#F0F2F5'),
    ]
    services = [
        compile_section('s-hero', [
            eyebrow('s-eyebrow', 4, 60, 'HOW IT WORKS', color='#7C9EFF'),
            heading('s-title', 4, 80, 'Everything you need, in one place.', size=36, color='#F0F2F5'),
        ], bg='#121417'),
        compile_section('s-grid', [
            feature_grid('s-items', 4, 92, [
                {'icon': 'Zap', 'title': 'Quick Setup', 'description': 'Up and running in minutes, not weeks.'},
                {'icon': 'Users', 'title': 'Team Collaboration', 'description': 'Everyone stays on the same page, automatically.'},
                {'icon': 'LineChart', 'title': 'Real Reporting', 'description': 'See what\'s working without digging for it.'},
                {'icon': 'ShieldCheck', 'title': 'Enterprise-Ready Security', 'description': 'Built to pass your IT team\'s review.'},
            ]),
        ], bg='#FFFFFF'),
        compile_section('s-cta', [
            heading('s-cta-title', 10, 80, 'See it for yourself.', size=28, color='#F0F2F5', align='center'),
            btn('s-cta-btn', 40, 20, 'Get Started', '/contact', y=55),
        ], bg='#121417', dark_bg=True),
    ]
    contact = [
        compile_section('c-hero', [
            eyebrow('c-eyebrow', 4, 60, 'GET IN TOUCH', color='#7C9EFF'),
            heading('c-title', 4, 80, "Let's get you set up.", size=36, color='#F0F2F5'),
        ], bg='#121417'),
        compile_section('c-body', [
            heading('c-form-title', 15, 70, 'Tell Us About Your Team', size=24),
            contact_form('c-contact-form', 15, 70, 'Tell Us About Your Team', style='boxed'),
        ], bg='#FFFFFF'),
    ]
    return {
        'name': 'Tech Startup', 'category': 'other',
        'description': 'A dark, confident layout for SaaS and tech-forward services -- client logos, feature highlights, and clean conversion points.',
        'theme': theme, 'nav_links': _standard_nav(), 'footer_text': f'© {NAME}. All rights reserved.',
        'home_sections': home,
        'extra_pages': [_page('about', 'About', about), _page('services', 'Services', services), _page('contact', 'Contact', contact)],
    }


# ──────────────────────────────────────────────────────────────────────
# 6. Local Service Pro -- contractors, home services, trades
# ──────────────────────────────────────────────────────────────────────
def local_service_pro():
    theme = {
        'palette': 'slate', 'fontPairing': 'modern', 'buttonStyle': 'square', 'formStyle': 'boxed',
        'navStyle': 'top', 'footerStyle': 'columns',
    }
    home = [
        compile_section('hero', [
            eyebrow('h-eyebrow', 4, 60, 'LICENSED & INSURED'),
            heading('h-title', 4, 80, f'{NAME} -- done right, the first time.', size=38, color='#ffffff'),
            para('h-sub', 4, 60, f'Reliable {CATEGORY} work from a team your neighbors already trust.', size=16, color='#E2E8F0'),
            btn('h-cta1', 4, 26, 'Get a Free Quote', '/contact', y=50),
            btn('h-cta2', 32, 24, 'Our Services', '/services', y=50, style='outline'),
            google_badge('h-google', 4, 36),
        ], bg='#1E293B'),
        compile_section('why', [
            feature_grid('h-why-grid', 4, 92, [
                {'icon': 'ShieldCheck', 'title': 'Licensed & Insured', 'description': "You're fully protected, every job."},
                {'icon': 'Clock', 'title': 'On Time, Every Time', 'description': 'We show up when we say we will.'},
                {'icon': 'Award', 'title': 'Satisfaction Guaranteed', 'description': "We're not done until it's right."},
                {'icon': 'Phone', 'title': '24/7 Emergency Service', 'description': "Real help, even after hours."},
            ], card_style='checklist'),
        ], bg='#F1F5F9'),
        compile_section('services-preview', [
            eyebrow('h-svc-eyebrow', 4, 50, 'WHAT WE DO'),
            heading('h-svc-title', 4, 70, 'Services You Can Count On', size=28),
            feature_grid('h-svc-grid', 4, 92, [
                {'icon': 'Wrench', 'title': 'Repairs', 'description': 'Fast, reliable fixes done right the first time.'},
                {'icon': 'Building2', 'title': 'Installation', 'description': 'New installs handled start to finish.'},
                {'icon': 'Calculator', 'title': 'Free Estimates', 'description': 'Know the cost before we start, every time.'},
                {'icon': 'ShieldCheck', 'title': 'Maintenance Plans', 'description': 'Avoid costly surprises down the line.'},
            ]),
            btn('h-svc-cta', 4, 26, 'View All Services', '/services', y=90),
        ], bg='#FFFFFF'),
        compile_section('testimonial', [
            testimonial_grid('h-quote', 4, 92, [
                {'quote': f'{NAME} showed up on time, explained everything clearly, and the price matched the quote. Rare these days.', 'author': 'A Local Customer'},
            ], card_style='quote'),
        ], bg='#F1F5F9'),
        compile_section('cta', [
            heading('h-cta-title', 4, 55, 'Need help today?', size=28, color='#ffffff'),
            para('h-cta-sub', 4, 55, 'Call now or request a free quote online.', size=15, color='#E2E8F0'),
            btn('h-cta-btn', 65, 28, 'Get a Free Quote', '/contact', y=20),
        ], bg='#1E293B', dark_bg=True),
    ]
    about = [
        compile_section('a-hero', [
            eyebrow('a-eyebrow', 4, 60, 'ABOUT US'),
            heading('a-title', 4, 80, f'The team behind {NAME}.', size=34, color='#ffffff'),
        ], bg='#1E293B'),
        compile_section('a-story', [
            para('a-story-p', 10, 80, f'{NAME} has been serving this community with honest, reliable {CATEGORY} work for years. We hire carefully, train thoroughly, and stand behind every job we do.', size=16, align='center'),
        ], bg='#FFFFFF'),
        compile_section('a-values', [
            feature_grid('a-values-grid', 4, 92, [
                {'icon': 'ShieldCheck', 'title': 'Fully Licensed', 'description': 'Every technician is licensed and background-checked.'},
                {'icon': 'HeartHandshake', 'title': 'Honest Pricing', 'description': "No surprise fees, ever."},
                {'icon': 'Award', 'title': 'Guaranteed Work', 'description': "If it's not right, we'll make it right."},
            ], card_style='checklist'),
        ], bg='#F1F5F9'),
    ]
    services = [
        compile_section('s-hero', [
            eyebrow('s-eyebrow', 4, 60, 'OUR SERVICES'),
            heading('s-title', 4, 80, 'Services You Can Count On', size=34, color='#ffffff'),
        ], bg='#1E293B'),
        compile_section('s-list', [
            service_list('s-services', 4, 92, [
                {'icon': 'Wrench', 'title': 'Repairs', 'description': 'Fast, reliable repairs from technicians who show up on time and explain what they find.', 'points': ['Same-week appointments available', 'Transparent, written pricing', 'Parts and labor warranty', 'Clean, respectful work on-site']},
                {'icon': 'Building2', 'title': 'Installation', 'description': 'New installations handled start to finish, with proper permitting and cleanup included.', 'points': ['Free in-home consultation', 'Permitting handled for you', 'Quality equipment, fairly priced', 'Full cleanup after every job']},
                {'icon': 'ShieldCheck', 'title': 'Maintenance Plans', 'description': 'Scheduled maintenance that catches small problems before they become expensive ones.', 'points': ['Priority scheduling for members', 'Discounted repair rates', 'Seasonal check-ups included', 'No long-term contract required']},
            ]),
        ], bg='#FFFFFF'),
        compile_section('s-cta', [
            heading('s-cta-title', 4, 55, 'Get a free quote today.', size=26, color='#ffffff'),
            btn('s-cta-btn', 65, 28, 'Get a Free Quote', '/contact', y=20),
        ], bg='#1E293B', dark_bg=True),
    ]
    contact = [
        compile_section('c-hero', [
            eyebrow('c-eyebrow', 4, 60, 'GET IN TOUCH'),
            heading('c-title', 4, 80, 'Request a Free Quote', size=34, color='#ffffff'),
        ], bg='#1E293B'),
        compile_section('c-body', [
            feature_grid('c-info', 4, 44, [
                {'icon': 'MapPin', 'title': 'Service Area', 'description': 'Add your service area in the site editor.'},
                {'icon': 'Phone', 'title': 'Phone', 'description': 'Add your phone number in the site editor.'},
                {'icon': 'Clock', 'title': 'Hours', 'description': 'Add your hours in the site editor.'},
            ], card_style='row'),
            contact_form('c-contact-form', 52, 44, 'Request a Free Quote', style='boxed'),
        ], bg='#FFFFFF'),
    ]
    return {
        'name': 'Local Service Pro', 'category': 'home_services',
        'description': 'A trust-first layout for contractors and home-service businesses -- licensing/guarantees, a clear services list, and a fast quote path.',
        'theme': theme, 'nav_links': _standard_nav(), 'footer_text': f'© {NAME}. All rights reserved.',
        'home_sections': home,
        'extra_pages': [_page('about', 'About', about), _page('services', 'Services', services), _page('contact', 'Contact', contact)],
    }


# ──────────────────────────────────────────────────────────────────────
# 7. Health & Wellness -- spas, clinics, fitness studios
# ──────────────────────────────────────────────────────────────────────
def health_and_wellness():
    theme = {
        'palette': 'rose', 'fontPairing': 'friendly', 'buttonStyle': 'pill', 'formStyle': 'soft',
        'navStyle': 'split', 'footerStyle': 'stacked',
    }
    home = [
        compile_section('hero', [
            eyebrow('h-eyebrow', 10, 80, 'FEEL YOUR BEST', align='center'),
            heading('h-title', 10, 80, f'{NAME} is here for you.', size=40, align='center'),
            para('h-sub', 15, 70, f'Personalized {CATEGORY} care in a calm, welcoming space.', size=17, align='center'),
            btn('h-cta1', 38, 24, 'Book Now', '/contact', y=45),
        ], bg='#FDF2F6'),
        compile_section('why', [
            feature_grid('h-why-grid', 4, 92, [
                {'icon': 'HeartHandshake', 'title': 'Personalized Care', 'description': 'A plan built around you, not a one-size-fits-all script.'},
                {'icon': 'Award', 'title': 'Experienced Team', 'description': 'Trained professionals who genuinely care about your results.'},
                {'icon': 'Sparkles', 'title': 'A Calm Space', 'description': 'Designed to help you relax from the moment you walk in.'},
            ], card_style='row'),
        ], bg='#FFFFFF'),
        compile_section('services-preview', [
            eyebrow('h-svc-eyebrow', 4, 50, 'WHAT WE OFFER', align='center'),
            heading('h-svc-title', 10, 80, 'Services Built Around You', size=28, align='center'),
            feature_grid('h-svc-grid', 4, 92, [
                {'icon': 'Sparkles', 'title': 'Consultations', 'description': 'A thoughtful first step, every time.'},
                {'icon': 'HeartHandshake', 'title': 'Ongoing Care', 'description': 'Ongoing support, not a one-time visit.'},
                {'icon': 'Award', 'title': 'Specialized Treatments', 'description': 'Options tailored to your specific goals.'},
            ]),
            btn('h-svc-cta', 38, 24, 'See All Services', '/services', y=90),
        ], bg='#FDF2F6'),
        compile_section('testimonial', [
            testimonial_grid('h-quote', 4, 92, [
                {'quote': f'I finally found a {CATEGORY} provider who actually listens. {NAME} changed how I feel day to day.', 'author': 'A Grateful Client'},
            ], card_style='quote'),
        ], bg='#FFFFFF'),
        compile_section('cta', [
            heading('h-cta-title', 10, 80, 'Ready to feel better?', size=28, align='center'),
            btn('h-cta-btn', 40, 20, 'Book Your Visit', '/contact', y=45),
        ], bg='#FDF2F6'),
    ]
    about = [
        compile_section('a-hero', [
            eyebrow('a-eyebrow', 10, 80, 'ABOUT US', align='center'),
            heading('a-title', 10, 80, f'The care behind {NAME}.', size=34, align='center'),
        ], bg='#FDF2F6'),
        compile_section('a-story', [
            para('a-story-p', 15, 70, f'{NAME} was built around a simple belief: good care takes time and genuine attention. Every visit starts with listening, not assuming.', size=16, align='center'),
        ], bg='#FFFFFF'),
        compile_section('a-team', [
            feature_grid('a-team-grid', 4, 92, [
                {'icon': 'Award', 'title': 'Experienced', 'description': 'Years of hands-on expertise.'},
                {'icon': 'HeartHandshake', 'title': 'Attentive', 'description': 'You are never rushed through a visit here.'},
                {'icon': 'Sparkles', 'title': 'Up to Date', 'description': 'We invest in continued training every year.'},
            ], card_style='panel'),
        ], bg='#FDF2F6'),
    ]
    services = [
        compile_section('s-hero', [
            eyebrow('s-eyebrow', 10, 80, 'OUR SERVICES', align='center'),
            heading('s-title', 10, 80, 'Care Built Around You', size=34, align='center'),
        ], bg='#FDF2F6'),
        compile_section('s-grid', [
            feature_grid('s-items', 4, 92, [
                {'icon': 'Sparkles', 'title': 'Initial Consultation', 'description': 'A thorough first visit to understand your goals.'},
                {'icon': 'HeartHandshake', 'title': 'Ongoing Treatment', 'description': 'A plan that evolves as you do.'},
                {'icon': 'Award', 'title': 'Specialized Care', 'description': 'Targeted options for specific needs.'},
                {'icon': 'Users', 'title': 'Group Sessions', 'description': 'A supportive, shared experience.'},
            ]),
        ], bg='#FFFFFF'),
        compile_section('s-cta', [
            heading('s-cta-title', 10, 80, 'Ready to begin?', size=28, align='center'),
            btn('s-cta-btn', 40, 20, 'Book Now', '/contact', y=45),
        ], bg='#FDF2F6'),
    ]
    contact = [
        compile_section('c-hero', [
            eyebrow('c-eyebrow', 10, 80, 'GET IN TOUCH', align='center'),
            heading('c-title', 10, 80, 'Book Your Visit', size=34, align='center'),
        ], bg='#FDF2F6'),
        compile_section('c-body', [
            heading('c-info-title', 4, 44, 'Visit Us', size=22),
            para('c-info-body', 4, 44, 'Add your address and hours in the site editor.', size=15),
            map_block('c-map', 4, 44),
            contact_form('c-contact-form', 52, 44, 'Book Your Visit', style='soft'),
        ], bg='#FFFFFF'),
    ]
    return {
        'name': 'Health & Wellness', 'category': 'health_beauty',
        'description': 'A calm, personal layout for spas, clinics, and fitness studios -- a welcoming tone, treatment highlights, and an easy way to book.',
        'theme': theme, 'nav_links': _standard_nav(), 'footer_text': f'© {NAME}. All rights reserved.',
        'home_sections': home,
        'extra_pages': [_page('about', 'About', about), _page('services', 'Services', services), _page('contact', 'Contact', contact)],
    }


# ──────────────────────────────────────────────────────────────────────
# 8. Minimal Portfolio Plus -- freelancers, creatives, consultants
# ──────────────────────────────────────────────────────────────────────
def minimal_portfolio_plus():
    theme = {
        'palette': 'minimal', 'fontPairing': 'editorial', 'buttonStyle': 'outline', 'formStyle': 'underline',
        'navStyle': 'minimal', 'footerStyle': 'simple',
    }
    home = [
        compile_section('hero', [
            heading('h-title', 10, 80, NAME, size=44, align='center'),
            para('h-sub', 20, 60, f'{CATEGORY}, done with care and attention to detail.', size=17, align='center'),
            btn('h-cta1', 40, 20, 'View My Work', '/services', y=55),
        ], bg='#FFFFFF'),
        compile_section('work', [
            eyebrow('h-work-eyebrow', 10, 80, 'SELECTED WORK', align='center'),
            gallery('h-work-gallery', 4, 92, n_images=6),
        ], bg='#FAFAFA'),
        compile_section('experience', [
            eyebrow('h-exp-eyebrow', 4, 50, 'EXPERIENCE'),
            feature_grid('h-exp-grid', 4, 92, [
                {'badge': 'Now', 'title': f'Independent {CATEGORY}', 'description': 'Working with clients who value quality and honest collaboration.'},
                {'badge': 'Prior', 'title': 'Years of Experience', 'description': 'A solid foundation built across varied, challenging work.'},
            ], card_style='timeline'),
        ], bg='#FFFFFF'),
        compile_section('cta', [
            heading('h-cta-title', 10, 80, "Let's work together.", size=28, align='center'),
            btn('h-cta-btn', 40, 20, 'Say Hello', '/contact', y=55),
        ], bg='#FAFAFA'),
    ]
    about = [
        compile_section('a-hero', [
            heading('a-title', 10, 80, 'A Little About Me', size=36, align='center'),
        ], bg='#FFFFFF'),
        compile_section('a-story', [
            para('a-story-p', 15, 70, f'I\'m the person behind {NAME}. I care about doing work that actually solves the problem in front of me, not just checking a box -- and I like clients who feel the same way.', size=16, align='center'),
        ], bg='#FAFAFA'),
    ]
    services = [
        compile_section('s-hero', [
            heading('s-title', 10, 80, 'What I Do', size=36, align='center'),
        ], bg='#FFFFFF'),
        compile_section('s-list', [
            service_list('s-services', 4, 92, [
                {'icon': 'Sparkles', 'title': 'Project Work', 'description': 'Focused, high-quality work delivered on a clear timeline.', 'points': ['A clear scope before we start', 'Regular updates along the way', 'Honest timelines, no surprises']},
                {'icon': 'Users', 'title': 'Ongoing Collaboration', 'description': 'A longer-term partnership for work that keeps evolving.', 'points': ['Flexible, ongoing availability', 'Consistent quality over time', 'A real working relationship, not a vendor transaction']},
            ], numbered=False),
        ], bg='#FAFAFA'),
    ]
    contact = [
        compile_section('c-hero', [
            heading('c-title', 10, 80, 'Say Hello', size=36, align='center'),
            para('c-sub', 20, 60, "Tell me about your project -- I'll get back to you soon.", size=15, align='center'),
        ], bg='#FFFFFF'),
        compile_section('c-form', [
            contact_form('c-contact-form', 25, 50, 'Say Hello', style='underline'),
        ], bg='#FAFAFA'),
    ]
    return {
        'name': 'Minimal Portfolio Plus', 'category': 'other',
        'description': 'A quiet, image-forward layout for freelancers and consultants -- a work gallery, a simple timeline, and an easy way to reach out.',
        'theme': theme, 'nav_links': [{'label': 'Services', 'path': '/services'}, {'label': 'About', 'path': '/about'}, {'label': 'Contact', 'path': '/contact'}],
        'footer_text': f'© {NAME}.', 'home_sections': home,
        'extra_pages': [_page('about', 'About', about), _page('services', 'Services', services), _page('contact', 'Contact', contact)],
    }


# ──────────────────────────────────────────────────────────────────────
# 9. Retail Boutique -- shops, makers, small retail
# ──────────────────────────────────────────────────────────────────────
def retail_boutique():
    theme = {
        'palette': 'sunset', 'fontPairing': 'rounded', 'buttonStyle': 'pill', 'formStyle': 'soft',
        'navStyle': 'top', 'footerStyle': 'simple',
    }
    home = [
        compile_section('hero', [
            eyebrow('h-eyebrow', 10, 80, 'NEW ARRIVALS WEEKLY', align='center'),
            heading('h-title', 10, 80, NAME, size=42, align='center'),
            para('h-sub', 15, 70, f'Thoughtfully chosen {CATEGORY}, picked with you in mind.', size=17, align='center'),
            btn('h-cta1', 38, 24, 'Shop Now', '/cart', y=45),
        ], bg='#FFF6ED'),
        compile_section('gallery', [
            eyebrow('h-g-eyebrow', 10, 80, 'A FEW FAVORITES', align='center'),
            gallery('h-gallery', 4, 92, n_images=6),
        ], bg='#FFFFFF'),
        compile_section('why', [
            feature_grid('h-why-grid', 4, 92, [
                {'icon': 'Sparkles', 'title': 'Handpicked', 'description': "Every piece is chosen with care, not mass-ordered."},
                {'icon': 'Truck', 'title': 'Fast Shipping', 'description': "Quick, careful delivery to your door."},
                {'icon': 'HeartHandshake', 'title': 'Easy Returns', 'description': "Not quite right? We'll make it easy."},
            ], card_style='checklist'),
        ], bg='#FFF6ED'),
        compile_section('press', [
            logo_strip('h-press', 4, 92, ['Press Mention', 'Press Mention', 'Press Mention'], heading_text='AS SEEN IN'),
        ], bg='#FFFFFF'),
        compile_section('testimonial', [
            testimonial_grid('h-quote', 4, 92, [
                {'quote': f'{NAME} has become my go-to. The quality is always there.', 'author': 'A Happy Customer'},
            ], card_style='quote'),
        ], bg='#FFF6ED'),
    ]
    about = [
        compile_section('a-hero', [
            eyebrow('a-eyebrow', 10, 80, 'OUR STORY', align='center'),
            heading('a-title', 10, 80, f'The story behind {NAME}.', size=34, align='center'),
        ], bg='#FFF6ED'),
        compile_section('a-story', [
            para('a-story-p', 15, 70, f'{NAME} started with a simple love of good {CATEGORY} and a frustration with settling for less. Every item we carry, we\'d happily keep for ourselves.', size=16, align='center'),
        ], bg='#FFFFFF'),
    ]
    services = [
        compile_section('s-hero', [
            eyebrow('s-eyebrow', 10, 80, 'SHOP', align='center'),
            heading('s-title', 10, 80, 'What We Carry', size=34, align='center'),
        ], bg='#FFF6ED'),
        compile_section('s-grid', [
            feature_grid('s-items', 4, 92, [
                {'icon': 'Sparkles', 'title': 'New Arrivals', 'description': 'Fresh picks, added every week.'},
                {'icon': 'Award', 'title': 'Customer Favorites', 'description': 'The pieces people keep coming back for.'},
                {'icon': 'HeartHandshake', 'title': 'Gift Sets', 'description': 'Thoughtfully put together, ready to give.'},
            ]),
            btn('s-cta', 38, 24, 'Shop Now', '/cart', y=90),
        ], bg='#FFFFFF'),
    ]
    contact = [
        compile_section('c-hero', [
            eyebrow('c-eyebrow', 10, 80, 'GET IN TOUCH', align='center'),
            heading('c-title', 10, 80, "We'd Love to Hear From You", size=32, align='center'),
        ], bg='#FFF6ED'),
        compile_section('c-form', [
            contact_form('c-contact-form', 25, 50, 'Send a Message', style='soft'),
        ], bg='#FFFFFF'),
    ]
    return {
        'name': 'Retail Boutique', 'category': 'retail',
        'description': 'A friendly, photo-led layout for shops and makers -- new arrivals, press mentions, and a direct line to your storefront.',
        'theme': theme, 'nav_links': [{'label': 'Shop', 'path': '/cart'}, {'label': 'About', 'path': '/about'}, {'label': 'Contact', 'path': '/contact'}],
        'footer_text': f'© {NAME}. All rights reserved.', 'home_sections': home,
        'extra_pages': [_page('about', 'About', about), _page('services', 'Services', services), _page('contact', 'Contact', contact)],
    }


# ──────────────────────────────────────────────────────────────────────
# 10. Nonprofit Mission -- charities, causes, advocacy groups
# ──────────────────────────────────────────────────────────────────────
def nonprofit_mission():
    theme = {
        'palette': 'forest', 'fontPairing': 'classic', 'buttonStyle': 'rounded', 'formStyle': 'boxed',
        'navStyle': 'top', 'footerStyle': 'columns', 'footerDark': True, 'footerDarkBg': '#1E2E24', 'footerDarkText': '#C8E0CF',
    }
    home = [
        compile_section('hero', [
            eyebrow('h-eyebrow', 4, 60, 'OUR MISSION'),
            heading('h-title', 4, 80, f'{NAME} is changing lives.', size=40, color='#ffffff'),
            para('h-sub', 4, 60, f'Join us in making a real difference in {CATEGORY}.', size=17, color='#e7f3ea'),
            btn('h-cta1', 4, 24, 'Donate Now', '/contact', y=50),
            btn('h-cta2', 30, 22, 'Our Impact', '/about', y=50, style='outline'),
        ], bg='#2F6B4F'),
        compile_section('impact', [
            eyebrow('h-impact-eyebrow', 4, 50, 'OUR IMPACT'),
            heading('h-impact-title', 4, 70, 'Real numbers, real change.', size=28),
            feature_grid('h-impact-grid', 4, 92, [
                {'title': '5,000+', 'description': 'Lives Impacted'},
                {'title': '$2M+', 'description': 'Raised for the Cause'},
                {'title': '15', 'description': 'Years of Service'},
                {'title': '200+', 'description': 'Active Volunteers'},
            ], card_style='stat'),
        ], bg='#F1F7F2'),
        compile_section('cause', [
            callout('h-callout', 4, 92, 'Every donation makes a difference.', f'{NAME} relies on supporters like you. No amount is too small -- every contribution goes directly toward our mission.', color_scheme='green', icon='HeartHandshake'),
        ], bg='#FFFFFF'),
        compile_section('testimonial', [
            testimonial_grid('h-quote', 4, 92, [
                {'quote': f'{NAME} gave our family real support when we needed it most. We\'ll never forget it.', 'author': 'Someone We Helped'},
            ], card_style='quote'),
        ], bg='#F1F7F2'),
        compile_section('cta', [
            heading('h-cta-title', 4, 55, 'Ready to help?', size=28, color='#ffffff'),
            para('h-cta-sub', 4, 55, 'Every contribution brings us closer to our goal.', size=15, color='#e7f3ea'),
            btn('h-cta-btn', 65, 28, 'Donate Now', '/contact', y=20),
        ], bg='#2F6B4F', dark_bg=True),
    ]
    about = [
        compile_section('a-hero', [
            eyebrow('a-eyebrow', 4, 60, 'ABOUT US'),
            heading('a-title', 4, 80, f'Why {NAME} exists.', size=34, color='#ffffff'),
        ], bg='#2F6B4F'),
        compile_section('a-story', [
            para('a-story-p', 10, 80, f'{NAME} was founded because we saw a real need and decided to act. Every program we run traces back to that same simple commitment: show up for people who need it.', size=16, align='center'),
        ], bg='#FFFFFF'),
        compile_section('a-values', [
            feature_grid('a-values-grid', 4, 92, [
                {'icon': 'HeartHandshake', 'title': 'People First', 'description': 'Every decision starts with who it actually helps.'},
                {'icon': 'ShieldCheck', 'title': 'Full Transparency', 'description': 'You can always see where the support goes.'},
                {'icon': 'Users', 'title': 'Community-Driven', 'description': 'Built with the people we serve, not just for them.'},
            ], card_style='row'),
        ], bg='#F1F7F2'),
    ]
    services = [
        compile_section('s-hero', [
            eyebrow('s-eyebrow', 4, 60, 'WHAT WE DO'),
            heading('s-title', 4, 80, 'Our Programs', size=34, color='#ffffff'),
        ], bg='#2F6B4F'),
        compile_section('s-grid', [
            feature_grid('s-items', 4, 92, [
                {'icon': 'Users', 'title': 'Direct Support', 'description': 'Hands-on help for people who need it now.'},
                {'icon': 'Sparkles', 'title': 'Education & Outreach', 'description': 'Building awareness and long-term change.'},
                {'icon': 'HeartHandshake', 'title': 'Volunteer Programs', 'description': 'Meaningful ways to get involved directly.'},
            ]),
        ], bg='#FFFFFF'),
        compile_section('s-cta', [
            callout('s-callout', 4, 92, 'Want to get involved?', 'Volunteering, donating, or spreading the word all make a real difference. Reach out any time.', color_scheme='green', icon='HeartHandshake'),
        ], bg='#F1F7F2'),
    ]
    contact = [
        compile_section('c-hero', [
            eyebrow('c-eyebrow', 4, 60, 'GET IN TOUCH'),
            heading('c-title', 4, 80, 'Support Our Mission', size=34, color='#ffffff'),
        ], bg='#2F6B4F'),
        compile_section('c-body', [
            feature_grid('c-info', 4, 44, [
                {'icon': 'MapPin', 'title': 'Address', 'description': 'Add your address in the site editor.'},
                {'icon': 'Phone', 'title': 'Phone', 'description': 'Add your phone number in the site editor.'},
                {'icon': 'Mail', 'title': 'Email', 'description': 'Add your email in the site editor.'},
            ], card_style='panel'),
            contact_form('c-contact-form', 52, 44, 'Send a Message', style='boxed'),
        ], bg='#FFFFFF'),
    ]
    return {
        'name': 'Nonprofit Mission', 'category': 'nonprofit',
        'description': 'A mission-first layout for charities and advocacy groups -- impact numbers, a clear donate path, and real stories of change.',
        'theme': theme, 'nav_links': _standard_nav(), 'footer_text': f'© {NAME}. All rights reserved.',
        'home_sections': home,
        'extra_pages': [_page('about', 'About', about), _page('services', 'Services', services), _page('contact', 'Contact', contact)],
    }


ALL_TEMPLATES_V2 = [
    modern_professional, elegant_hospitality, bold_creative_studio, warm_community,
    tech_startup, local_service_pro, health_and_wellness, minimal_portfolio_plus,
    retail_boutique, nonprofit_mission,
]


def seed_v2_templates():
    """Idempotent, same convention as site_template.py's own
    seed_default_templates() -- only ever inserts a template whose name
    isn't already in the table, never overwrites one a SuperAdmin has
    since edited. Needs the extra_pages column (migration
    a7f3c8e2b5d9) to already exist."""
    from config import db
    from backend.business.modals.site_template import SiteTemplate

    existing_names = {t.name for t in SiteTemplate.query.filter_by(is_system_default=True).all()}
    position = SiteTemplate.query.count()
    created = 0
    for fn in ALL_TEMPLATES_V2:
        tpl = fn()
        if tpl['name'] in existing_names:
            continue
        db.session.add(SiteTemplate(
            name=tpl['name'], description=tpl['description'], category=tpl['category'],
            theme=tpl['theme'], home_sections=tpl['home_sections'], extra_pages=tpl['extra_pages'],
            nav_links=tpl['nav_links'], footer_text=tpl['footer_text'],
            is_system_default=True, position=position,
        ))
        position += 1
        created += 1
    if created:
        db.session.commit()
    return created
