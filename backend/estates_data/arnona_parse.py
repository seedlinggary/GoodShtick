"""Heuristic extraction of candidate arnona rates from a PDF's plain
text (connectors/arnona_pdf.py does the fetching, this does the
guessing). Deliberately separate from linking.py's shared operations --
this is specific to one source's messy input, not a general-purpose tool.

PDF table extraction loses column alignment often enough that a rate, its
zone, and its use-type/area-component can end up on different lines, or
merged onto one line with other numbers entirely. This never claims
certainty: every candidate it emits carries a confidence score and the
exact source line, for a human to approve or reject
(ArnonaRateCandidate, reviewed via /estates-data/admin/arnona-candidates)
-- it never writes directly to the trusted ArnonaRate table."""
import re

USE_TYPE_KEYWORDS = (
    ('residential', ('מגורים',)),
    ('commercial', ('מסחר', 'עסקים', 'מסחרי')),
    ('industrial', ('תעשיה', 'תעשייה')),
    ('office', ('משרד', 'משרדים')),
)

# Checked in this order so a more specific phrase ("מרפסת מקורה") wins
# over the generic word it contains ("מרפסת").
AREA_COMPONENT_KEYWORDS = (
    ('balcony_covered', ('מרפסת מקורה', 'מרפסת סגורה')),
    ('balcony_open', ('מרפסת שמש', 'מרפסת פתוחה', 'מרפסת')),
    ('storage', ('מחסן',)),
    ('parking', ('חניה', 'חנייה')),
    ('shared', ('שטח משותף', 'משותף')),
    ('main', ('עיקרי', 'מבונה')),
)

_RATE_PATTERN = re.compile(r'\d{1,4}(?:[.,]\d{1,2})?')
_UNIT_MARKERS = ('ש"ח', 'שח', '₪', 'למ"ר', 'למר')
_ZONE_PATTERN = re.compile(r'אזור\s*([א-ת0-9]{1,3})')

# Real Israeli residential arnona rates (2026-ish) sit roughly in this
# range -- used only to drop obviously-wrong matches (a year, a page
# number, a phone extension), not to validate a real one.
_PLAUSIBLE_RATE_RANGE = (1, 2000)


def _match_keyword(line, keyword_map):
    for key, phrases in keyword_map:
        for phrase in phrases:
            if phrase in line:
                return key
    return None


def parse_arnona_candidates(text):
    """Line-by-line heuristic: a line only produces a candidate if it
    has BOTH a currency/per-sqm unit marker and a plausible number.
    Zone/use-type/area-component tags come from whatever keywords also
    appear on that same line, or are left None when the line doesn't say
    -- never guessed from context. Returns a list of candidate dicts;
    expect some to be wrong or duplicated, that's what review is for."""
    candidates = []
    for line in (text or '').splitlines():
        line = line.strip()
        if not line or len(line) > 200:
            continue
        if not any(marker in line for marker in _UNIT_MARKERS):
            continue

        use_type = _match_keyword(line, USE_TYPE_KEYWORDS)
        area_component = _match_keyword(line, AREA_COMPONENT_KEYWORDS)
        zone_match = _ZONE_PATTERN.search(line)
        zone = zone_match.group(1) if zone_match else None

        confidence = 0.2
        if use_type:
            confidence += 0.2
        if area_component:
            confidence += 0.2
        if zone:
            confidence += 0.1

        # The zone's own digit (e.g. the "1" in "אזור 1") matches the
        # same rate-number pattern and must not be read as a rate itself
        # -- re-scan the line with that whole "אזור N" span blanked out.
        search_line = line
        if zone_match:
            search_line = line[:zone_match.start()] + line[zone_match.end():]
        numbers = _RATE_PATTERN.findall(search_line)
        if not numbers:
            continue

        for raw_number in numbers:
            try:
                value = float(raw_number.replace(',', '.'))
            except ValueError:
                continue
            if not (_PLAUSIBLE_RATE_RANGE[0] <= value <= _PLAUSIBLE_RATE_RANGE[1]):
                continue
            candidates.append({
                'zone': zone,
                'use_type': use_type,
                'area_component': area_component or 'main',
                'rate_per_sqm': value,
                'confidence': round(min(confidence, 0.9), 2),
                'raw_line': line,
            })

    return candidates
