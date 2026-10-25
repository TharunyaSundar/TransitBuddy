"""Time helpers. Times are HH:mm strings (24-hour) as in the contracts; Arizona is always UTC-7 (no DST)."""
import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from ..contracts import WEEKDAYS

DEFAULT_TZ = "America/Phoenix"

_DAY_ALIASES = {
    "m": 0, "mo": 0, "mon": 0, "monday": 0,
    "t": 1, "tu": 1, "tue": 1, "tues": 1, "tuesday": 1,
    "w": 2, "we": 2, "wed": 2, "wednesday": 2,
    "r": 3, "th": 3, "thu": 3, "thur": 3, "thurs": 3, "thursday": 3,
    "f": 4, "fr": 4, "fri": 4, "friday": 4,
    "sa": 5, "sat": 5, "saturday": 5,
    "su": 6, "sun": 6, "sunday": 6,
}


def now(tz: str = DEFAULT_TZ) -> datetime:
    return datetime.now(ZoneInfo(tz))


def to_minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def from_minutes(minutes: int) -> str:
    minutes = max(0, min(minutes, 24 * 60 - 1))
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def display(hhmm: str) -> str:
    """'14:05' -> '2:05 PM'"""
    h, m = to_minutes(hhmm) // 60, to_minutes(hhmm) % 60
    return f"{h % 12 or 12}:{m:02d} {'AM' if h < 12 else 'PM'}"


def normalize_time(text: str) -> str | None:
    """'2:00 PM', '2pm', '14:00', '9:30am', '0930' -> 'HH:mm'; None if unreadable."""
    s = str(text).strip().lower().replace(".", "")
    m = re.fullmatch(r"(\d{1,2})(?::?(\d{2}))?\s*(am|pm|a|p)?", s)
    if not m:
        return None
    h, mi, ap = int(m.group(1)), int(m.group(2) or 0), m.group(3)
    if ap:
        if not 1 <= h <= 12:
            return None
        h = h % 12 + (12 if ap.startswith("p") else 0)
    if h > 23 or mi > 59:
        return None
    return f"{h:02d}:{mi:02d}"


def normalize_days(text: str | list) -> list[str]:
    """'Mon/Wed/Fri', 'MWF', 'TTh', 'Tuesday', ['Mon','Wed'] -> ['Monday', ...]. Unknown parts are dropped."""
    if isinstance(text, list):
        out = []
        for t in text:
            out += normalize_days(t)
        return [d for d in WEEKDAYS if d in out]
    s = str(text).strip().lower()
    parts = [p for p in re.split(r"[\s/,&+]+|\band\b", s) if p]
    found = set()
    if parts and all(p in _DAY_ALIASES for p in parts):
        found = {_DAY_ALIASES[p] for p in parts}
    elif re.fullmatch(r"(th|tu|sa|su|[mtwrf])+", s.replace(" ", "")):  # compact: MWF, TTh, TR
        for tok in re.findall(r"th|tu|sa|su|[mtwrf]", s.replace(" ", "")):
            found.add(_DAY_ALIASES[tok])
    return [WEEKDAYS[i] for i in sorted(found)]


def parse_window(window: str) -> tuple[int, int] | None:
    """'08:00-09:00' or '8am - 9am' -> (480, 540)."""
    if not window:
        return None
    parts = re.split(r"\s*(?:-|–|to)\s*", str(window).strip())
    if len(parts) != 2:
        return None
    a, b = normalize_time(parts[0]), normalize_time(parts[1])
    if not a or not b or to_minutes(b) < to_minutes(a):
        return None
    return to_minutes(a), to_minutes(b)


def resolve_day(text: str | None, ref: datetime) -> str:
    """'today', 'tomorrow', 'monday', '2026-10-26' -> weekday name (defaults to today)."""
    s = (text or "today").strip().lower()
    if s in ("today", "now", ""):
        return WEEKDAYS[ref.weekday()]
    if s == "tomorrow":
        return WEEKDAYS[(ref.weekday() + 1) % 7]
    days = normalize_days(s)
    if len(days) == 1:
        return days[0]
    try:
        return WEEKDAYS[date.fromisoformat(s).weekday()]
    except ValueError:
        raise ValueError(f"can't read the day {text!r}; use e.g. tomorrow, Monday or 2026-10-26")


def next_date_for(day: str, ref: datetime) -> date:
    ahead = (WEEKDAYS.index(day) - ref.weekday()) % 7
    return ref.date() + timedelta(days=ahead)
