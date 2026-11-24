"""Tachlis (Gut Money) emails -- built from the same shared shell as
backend/alerts/emails.py and backend/giveaways/emails.py (_wrap/_button/
_kicker/_section/_footer_link/_client), not a separate template system."""
from collections import Counter
from html import escape

from backend.alerts.emails import _client, _wrap, _kicker, _section, MUTED, BORDER

SOURCE_LABELS = {
    'arbeitnow': 'Arbeitnow', 'remoteok': 'Remote OK',
    'jobicy': 'Jobicy', 'alljobs': 'AllJobs.co.il',
}


def _top_n(counter, n=5):
    return counter.most_common(n) if counter else []


def _bar_row(label, count, total):
    pct = round(100 * count / total) if total else 0
    return (
        f'<tr><td style="padding:3px 10px 3px 0;color:{MUTED};font-size:13px;white-space:nowrap;">{escape(str(label))}</td>'
        f'<td style="padding:3px 0;width:100%;"><div style="background:{BORDER};border-radius:4px;height:8px;width:100%;">'
        f'<div style="background:#15332c;border-radius:4px;height:8px;width:{max(pct,3)}%;"></div></div></td>'
        f'<td style="padding:3px 0 3px 10px;font-size:13px;font-weight:600;white-space:nowrap;">{count}</td></tr>'
    )


def send_job_scraper_summary_email(to_email, results):
    """One daily email after /tachlis/scrape/cron/run-all finishes --
    total pulled, a per-source breakdown, remote vs. on-site in Israel,
    how many were excluded as restricted to some other single country
    (not doable from Israel), and the top categories/locations added
    today. `results` is the same {source: _run_source(...)} dict the cron
    endpoint itself returns."""
    resend, from_header = _client()

    total_added = sum(r.get('added', 0) for r in results.values())
    total_checked = sum(r.get('checked', 0) for r in results.values())
    total_excluded = sum(r.get('excluded_restricted', 0) for r in results.values())
    total_remote = sum(r.get('remote_count', 0) for r in results.values())
    total_onsite = sum(r.get('onsite_count', 0) for r in results.values())

    combined_categories = Counter()
    combined_locations = Counter()
    for r in results.values():
        combined_categories.update(r.get('category_counts') or {})
        combined_locations.update(r.get('location_counts') or {})

    source_rows = ''.join(
        f'<tr><td style="padding:4px 10px 4px 0;font-size:13px;">{escape(SOURCE_LABELS.get(source, source))}</td>'
        f'<td style="padding:4px 10px;font-size:13px;font-weight:600;">{r.get("added", "—") if "error" not in r else "failed"}</td>'
        f'<td style="padding:4px 10px;font-size:13px;color:{MUTED};">{r.get("checked", "—")}</td>'
        f'<td style="padding:4px 0;font-size:13px;color:{MUTED};">{escape(r.get("error") or r.get("stopped_reason") or "")}</td></tr>'
        for source, r in results.items()
    )

    remote_vs_onsite = (
        _bar_row('Remote', total_remote, total_remote + total_onsite) +
        _bar_row('In Israel', total_onsite, total_remote + total_onsite)
    ) if (total_remote + total_onsite) else ''

    category_rows = ''.join(_bar_row(name, count, total_added) for name, count in _top_n(combined_categories))
    location_rows = ''.join(_bar_row(name, count, total_added) for name, count in _top_n(combined_locations))

    sections = (
        _kicker("Today's job board pull") +
        f'<p style="margin:0 0 4px;font-size:22px;font-weight:700;">{total_added} new job{"s" if total_added != 1 else ""} added</p>'
        f'<p style="margin:0;color:{MUTED};font-size:13px;">'
        f'{total_checked} checked across {len(results)} sources &middot; '
        f'{total_excluded} excluded (restricted to a country other than Israel)</p>'
        +
        _section(
            '<table role="presentation" cellpadding="0" cellspacing="0" style="width:100%;">'
            f'<tr><td style="font-size:12px;font-weight:700;color:{MUTED};padding-bottom:6px;">SOURCE</td>'
            f'<td style="font-size:12px;font-weight:700;color:{MUTED};padding-bottom:6px;">ADDED</td>'
            f'<td style="font-size:12px;font-weight:700;color:{MUTED};padding-bottom:6px;">CHECKED</td>'
            f'<td style="font-size:12px;font-weight:700;color:{MUTED};padding-bottom:6px;">NOTE</td></tr>'
            f'{source_rows}</table>'
        )
    )

    if remote_vs_onsite:
        sections += (
            f'<p style="margin:18px 0 6px;font-size:13px;font-weight:700;">Remote vs. in Israel</p>'
            f'<table role="presentation" cellpadding="0" cellspacing="0" style="width:100%;">{remote_vs_onsite}</table>'
        )
    if category_rows:
        sections += (
            f'<p style="margin:18px 0 6px;font-size:13px;font-weight:700;">Top categories added today</p>'
            f'<table role="presentation" cellpadding="0" cellspacing="0" style="width:100%;">{category_rows}</table>'
        )
    if location_rows:
        sections += (
            f'<p style="margin:18px 0 6px;font-size:13px;font-weight:700;">Top locations added today</p>'
            f'<table role="presentation" cellpadding="0" cellspacing="0" style="width:100%;">{location_rows}</table>'
        )

    html = _wrap(sections, preheader=f'{total_added} new jobs added to the Gut Money job board today')
    resend.Emails.send({
        'from': from_header, 'to': [to_email],
        'subject': f'Gut Money job board: {total_added} new jobs today',
        'html': html,
    })
