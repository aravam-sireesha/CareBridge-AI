"""Volunteer availability and carrying capacity. Pure Python (tests/test_availability.py).

Definitions (so nobody has to guess):
* Availability = a WEEKLY schedule: slots of (weekday 0=Monday..6=Sunday, start "HH:MM", end "HH:MM"), same-day only, in the
  volunteer's own timezone. A slot that crosses midnight is entered as two slots. No slots means "not stated", never "always free".
* Carrying capacity = the weight (kg) of donated items the volunteer can carry in ONE trip. It is not passenger seats. It is
  declared by the volunteer and is NOT verified; screens must say so.
* Unknown never excludes. A volunteer is ruled out only when they declared hours that do not cover the time, or a capacity below the load.
* Free text in the old `availability` column is never silently turned into slots: `suggest_from_text` only PROPOSES slots.
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Optional

try:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
except ImportError:                                  # pragma: no cover (Python < 3.9)
    ZoneInfo = None
    ZoneInfoNotFoundError = Exception

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
TRANSPORT_MODES = ("walking", "bicycle", "motorbike", "car", "van")
MAX_SLOTS, MIN_SLOT_MINUTES, MAX_CAPACITY_KG = 28, 15, 5000.0
CONFLICT_WINDOW_MINUTES = 120


class AvailabilityError(ValueError):
    """A message that is safe to show to the person editing their availability."""


def default_timezone() -> str:
    return os.getenv("APP_TIMEZONE", "Asia/Kolkata")


def _tz(name: str):
    if ZoneInfo is None:
        return None
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, KeyError):
        return None


def parse_clock(value: Any) -> int:
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", str(value or "").strip())
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        raise AvailabilityError("Times must look like 09:30 (24-hour clock).")
    return int(m.group(1)) * 60 + int(m.group(2))


def clock(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def validate_slots(raw: Any) -> list[dict]:
    """Normalise and check a weekly schedule. Returns a sorted list of {weekday, start, end}."""
    if raw is None:
        return []
    if not isinstance(raw, (list, tuple)):
        raise AvailabilityError("Availability must be a list of time slots.")
    if len(raw) > MAX_SLOTS:
        raise AvailabilityError(f"Please keep it to {MAX_SLOTS} time slots or fewer.")
    slots = []
    for i, item in enumerate(raw, 1):
        if not isinstance(item, dict):
            raise AvailabilityError(f"Slot {i} is not valid.")
        wd = item.get("weekday")
        if isinstance(wd, bool) or not isinstance(wd, int) or not 0 <= wd <= 6:
            raise AvailabilityError(f"Slot {i}: choose a weekday.")
        start, end = parse_clock(item.get("start")), parse_clock(item.get("end"))
        if end <= start:
            raise AvailabilityError(f"Slot {i} ({WEEKDAYS[wd]}): the end must be after the start. For a night shift, enter two slots, one ending at 23:59 and one starting at 00:00 the next day.")
        if end - start < MIN_SLOT_MINUTES:
            raise AvailabilityError(f"Slot {i} ({WEEKDAYS[wd]}): a slot must be at least {MIN_SLOT_MINUTES} minutes long.")
        slots.append({"weekday": wd, "start": start, "end": end})
    slots.sort(key=lambda s: (s["weekday"], s["start"]))
    for a, b in zip(slots, slots[1:]):
        if a["weekday"] == b["weekday"] and b["start"] < a["end"]:
            raise AvailabilityError(f"{WEEKDAYS[a['weekday']]}: the slots {clock(a['start'])}-{clock(a['end'])} and {clock(b['start'])}-{clock(b['end'])} overlap.")
    return [{"weekday": s["weekday"], "start": clock(s["start"]), "end": clock(s["end"])} for s in slots]


def validate_profile(timezone_name: Optional[str], transport_mode: Optional[str], capacity_kg: Any) -> tuple[Optional[str], Optional[str], Optional[float]]:
    tz = (timezone_name or "").strip() or None
    if tz is not None and _tz(tz) is None:
        raise AvailabilityError("That timezone is not recognised. Use a name such as Asia/Kolkata.")
    mode = (transport_mode or "").strip().lower() or None
    if mode is not None and mode not in TRANSPORT_MODES:
        raise AvailabilityError("Choose how you travel: " + ", ".join(TRANSPORT_MODES) + ".")
    cap = None
    if capacity_kg not in (None, ""):
        if isinstance(capacity_kg, bool):
            raise AvailabilityError("Capacity must be a number of kilograms.")
        try:
            cap = float(capacity_kg)
        except (TypeError, ValueError):
            raise AvailabilityError("Capacity must be a number of kilograms.") from None
        if not (cap == cap) or cap <= 0 or cap > MAX_CAPACITY_KG:
            raise AvailabilityError(f"Capacity must be above 0 and at most {MAX_CAPACITY_KG:g} kg.")
    return tz, mode, cap


def is_available(slots: Optional[list], tz_name: Optional[str], when_utc: datetime) -> Optional[bool]:
    """True / False when the volunteer declared a schedule; None when they have not (unknown, never 'free')."""
    if not slots:
        return None
    tz = _tz(tz_name or default_timezone())
    if tz is None:
        return None                                   # cannot interpret the timezone here: say "unknown", never guess
    local = when_utc.replace(tzinfo=timezone.utc).astimezone(tz)
    minute = local.hour * 60 + local.minute
    return any(s["weekday"] == local.weekday() and parse_clock(s["start"]) <= minute < parse_clock(s["end"]) for s in slots)


def capacity_status(load_kg: Optional[float], capacity_kg: Optional[float]) -> str:
    if not load_kg or not capacity_kg:
        return "unknown"
    return "ok" if load_kg <= capacity_kg else "exceeds"


def has_conflict(existing: Iterable[datetime], new: datetime, window_minutes: int = CONFLICT_WINDOW_MINUTES) -> Optional[datetime]:
    """The first existing pickup within the window of the new one (a volunteer cannot be in two places), or None."""
    for e in existing:
        if e is not None and abs((e - new).total_seconds()) < window_minutes * 60:
            return e
    return None


def assess(slots: Optional[list], tz_name: Optional[str], capacity_kg: Optional[float], when_utc: Optional[datetime] = None, load_kg: Optional[float] = None) -> dict:
    """One volunteer against one job. {available: True|False|None, capacity: ok|exceeds|unknown, exclude, reasons}"""
    out = {"available": None, "capacity": "unknown", "exclude": False, "reasons": []}
    if when_utc is not None:
        out["available"] = is_available(slots, tz_name, when_utc)
        if out["available"] is True:
            out["reasons"].append("Declared availability covers the pickup time")
        elif out["available"] is False:
            out["exclude"] = True
            out["reasons"].append("Outside the hours they declared")
        else:
            out["reasons"].append("Availability not stated, so it could not be checked")
    out["capacity"] = capacity_status(load_kg, capacity_kg)
    if out["capacity"] == "ok":
        out["reasons"].append(f"Declared capacity of {capacity_kg:g} kg covers the {load_kg:g} kg load (self-declared, not verified)")
    elif out["capacity"] == "exceeds":
        out["exclude"] = True
        out["reasons"].append(f"The {load_kg:g} kg load is above the {capacity_kg:g} kg they said they can carry")
    elif load_kg:
        out["reasons"].append("Carrying capacity not stated, so it could not be checked")
    return out


# --------------------------------------------------------------------------- migrating free text: suggestions only
_DAYS = {"mon": 0, "monday": 0, "tue": 1, "tues": 1, "tuesday": 1, "wed": 2, "wednesday": 2, "thu": 3, "thur": 3, "thurs": 3, "thursday": 3, "fri": 4, "friday": 4, "sat": 5, "saturday": 5, "sun": 6, "sunday": 6}
_PARTS = {"morning": ("08:00", "12:00"), "mornings": ("08:00", "12:00"), "afternoon": ("12:00", "17:00"), "afternoons": ("12:00", "17:00"), "evening": ("17:00", "21:00"), "evenings": ("17:00", "21:00")}


def suggest_from_text(text: Optional[str]) -> dict:
    """PROPOSE slots from old free text such as "weekends", "weekday evenings", "Sat mornings". Never saved automatically.
    The hours are ordinary defaults, not facts about the person, which is why the result is labelled a suggestion."""
    t = (text or "").lower()
    words = set(re.findall(r"[a-z]+", t))
    days: set[int] = set()
    if words & {"weekend", "weekends"}:
        days |= {5, 6}
    if words & {"weekday", "weekdays"}:
        days |= {0, 1, 2, 3, 4}
    if words & {"anytime", "flexible", "daily", "everyday", "fulltime"} or "full time" in t or "any day" in t or "every day" in t:
        days |= set(range(7))
    days |= {_DAYS[w] for w in words if w in _DAYS}
    part = next((_PARTS[w] for w in _PARTS if w in words), None)
    if not days or ("unavailable" in words or "none" in words or "never" in words):
        return {"slots": [], "note": "Nothing could be suggested from that text. Add your times yourself.", "source_text": text or ""}
    start, end = part or ("09:00", "18:00")
    slots = [{"weekday": d, "start": start, "end": end} for d in sorted(days)]
    note = "Suggested from your earlier text" + ("" if part else ", using 09:00 to 18:00 because no time of day was given") + ". Nothing is saved until you confirm it."
    return {"slots": slots, "note": note, "source_text": text}
