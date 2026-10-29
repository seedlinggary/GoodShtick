"""Best-effort reader for an Israeli Form 106 (טופס 106) PDF, so someone can
upload their actual year-end tax summary instead of typing numbers in by
hand. Deliberately narrow in scope:

- Text-based PDFs only (what every payroll system -- Hilan, Malam, etc. --
  actually generates). A scanned/photographed Form 106 has no extractable
  text layer and pdfplumber returns nothing for it; we detect that case and
  tell the caller plainly rather than guessing from a blank page.
- Nothing is ever persisted. The uploaded bytes exist only for this one
  request, in memory, and are discarded the moment the response is sent --
  this is someone's salary and ID-adjacent tax paperwork, so the least we
  can do is not store it anywhere.
- Field extraction is label-proximity matching on Hebrew keywords, not a
  real forms-parser -- Form 106 layouts vary by payroll provider and aren't
  standardized character-for-character. Every extracted figure comes back
  tagged as a best-effort guess for the frontend to show as "we think this
  is X -- please check", never as a trusted final number.
"""
import re
from io import BytesIO

import pdfplumber
from flask import Blueprint, jsonify, request

from security import token_required

finance_form106_api = Blueprint('finance_form106_api', __name__, url_prefix='/finance')

MAX_UPLOAD_BYTES = 8 * 1024 * 1024  # 8MB -- Form 106 is a 1-2 page document, this is generous

# Each field: a list of Hebrew (and occasional English) substrings that tend
# to label it on a Form 106 / payslip-style summary. First match on a line
# wins; checked in this order so more specific labels (e.g. "בריאות") don't
# get shadowed by a more general one checked later.
FIELD_LABELS = {
    'grossAnnualIncome': ['סך הכנסה', 'סה"כ הכנסה', 'הכנסת עבודה', 'סך הכנסות'],
    'incomeTaxWithheld': ['מס הכנסה שנוכה', 'סה"כ מס הכנסה', 'ניכוי מס הכנסה', 'מס שנוכה'],
    'niWithheld': ['ביטוח לאומי'],
    'healthTaxWithheld': ['מס בריאות', 'דמי בריאות'],
    'pensionContributions': ['קרן פנסיה', 'קופת גמל'],
    'studyFundContributions': ['קרן השתלמות'],
    'creditPoints': ['נקודות זיכוי'],
}

NUMBER_RE = re.compile(r'[\d][\d,]*\.?\d*')


def _parse_number(token):
    try:
        return float(token.replace(',', ''))
    except ValueError:
        return None


def _extract_fields(text):
    """Line-by-line label match -- for each line, if a field's keyword
    appears anywhere in it, take the LAST numeric token on that line as the
    value (Form 106's layout is almost always "label .... amount", and
    digit sequences stay left-to-right even inside RTL-extracted text, so
    the rightmost-in-reading-order number is the one actually after the
    label most of the time). Only the first matching line per field counts,
    since Form 106 states each total once."""
    found = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        # Skip the document's own title/header line ("טופס 106 - אישור על...") --
        # it names several fields in passing (e.g. "...ודמי ביטוח לאומי משכר")
        # without actually reporting their values, which would otherwise
        # false-match against the literal "106" in "טופס 106" as if it were
        # an amount.
        if not line or 'טופס' in line:
            continue
        for field, labels in FIELD_LABELS.items():
            if field in found:
                continue
            if any(label in line for label in labels):
                numbers = NUMBER_RE.findall(line)
                if numbers:
                    value = _parse_number(numbers[-1])
                    if value is not None:
                        found[field] = value
    return found


@finance_form106_api.route('/form106/parse', methods=['POST'])
@token_required
def parse_form106(current_user):
    if request.content_length and request.content_length > MAX_UPLOAD_BYTES:
        return jsonify({'message': 'File is too large (max 8MB) -- a Form 106 PDF is normally well under 1MB.'}), 413

    upload = request.files.get('file')
    if not upload or not upload.filename:
        return jsonify({'message': 'Attach a PDF file.'}), 400
    if not upload.filename.lower().endswith('.pdf'):
        return jsonify({'message': 'Only PDF files are supported right now.'}), 400

    data = upload.read()
    if len(data) > MAX_UPLOAD_BYTES:
        return jsonify({'message': 'File is too large (max 8MB) -- a Form 106 PDF is normally well under 1MB.'}), 413

    try:
        with pdfplumber.open(BytesIO(data)) as pdf:
            text = '\n'.join(page.extract_text() or '' for page in pdf.pages)
    except Exception:
        return jsonify({'message': "Couldn't read that file -- make sure it's a valid, non-password-protected PDF."}), 400

    if not text.strip():
        return jsonify({
            'scanned': True,
            'fields': {},
            'message': "This looks like a scanned or photographed PDF with no selectable text, so we can't read it automatically. Enter your numbers manually below using the figures from your form.",
        })

    fields = _extract_fields(text)
    missing = [f for f in FIELD_LABELS if f not in fields]
    return jsonify({
        'scanned': False,
        'fields': fields,
        'missing': missing,
        'message': 'These are best-effort readings from your form, not a certified extraction -- check every figure below against the actual PDF before relying on it.',
    })
