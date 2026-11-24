"""Parsing and validation for the bulk need upload (CSV).

Pure logic: no database and no web framework, so it can be tested on its own. The rules deliberately mirror
``schemas.NeedCreate`` so a bulk import can never accept something the single-need API would reject.
The router re-validates on the server at import time; a preview shown earlier is never trusted.
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

MAX_BYTES = 1_000_000
MAX_ROWS = 500
URGENCY = ("low", "medium", "high", "critical")
INT_MAX = 2_147_483_647   # PostgreSQL INTEGER limit; larger values would otherwise surface as a server error

TEMPLATE_HEADERS = ["title", "category", "quantity", "urgency", "description", "required_by", "location", "beneficiaries", "organization_id"]
REQUIRED = ("category", "quantity")
KNOWN = set(TEMPLATE_HEADERS)
ALIASES = {
    "priority": "urgency", "need_title": "title", "name": "title", "required_date": "required_by", "due_date": "required_by",
    "notes": "description", "qty": "quantity", "org_id": "organization_id",
}
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_SPACES = re.compile(r"[ \t]+")


class BulkError(ValueError):
    """The file as a whole cannot be processed (wrong format, too large, missing columns)."""


@dataclass
class Record:
    row: int                      # 1-based data row (the header is not counted)
    line: int                     # last physical line of the record in the file
    cells: dict[str, str]
    extra: list[str] = field(default_factory=list)


@dataclass
class RowResult:
    row: int
    line: int
    data: dict[str, Any] | None
    errors: list[str]
    duplicate_of: int | None = None

    @property
    def status(self) -> str:
        if self.errors:
            return "invalid"
        return "duplicate" if self.duplicate_of else "valid"


def _norm_header(name: str) -> str:
    key = re.sub(r"[^a-z0-9]+", "_", (name or "").strip().lower().lstrip("\ufeff")).strip("_")
    return ALIASES.get(key, key)


def parse_csv(text: str) -> tuple[list[str], list[Record], dict[str, Any]]:
    """Split CSV text into records. Returns (headers, records, info). Raises ``BulkError`` for file-level problems."""
    if text is None or not text.strip():
        raise BulkError("The file is empty.")
    if len(text.encode("utf-8", errors="ignore")) > MAX_BYTES:
        raise BulkError(f"The file is larger than {MAX_BYTES // 1000} KB. Split it into smaller files.")
    if "\x00" in text:
        raise BulkError("This does not look like a text CSV file.")
    text = text.lstrip("\ufeff")
    reader = csv.reader(io.StringIO(text, newline=""))
    try:
        raw_header = next(reader)
    except (StopIteration, csv.Error) as exc:
        raise BulkError("Could not read the header row.") from exc
    if len(raw_header) == 1 and any(sep in raw_header[0] for sep in (";", "\t", "|")):
        raise BulkError("Use a comma-separated file (CSV). This file seems to use ; tabs or | between columns.")
    headers = [_norm_header(h) for h in raw_header]
    named = [h for h in headers if h]
    if len(named) != len(set(named)):
        raise BulkError("Two columns have the same name after cleaning. Rename the duplicate column.")
    missing = [c for c in REQUIRED if c not in headers]
    if missing:
        raise BulkError("Missing required column(s): " + ", ".join(missing) + ". Download the template to see the layout.")
    ignored = sorted({h for h in headers if h and h not in KNOWN})

    records: list[Record] = []
    blank = 0
    try:
        for cells in reader:
            if not cells or not any((c or "").strip() for c in cells):
                blank += 1
                continue
            if len(records) >= MAX_ROWS:
                raise BulkError(f"Too many rows. The limit is {MAX_ROWS} needs per upload; split the file.")
            mapped = {h: (cells[i] if i < len(cells) else "") for i, h in enumerate(headers) if h}
            extra = [c for c in cells[len(headers):] if (c or "").strip()]
            records.append(Record(row=len(records) + 1, line=reader.line_num, cells=mapped, extra=extra))
    except csv.Error as exc:
        raise BulkError(f"The file is not valid CSV near line {reader.line_num}: {exc}") from exc
    if not records:
        raise BulkError("The file has a header but no data rows.")
    return headers, records, {"ignored_columns": ignored, "blank_rows_ignored": blank}


def _clean(value: str | None, multiline: bool = False) -> str:
    text = _CONTROL.sub("", value or "")
    if multiline:
        text = "\n".join(_SPACES.sub(" ", line).strip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"))
        return text.strip()
    return _SPACES.sub(" ", text.replace("\r", " ").replace("\n", " ")).strip()


def _int(text: str, label: str, errors: list[str], low: int = 0, high: int = INT_MAX) -> int | None:
    if not re.fullmatch(r"\d+", text):
        errors.append(f"{label} must be a whole number (digits only), got “{text[:30]}”.")
        return None
    number = int(text)
    if number < low or number > high:
        errors.append(f"{label} must be between {low} and {high}.")
        return None
    return number


def _date(text: str, errors: list[str]) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        errors.append("required_by must be an ISO date like 2026-12-31 (or 2026-12-31 18:00).")
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    if not 2000 <= parsed.year <= 2100:
        errors.append("required_by must be a year between 2000 and 2100.")
        return None
    return parsed


def dedupe_key(data: dict[str, Any]) -> tuple:
    due = data.get("required_by")
    return (data.get("org_id"), (data.get("title") or "").lower(), (data.get("category") or "").lower(), due.date() if due else None)


def validate(records: list[Record], *, is_admin: bool, own_org_id: int | None, default_org_id: int | None = None,
             known_org_ids: set[int] | None = None) -> list[RowResult]:
    """Validate every record. Invalid rows are returned with their reasons; nothing is dropped silently."""
    results: list[RowResult] = []
    seen: dict[tuple, int] = {}
    for rec in records:
        errors: list[str] = []
        c = rec.cells
        if rec.extra:
            errors.append("This row has more values than the header has columns (check for an unquoted comma).")

        category = _clean(c.get("category"))
        if not category:
            errors.append("category is required.")
        elif len(category) > 200:
            errors.append("category must be 200 characters or fewer.")

        qty_text = _clean(c.get("quantity"))
        quantity = _int(qty_text, "quantity", errors) if qty_text else (errors.append("quantity is required.") or None)

        urgency_text = _clean(c.get("urgency")).lower() or "medium"
        if urgency_text not in URGENCY:
            errors.append("urgency must be one of: " + ", ".join(URGENCY) + ".")
            urgency_text = None

        title = _clean(c.get("title")) or None
        if title and len(title) > 200:
            errors.append("title must be 200 characters or fewer.")
        description = _clean(c.get("description"), multiline=True) or None
        if description and len(description) > 4000:
            errors.append("description must be 4000 characters or fewer.")
        location = _clean(c.get("location")) or None
        if location and len(location) > 200:
            errors.append("location must be 200 characters or fewer.")

        beneficiaries = None
        ben_text = _clean(c.get("beneficiaries"))
        if ben_text:
            beneficiaries = _int(ben_text, "beneficiaries", errors, 0, 100000)

        required_by = None
        due_text = _clean(c.get("required_by"))
        if due_text:
            required_by = _date(due_text, errors)

        org_text = _clean(c.get("organization_id"))
        org_id: int | None
        if not is_admin:
            if own_org_id is None:
                errors.append("Your account is not linked to an organization.")
            if org_text and org_text != str(own_org_id):
                errors.append("You can only upload needs for your own organization; leave organization_id empty.")
            org_id = own_org_id
        else:
            org_id = None
            if org_text:
                org_id = _int(org_text, "organization_id", errors, 1)
            elif default_org_id is not None:
                org_id = default_org_id
            else:
                errors.append("organization_id is required (or pick a default organization for the upload).")
            if org_id is not None and known_org_ids is not None and org_id not in known_org_ids:
                errors.append(f"Organization {org_id} does not exist.")

        data = None
        dup = None
        if not errors:
            data = {"org_id": org_id, "category": category, "quantity": quantity, "urgency": urgency_text, "title": title,
                    "description": description, "required_by": required_by, "location": location, "beneficiaries": beneficiaries}
            key = dedupe_key(data)
            if key in seen:
                dup = seen[key]
            else:
                seen[key] = rec.row
        results.append(RowResult(row=rec.row, line=rec.line, data=data, errors=errors, duplicate_of=dup))
    return results


def template_csv() -> str:
    """A small, safe example file users can download and fill in."""
    rows = [
        ["Winter blankets", "Clothing", "40", "high", "Warm blankets for the girls' hostel", "2026-12-15", "Tirupati", "40", ""],
        ["School notebooks", "Education", "200", "medium", "Notebooks for the new term", "2027-01-10", "Tirupati", "60", ""],
        ["Rice (25 kg bags)", "Food", "12", "critical", "Monthly grain stock", "", "Tirupati", "", ""],
    ]
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\r\n")
    writer.writerow(TEMPLATE_HEADERS)
    writer.writerows(rows)
    return out.getvalue()
