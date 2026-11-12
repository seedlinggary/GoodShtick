"""Connector for municipal arnona orders ("צו ארנונה") -- the one source
in this package that will never have an API, because it doesn't exist as
anything but a PDF each city publishes on its own site once a year. This
automates everything downstream of having that PDF's URL: fetching it,
extracting its text, and staging it -- nothing here guesses at rates
itself (see normalize.py's parse_arnona_candidates for that, kept
deliberately separate and low-confidence by design).

Finding THIS YEAR'S PDF link still needs a human the first time for each
city (discover_pdf_url below is a best-effort helper for that, not a
guarantee) -- municipal sites change their page structure often enough,
and are inconsistent enough between cities, that blindly trusting an
auto-discovered link for data that feeds a cost ESTIMATE would be worse
than asking once. Once a URL is known, ingest() needs no human again
until next year's order replaces it."""
import re
from datetime import datetime
from urllib.parse import urljoin

import requests
import pdfplumber
import io

from config import db
from backend.estates_data.modals.estates_data import RawIngestRecord

SOURCE = 'arnona_pdf'
TIMEOUT = 30


def discover_pdf_url(index_url, year=None):
    """Best-effort: fetches a municipality's own arnona page and returns
    PDF links whose href or link text mentions arnona ("ארנונה"),
    preferring ones that also mention `year` if given. Returns a list
    (most-likely-first), NOT a single guaranteed answer -- the caller
    (or an admin) should confirm before relying on the top result,
    especially the first time for a given city."""
    resp = requests.get(index_url, timeout=TIMEOUT)
    resp.raise_for_status()
    html = resp.text

    links = re.findall(r'<a[^>]+href=["\']([^"\']+\.pdf)["\'][^>]*>(.*?)</a>', html, re.IGNORECASE | re.DOTALL)
    candidates = []
    for href, link_text in links:
        text = re.sub(r'<[^>]+>', '', link_text)
        haystack = href + ' ' + text
        if 'ארנונה' not in haystack and 'arnona' not in haystack.lower():
            continue
        score = 1
        if year and str(year) in haystack:
            score += 2
        candidates.append((score, urljoin(index_url, href), text.strip()))

    candidates.sort(key=lambda c: -c[0])
    return [{'url': url, 'text': text} for _score, url, text in candidates]


def fetch_pdf_text(pdf_url):
    """Downloads the PDF and returns (full_text, tables) -- full_text is
    every page's extracted text joined with blank lines; tables is a
    list of pdfplumber's own extracted-table structures (a list of rows,
    each a list of cell strings, possibly containing None for empty
    cells) for whichever pages had anything pdfplumber recognized as a
    table. Both are kept in the raw payload untouched -- parsing them
    into actual rate rows is normalize.py's job, not this function's."""
    resp = requests.get(pdf_url, timeout=TIMEOUT)
    resp.raise_for_status()

    pages_text = []
    tables = []
    with pdfplumber.open(io.BytesIO(resp.content)) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ''
            pages_text.append(text)
            for table in (page.extract_tables() or []):
                tables.append(table)

    return '\n\n'.join(pages_text), tables


def ingest(municipality, year, pdf_url=None, index_url=None):
    """If `pdf_url` isn't given, tries discover_pdf_url(index_url, year)
    and uses its top candidate -- logged in the staged payload either
    way, so which URL was actually used is always visible later. Stages
    ONE RawIngestRecord per (municipality, year, pdf_url) -- re-running
    with the same URL is a no-op, not a duplicate; re-running with a
    different URL (e.g. next year's order) stages a new one. Returns the
    count of NEW rows staged (0 or 1)."""
    discovered_from = None
    if not pdf_url:
        if not index_url:
            raise ValueError('Either pdf_url or index_url is required')
        candidates = discover_pdf_url(index_url, year=year)
        if not candidates:
            raise ValueError(f'No arnona PDF link found on {index_url} -- supply pdf_url directly instead')
        pdf_url = candidates[0]['url']
        discovered_from = index_url

    text, tables = fetch_pdf_text(pdf_url)

    external_id = f'{municipality}:{year}:{pdf_url}'
    if RawIngestRecord.query.filter_by(source=SOURCE, external_id=external_id).first():
        return 0

    db.session.add(RawIngestRecord(source=SOURCE, external_id=external_id, payload={
        'municipality': municipality, 'year': year, 'pdf_url': pdf_url,
        'discovered_from': discovered_from, 'fetched_at': datetime.utcnow().isoformat(),
        'text': text, 'tables': tables,
    }))
    db.session.commit()
    return 1
