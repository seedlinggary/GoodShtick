"""Renders a TorahSourceSheet to PDF or Word, for a rabbi to preview and
download a sheet they've built. Hebrew needs actual RTL handling, which
neither library does automatically:

- PDF (reportlab): reportlab lays out whatever Unicode codepoints it's
  given, left-to-right, using whichever font is active -- it has no
  built-in bidi algorithm and ships no Hebrew-covering font at all. Both
  are handled explicitly below: python-bidi's get_display() reorders each
  Hebrew string into visual order before it's drawn, and Noto Sans/Noto
  Sans Hebrew (bundled under backend/torah/fonts/, OFL-licensed) are
  registered and embedded so the glyphs actually exist in the output file.
- Word (.docx, python-docx): python-docx has no public API for a
  paragraph's/run's right-to-left flag, so it's set via direct OOXML
  element manipulation (_set_rtl_paragraph/_set_rtl_run below) -- Word
  itself still does its own bidi shaping once that flag is set, so (unlike
  the PDF path) the raw logical-order Hebrew string is used as-is, NOT
  run through get_display() first.

Sefaria's text segments are HTML fragments (<b>, <i>, footnote markup,
...). Full HTML-aware RTL layout is a genuinely deep rabbit hole (reportlab
Paragraph's bidi-unaware mini-HTML parser would need every tag's contents
reordered independently around the tags, not the whole string) -- so for
this first version tags are stripped to plain text rather than attempting
partial formatting preservation that's more likely to render subtly wrong
than not render bold/italic at all.
"""
import io
import os
import re

from bidi.algorithm import get_display
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Pt
from reportlab.lib.enums import TA_RIGHT, TA_LEFT, TA_CENTER
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable

FONT_DIR = os.path.join(os.path.dirname(__file__), 'fonts')
_FONTS_REGISTERED = False


def _register_fonts():
    global _FONTS_REGISTERED
    if _FONTS_REGISTERED:
        return
    pdfmetrics.registerFont(TTFont('NotoHebrew', os.path.join(FONT_DIR, 'NotoSansHebrew-Regular.ttf')))
    pdfmetrics.registerFont(TTFont('NotoHebrew-Bold', os.path.join(FONT_DIR, 'NotoSansHebrew-Bold.ttf')))
    pdfmetrics.registerFont(TTFont('NotoLatin', os.path.join(FONT_DIR, 'NotoSans-Regular.ttf')))
    pdfmetrics.registerFont(TTFont('NotoLatin-Bold', os.path.join(FONT_DIR, 'NotoSans-Bold.ttf')))
    _FONTS_REGISTERED = True


def _strip_html(html):
    if not html:
        return ''
    text = re.sub(r'<[^>]+>', '', html)
    text = text.replace('&nbsp;', ' ').replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>').replace('&quot;', '"')
    return text.strip()


def _he_display(html):
    """Plain text, reordered into visual order for reportlab (see module
    docstring) -- NOT used for the Word path, which wants logical order."""
    return get_display(_strip_html(html))


# ── PDF ──────────────────────────────────────────────────────────────────

