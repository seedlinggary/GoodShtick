"""Seasonal campaign templates for the Social Desk composer -- pre-written
caption starters timed to the same Jewish-holiday table already used for
auto-closure hours (see holidays.py), so a business owner gets a "quick
start" suggestion instead of a blank textarea in the run-up to a holiday
that actually matters for their category.

Deliberately static/bundled, same reasoning as holidays.py: no outbound
call needed, fully deterministic to test.
"""
from datetime import date

from backend.business.social.holidays import YOM_TOV_RANGES

# label -> {category -> caption template, 'default' -> generic fallback}
# {name} is replaced with the business name at render time.
CAMPAIGN_COPY = {
    'Rosh Hashanah': {
        'restaurant': "Sweet new year specials at {name}! Stop by for round challah, honey cake, and everything you need for a sweet 5786. \U0001F36F",
        'grocery': "Rosh Hashanah is almost here -- {name} is stocked up on round challah, apples, honey, and everything for your holiday table.",
        'default': "Wishing you a sweet new year from all of us at {name}! Come see what we've got for Rosh Hashanah.",
    },
    'Yom Kippur': {
        'restaurant': "Pre-fast and break-fast platters are ready at {name} -- order ahead so your table's covered before and after the fast.",
        'default': "An easy fast from {name}. We'll be here when it's time to break it.",
    },
    'Sukkot': {
        'entertainment': "Book your sukkah decor, simcha hall dates, or event needs at {name} before Sukkot fills up the calendar.",
        'default': "Chag Sameach from {name}! Come see what we've got for Sukkot.",
    },
    'Shemini Atzeret / Simchat Torah': {
        'default': "Chag Sameach from {name} -- wishing you a joyous Simchat Torah!",
    },
    'Pesach I-II': {
        'grocery': "Pesach shopping starts at {name} -- kosher l'Pesach stock is in, come beat the last-minute rush.",
        'home_services': "Pesach cleaning season is here -- {name} is booking now before the calendar fills up.",
        'default': "Chag Kasher V'Sameach from {name}!",
    },
    'Pesach VII-VIII': {
        'default': "Wishing everyone a Chag Sameach from {name} as Pesach wraps up.",
    },
    'Shavuot': {
        'restaurant': "It's a dairy holiday! {name} has cheesecake, blintzes, and all your Shavuot dairy favorites ready to order.",
        'grocery': "Shavuot dairy stock has arrived at {name} -- cheesecake ingredients, dairy staples, and more.",
        'default': "Chag Sameach from {name} -- wishing you a wonderful Shavuot.",
    },
    # Not in YOM_TOV_RANGES (no fixed civil date the way Yom Tov has -- shown
    # year-round as an evergreen suggestion instead of a dated one below).
    'Chanukah': {
        'retail': "The Chanukah gift guide is here! Stop by {name} for gifts everyone on your list will actually want.",
        'restaurant': "Latkes, donuts, and everything fried -- {name} is celebrating Chanukah all eight nights.",
        'default': "Happy Chanukah from {name}! Come see what we've got for the holiday.",
    },
    'Purim': {
        'retail': "Purim baskets, costumes, and mishloach manot supplies are in stock at {name}.",
        'restaurant': "Purim seudah catering and mishloach manot platters -- order now at {name} before Purim week fills up.",
        'default': "Purim Sameach from {name}!",
    },
}


def upcoming_campaign_templates(category=None, business_name='your business', days_ahead=30, today=None):
    """Templates for holidays with a fixed date inside the window (from
    YOM_TOV_RANGES), plus Chanukah/Purim always offered as evergreen
    suggestions since they aren't in that dated table."""
    today = today or date.today()
    templates = []

    for label, start, end in YOM_TOV_RANGES:
        days_out = (start - today).days
        if 0 <= days_out <= days_ahead and label.split(' 5')[0] in CAMPAIGN_COPY:
            base_label = next((k for k in CAMPAIGN_COPY if label.startswith(k)), None)
            if not base_label:
                continue
            copy_map = CAMPAIGN_COPY[base_label]
            caption = (copy_map.get(category) or copy_map['default']).format(name=business_name)
            templates.append({'holiday': label, 'days_away': days_out, 'caption': caption})

    for label in ('Chanukah', 'Purim'):
        copy_map = CAMPAIGN_COPY[label]
        caption = (copy_map.get(category) or copy_map['default']).format(name=business_name)
        templates.append({'holiday': label, 'days_away': None, 'caption': caption})

    templates.sort(key=lambda t: (t['days_away'] is None, t['days_away'] or 0))
    return templates
