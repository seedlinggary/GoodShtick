"""Static Jewish-holiday-closure data for the "auto Yom Tov & Shabbos hours"
feature (opt in per-location via attributes.auto_holiday_closure).

Deliberately a bundled static table rather than a live call to a calendar
API: closure dates need to render correctly even if an outbound request is
slow/down, and it makes this feature deterministic to test. Dates are plain
calendar facts (civil dates of well-known Jewish holidays), not creative
content -- extend YOM_TOV_RANGES by one row per year as years pass.

Each range is inclusive-start/exclusive-end civil dates during which the
location should show as closed for the holiday, in UTC-naive terms (matches
how BusinessLocation.hours is already compared against server time in
business/routes/business.py's _location_open_now).
"""
from datetime import date, datetime, timedelta

# (label, start_date, end_date_inclusive)
YOM_TOV_RANGES = [
    ('Rosh Hashanah 5786', date(2026, 9, 12), date(2026, 9, 14)),
    ('Yom Kippur 5786', date(2026, 9, 21), date(2026, 9, 21)),
    ('Sukkot 5786', date(2026, 9, 26), date(2026, 9, 27)),
    ('Shemini Atzeret / Simchat Torah 5786', date(2026, 10, 3), date(2026, 10, 4)),
    ('Pesach I-II 5786', date(2027, 4, 2), date(2027, 4, 3)),
    ('Pesach VII-VIII 5786', date(2027, 4, 8), date(2027, 4, 9)),
    ('Shavuot 5786', date(2027, 5, 22), date(2027, 5, 23)),
    ('Rosh Hashanah 5787', date(2027, 10, 2), date(2027, 10, 3)),
    ('Yom Kippur 5787', date(2027, 10, 11), date(2027, 10, 11)),
    ('Sukkot 5787', date(2027, 10, 16), date(2027, 10, 17)),
    ('Shemini Atzeret / Simchat Torah 5787', date(2027, 10, 23), date(2027, 10, 24)),
]

# Simple fixed-offset approximation of candle lighting / Havdalah -- not a
# real sunset calculation (that needs the location's lat/lng and a solar
# almanac). Good enough for an opt-in auto-closure default; an owner who
# wants precise times can still set explicit Friday/Saturday hours instead
# of enabling this toggle.
FRIDAY_CLOSE_HOUR = 17  # 5:00 PM local-assumed
SATURDAY_REOPEN_HOUR = 21  # 9:00 PM local-assumed


def holiday_closure_today(now=None):
    """Returns the holiday label if `now` (a date/datetime) falls inside a
    Yom Tov closure range, else None."""
    today = (now or datetime.utcnow()).date() if isinstance(now, datetime) else (now or date.today())
    for label, start, end in YOM_TOV_RANGES:
        if start <= today <= end:
            return label
    return None


def upcoming_holiday_closures(days_ahead=45, now=None):
    today = (now or datetime.utcnow()).date() if isinstance(now, datetime) else (now or date.today())
    horizon = today + timedelta(days=days_ahead)
    return [
        {'label': label, 'start': start.isoformat(), 'end': end.isoformat()}
        for label, start, end in YOM_TOV_RANGES
        if start <= horizon and end >= today
    ]


def is_shabbat_closed(now=None):
    """Friday after FRIDAY_CLOSE_HOUR through Saturday before
    SATURDAY_REOPEN_HOUR, using server time as a stand-in for local time --
    same known limitation as _location_open_now in business/routes/business.py."""
    now = now or datetime.utcnow()
    weekday, hour = now.weekday(), now.hour  # Mon=0 .. Sun=6
    if weekday == 4 and hour >= FRIDAY_CLOSE_HOUR:  # Friday evening
        return True
    if weekday == 5 and hour < SATURDAY_REOPEN_HOUR:  # Saturday until nightfall
        return True
    return False


def auto_closure_reason(now=None):
    """Single entry point the /businesses list/detail routes call when a
    location has attributes.auto_holiday_closure enabled. Returns a short
    reason string if it should show closed right now, else None."""
    holiday = holiday_closure_today(now)
    if holiday:
        return holiday
    if is_shabbat_closed(now):
        return 'Shabbat'
    return None