def build_pdf(sheet):
    _register_fonts()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=letter,
        topMargin=0.75 * inch, bottomMargin=0.75 * inch, leftMargin=0.75 * inch, rightMargin=0.75 * inch,
    )

    # Every style below sets `leading` (line height) explicitly to roughly
    # 1.2-1.3x its fontSize -- reportlab's ParagraphStyle does NOT derive a
    # default leading from fontSize, it's a flat 12pt default regardless of
    # font size. Left unset, a style with fontSize noticeably above 12 (the
    # title at 20pt was the worst case, confirmed live) wraps onto a second
    # line that's spaced for a 12pt font, so the lines visually overlap --
    # harmless for text that happens to fit on one line, broken the moment
    # it doesn't (a long sheet title being the most common way to hit it).
    title_style = ParagraphStyle('Title', fontName='NotoLatin-Bold', fontSize=20, leading=24, alignment=TA_CENTER, spaceAfter=4)
    meta_style = ParagraphStyle('Meta', fontName='NotoLatin', fontSize=9, leading=12, textColor='#666666', alignment=TA_CENTER, spaceAfter=18)
    note_style = ParagraphStyle('Note', fontName='NotoLatin-Bold', fontSize=13, leading=16, spaceBefore=14, spaceAfter=6, textColor='#1a1a1a')
    source_title_style = ParagraphStyle('SourceTitle', fontName='NotoLatin-Bold', fontSize=12, leading=15, spaceBefore=16, spaceAfter=4, textColor='#333333')
    he_style = ParagraphStyle('Hebrew', fontName='NotoHebrew', fontSize=13, alignment=TA_RIGHT, leading=20, spaceAfter=6)
    en_style = ParagraphStyle('English', fontName='NotoLatin', fontSize=10.5, alignment=TA_LEFT, leading=15, spaceAfter=10, textColor='#333333')
    comment_style = ParagraphStyle('Comment', fontName='NotoLatin', fontSize=9.5, alignment=TA_LEFT, leading=13, textColor='#555555', leftIndent=10, spaceAfter=10)
    footer_style = ParagraphStyle('Footer', fontName='NotoLatin', fontSize=8, textColor='#999999', alignment=TA_CENTER, spaceBefore=24)

    flow = [
        Paragraph(sheet.title, title_style),
        Paragraph(
            f'By {sheet.creator.profile_name if sheet.creator else "Unknown"} &middot; Gut Torah source sheet',
            meta_style,
        ),
    ]

    for item in sheet.items:
        if item.item_type == 'note':
            flow.append(HRFlowable(width='100%', thickness=0.5, color='#cccccc', spaceBefore=4, spaceAfter=10))
            flow.append(Paragraph(_strip_html(item.note_text or item.custom_title or ''), note_style))
            continue

        flow.append(Paragraph(item.custom_title or item.ref or '', source_title_style))
        he_segs = item.he_text or []
        en_segs = item.en_text or []
        seg_count = max(len(he_segs), len(en_segs))
        for i in range(seg_count):
            if i < len(he_segs) and he_segs[i]:
                flow.append(Paragraph(_he_display(he_segs[i]), he_style))
            if i < len(en_segs) and en_segs[i]:
                flow.append(Paragraph(_strip_html(en_segs[i]), en_style))
        if item.note_text:
            flow.append(Paragraph(f'<i>Note: {_strip_html(item.note_text)}</i>', comment_style))

    flow.append(Paragraph('Source texts from Sefaria.org. Generated by Gut Torah.', footer_style))

    doc.build(flow)
    return buf.getvalue()


# ── Word (.docx) ─────────────────────────────────────────────────────────

def _set_rtl_paragraph(paragraph):
    pPr = paragraph._p.get_or_add_pPr()
    bidi = pPr.makeelement(qn('w:bidi'), {})
    pPr.append(bidi)


def _set_rtl_run(run, bold=False, size=13):
    run.font.size = Pt(size)
    run.bold = bold
    rPr = run._r.get_or_add_rPr()
    rtl = rPr.makeelement(qn('w:rtl'), {})
    rPr.append(rtl)
    # Word picks the glyph-rendering font for Hebrew from the "complex
    # script" (cs) font slot, not the regular/ascii one -- set both so it
    # doesn't fall back to a font with no Hebrew glyphs.
    rFonts = rPr.find(qn('w:rFonts'))
    if rFonts is None:
        rFonts = rPr.makeelement(qn('w:rFonts'), {})
        rPr.append(rFonts)
    rFonts.set(qn('w:cs'), 'Noto Sans Hebrew')
    rFonts.set(qn('w:ascii'), 'Noto Sans Hebrew')
    rFonts.set(qn('w:hAnsi'), 'Noto Sans Hebrew')


def build_docx(sheet):
    doc = Document()

    title = doc.add_heading(sheet.title, level=0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER

    meta = doc.add_paragraph(f'By {sheet.creator.profile_name if sheet.creator else "Unknown"} · Gut Torah source sheet')
    meta.alignment = WD_ALIGN_PARAGRAPH.CENTER
    meta.runs[0].font.size = Pt(9)

    for item in sheet.items:
        if item.item_type == 'note':
            p = doc.add_paragraph()
            run = p.add_run(_strip_html(item.note_text or item.custom_title or ''))
            run.bold = True
            run.font.size = Pt(13)
            continue

        heading = doc.add_paragraph()
        heading.add_run(item.custom_title or item.ref or '').bold = True

        he_segs = item.he_text or []
        en_segs = item.en_text or []
        seg_count = max(len(he_segs), len(en_segs))
        for i in range(seg_count):
            if i < len(he_segs) and he_segs[i]:
                p = doc.add_paragraph()
                p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
                _set_rtl_paragraph(p)
                run = p.add_run(_strip_html(he_segs[i]))
                _set_rtl_run(run, size=13)
            if i < len(en_segs) and en_segs[i]:
                p = doc.add_paragraph(_strip_html(en_segs[i]))
                p.runs[0].font.size = Pt(10.5)
        if item.note_text:
            p = doc.add_paragraph()
            run = p.add_run(f'Note: {_strip_html(item.note_text)}')
            run.italic = True
            run.font.size = Pt(9.5)

    footer = doc.add_paragraph('Source texts from Sefaria.org. Generated by Gut Torah.')
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    footer.runs[0].font.size = Pt(8)

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
