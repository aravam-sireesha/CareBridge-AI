"""CSV helpers for downloadable reports.

Any cell that starts with ``= + - @`` (or a tab / carriage return) can be executed as a formula when a CSV is opened in
Excel, LibreOffice or Google Sheets ("CSV injection"). ``csv_safe`` prefixes such text with an apostrophe so it is shown
as plain text. Real numbers are left alone: a Python ``int``/``float`` can only ever contain digits, ``-``, ``.`` and ``e``.

This module has no database or web-framework imports, so it can be tested on its own.
"""
from __future__ import annotations

import csv
import io
import math
from datetime import date, datetime
from typing import Any, Iterable, Sequence

_FORMULA_TRIGGERS = ("=", "+", "-", "@", "\t", "\r", "\n")
# Characters that could be hidden in front of a trigger to dodge a naive check.
_LEADING_NOISE = " \u00a0\u200b\ufeff"
MAX_REPORT_ROWS = 50_000


def csv_safe(value: Any) -> Any:
    """Return a value that spreadsheet software will treat as data, never as a formula."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return "" if (math.isnan(value) or math.isinf(value)) else value
    if isinstance(value, datetime):
        return value.replace(microsecond=0).isoformat(sep=" ")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, (list, tuple, set)):
        value = "; ".join(str(v) for v in value)
    text = str(value)
    probe = text.lstrip(_LEADING_NOISE)
    if probe and probe[0] in _FORMULA_TRIGGERS:
        return "'" + text
    return text


def build_report(title: str, generated_at: datetime, filters: dict[str, Any], headers: Sequence[str],
                 rows: Iterable[Sequence[Any]], include_meta: bool = True) -> str:
    """Render a report as CSV text (UTF-8 with a BOM so Excel shows non-Latin names correctly).

    Every cell, including the metadata and the echoed filter values, goes through ``csv_safe``.
    """
    buf = io.StringIO()
    buf.write("\ufeff")
    writer = csv.writer(buf, lineterminator="\r\n")
    if include_meta:
        writer.writerow([csv_safe("Report"), csv_safe(title)])
        writer.writerow([csv_safe("Generated (UTC)"), csv_safe(generated_at)])
        shown = "; ".join(f"{k}={v}" for k, v in filters.items() if v not in (None, "")) or "none"
        writer.writerow([csv_safe("Filters"), csv_safe(shown)])
        writer.writerow([])
    writer.writerow([csv_safe(h) for h in headers])
    count = 0
    for row in rows:
        writer.writerow([csv_safe(cell) for cell in row])
        count += 1
    if include_meta:
        writer.writerow([])
        writer.writerow([csv_safe("Rows"), count])
    return buf.getvalue()
