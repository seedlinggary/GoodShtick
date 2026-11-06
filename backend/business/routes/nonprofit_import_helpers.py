"""Shared helpers for the nonprofit module's admin routes -- CSV export
(every list page across Donations/Memberships/Payment Links/Other
Transactions/Holiday Signups/Form Responses uses this one function)."""
import csv
import io

from flask import Response


def csv_response(header, rows, filename):
    """UTF-8 BOM-prefixed so Excel renders Hebrew (and any other non-
    ASCII) text correctly instead of mangling it -- same convention the
    ported system's own lib/csv.ts uses, confirmed necessary for Excel
    specifically (not needed for most other CSV consumers, but Excel is
    the realistic audience for a nonprofit's own finance exports)."""
    buffer = io.StringIO()
    buffer.write('﻿')
    writer = csv.writer(buffer)
    writer.writerow(header)
    writer.writerows(rows)
    return Response(
        buffer.getvalue(), mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'},
    )
