"""Normalize and validate extracted schedules against the Course contract, collecting warnings for the student.

Nothing here saves anything: a schedule is only stored after the student confirms it.
"""
import re
from typing import Any

from ...shared.contracts import COURSE_WEEKDAYS as WEEKDAYS
from ...shared.validators import is_non_empty_string, is_valid_time_string, is_valid_weekday
from ...shared.validators import is_valid_course as is_valid_course_shared
from .timeutil import display, normalize_days, normalize_time, to_minutes

ONLINE = re.compile(r"\b(online|remote|zoom|icourse|asu online|sync)\b", re.I)
UNKNOWN_ROOM = re.compile(r"\b(tba|tbd)\b", re.I)  # room not assigned yet: still an on-campus class
COURSE_CODE = re.compile(r"^([A-Za-z]{2,4})\s*-?\s*(\d{3}[A-Za-z]?)\b")


def is_online(location: str) -> bool:
    return bool(ONLINE.search(location or ""))


def normalize_course_code(code: str) -> str:
    m = COURSE_CODE.match((code or "").strip())
    return f"{m.group(1).upper()} {m.group(2).upper()}" if m else (code or "").strip().upper()


_RANGE = re.compile(r"^\s*(.+?)\s*(?:-|–|—|to)\s*(.+?)\s*$", re.I)
_MERIDIEM = re.compile(r"\b(am|pm|a\.m\.|p\.m\.)\s*$", re.I)


def _start_end(start_text: str, end_text: str) -> tuple[str | None, str | None]:
    """Start and end as HH:mm. Handles a whole range in one field ("10:00 - 10:50 AM") and a start without
    AM/PM, which takes the end's AM/PM unless that would put it after the end ("11:30 - 12:20 PM")."""
    for text in (start_text, end_text):
        m = _RANGE.match(text)
        if m and normalize_time(m.group(2)):
            start_text, end_text = m.group(1), m.group(2)
            break
    end = normalize_time(end_text)
    start = normalize_time(start_text)
    ap = _MERIDIEM.search(end_text)
    if end and start_text and not _MERIDIEM.search(start_text) and ap:
        same = normalize_time(f"{start_text} {ap.group(1)}")
        other = normalize_time(f"{start_text} {'am' if ap.group(1).lower().startswith('p') else 'pm'}")
        if same and to_minutes(same) < to_minutes(end):
            start = same
        elif other and to_minutes(other) < to_minutes(end):
            start = other
    return start, end


def _patterns(raw: dict, label: str, warnings: list[str]) -> list[dict]:
    """Accept meeting_patterns, or days/start_time/end_time shorthand from the model."""
    out = []
    items = raw.get("meeting_patterns")
    if not items and (raw.get("days") or raw.get("start_time")):
        items = [{"days": raw.get("days"), "start_time": raw.get("start_time"), "end_time": raw.get("end_time")}]
    for p in items or []:
        days = normalize_days(p.get("day_of_week") or p.get("days") or "")
        start, end = _start_end(str(p.get("start_time") or ""), str(p.get("end_time") or ""))
        if not days:
            warnings.append(f"{label}: couldn't read the meeting days.")
            continue
        if not start or not end:
            warnings.append(f"{label}: couldn't read the start or end time.")
            continue
        if to_minutes(end) <= to_minutes(start):
            warnings.append(f"{label}: ends ({display(end)}) before it starts ({display(start)}); please check the time.")
            continue
        if to_minutes(start) < 6 * 60 or to_minutes(start) > 22 * 60:
            warnings.append(f"{label}: starts at {display(start)}, which is unusual; please check AM/PM.")
        out += [{"day_of_week": d, "start_time": start, "end_time": end} for d in days]
    seen, unique = set(), []
    for p in out:
        k = (p["day_of_week"], p["start_time"], p["end_time"])
        if k not in seen:
            seen.add(k)
            unique.append(p)
    return sorted(unique, key=lambda p: (WEEKDAYS.index(p["day_of_week"]), p["start_time"]))


def normalize_schedule(raw: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Returns ({"semester", "courses": [Course]}, warnings)."""
    warnings: list[str] = []
    courses = []
    items = [c for c in raw.get("courses") or [] if isinstance(c, dict)]
    codes = [normalize_course_code(str(c.get("course_code") or "")) for c in items]
    for i, c in enumerate(items, 1):
        code = codes[i - 1]
        name = str(c.get("course_name") or "").strip()
        if code and name.upper().startswith(code):  # "CSE 110 Lab" -> "Lab"
            name = name[len(code):].strip(" -:") or name
        label = code or f"Course {i}"
        if code and codes.count(code) > 1 and name:  # two entries for one course: say which
            label = f"{code} ({name})"
        if not code:
            warnings.append(f"Course {i}: missing course code.")
        location = str(c.get("location") or "").strip()
        online = is_online(location) or (UNKNOWN_ROOM.search(location) is not None and not c.get("meeting_patterns"))
        patterns = _patterns(c, label, warnings)
        if not patterns and not online:
            warnings.append(f"{label}: no meeting times found.")
        if not location:
            warnings.append(f"{label}: no location found.")
        courses.append({
            "course_code": code,
            "course_name": name,
            "section": str(c.get("section") or "").strip(),
            "meeting_patterns": patterns,
            "location": location or "TBA",
        })
    if not courses:
        warnings.append("No classes found in the schedule.")
    _overlaps(courses, warnings)
    semester = str(raw.get("semester") or "").strip()
    if not semester:
        warnings.append("Semester not shown; please tell me which term this is (e.g. Fall 2026).")
    return {"semester": semester, "courses": courses}, warnings


def _overlaps(courses: list[dict], warnings: list[str]) -> None:
    """Warn about meeting times that overlap: two classes, or two times of the same class (a screenshot
    misread, or a real clash). One warning per pair of times, listing the days."""
    slots = [(c["course_code"], p) for c in courses for p in c["meeting_patterns"]]
    clashes: dict[tuple, list[str]] = {}
    for i, (a, pa) in enumerate(slots):
        for b, pb in slots[i + 1:]:
            same_time = (pa["start_time"], pa["end_time"]) == (pb["start_time"], pb["end_time"])
            if pa["day_of_week"] != pb["day_of_week"] or (a == b and same_time):
                continue
            if to_minutes(pa["start_time"]) < to_minutes(pb["end_time"]) and \
                    to_minutes(pb["start_time"]) < to_minutes(pa["end_time"]):
                times = tuple(sorted([(pa["start_time"], pa["end_time"]), (pb["start_time"], pb["end_time"])]))
                clashes.setdefault((a, b, times), []).append(pa["day_of_week"][:3])
    for (a, b, ((s1, e1), (s2, e2))), days in clashes.items():
        when = f"{display(s1)}-{display(e1)} and {display(s2)}-{display(e2)}"
        who = f"{a} has two meeting times that overlap" if a == b else f"{a} and {b} overlap"
        warnings.append(f"{who} on {'/'.join(dict.fromkeys(days))} ({when}); please check the times.")


def missing_for_save(c: dict) -> list[str]:
    """What DatabaseService.save_schedule (shared is_valid_course) would reject in this course."""
    missing = [label for key, label in (("course_code", "course code"), ("location", "location"))
               if not is_non_empty_string(c.get(key))]  # course_name and section are optional
    if not all(isinstance(p, dict) and is_valid_weekday(p.get("day_of_week")) and is_valid_time_string(p.get("start_time"))
               and is_valid_time_string(p.get("end_time")) for p in c.get("meeting_patterns") or []):
        missing.append("valid meeting times")
    return missing


def is_valid_course(c: dict) -> bool:
    return is_valid_course_shared(c)


def classes_on(schedule: dict | None, day: str) -> list[dict]:
    """[{course_code, start_time, end_time, location}] meeting on `day`, sorted. Online classes are excluded;
    a class whose room is TBA still counts (it meets on campus, the room just isn't known)."""
    out = []
    for c in (schedule or {}).get("courses", []):
        if is_online(c.get("location", "")):
            continue
        for p in c.get("meeting_patterns", []):
            if p["day_of_week"] == day:
                out.append({"course_code": c["course_code"], "start_time": p["start_time"], "end_time": p["end_time"],
                            "location": c.get("location", "")})
    return sorted(out, key=lambda x: x["start_time"])


def format_schedule(schedule: dict) -> str:
    """Discord-friendly list for the confirmation step."""
    lines = []
    if schedule.get("semester"):
        lines.append(f"**{schedule['semester']}**")
    for c in schedule.get("courses", []):
        by_time: dict[tuple, list[str]] = {}
        for p in c["meeting_patterns"]:
            by_time.setdefault((p["start_time"], p["end_time"]), []).append(p["day_of_week"][:3])
        when = "; ".join(f"{'/'.join(d)} {display(s)}-{display(e)}" for (s, e), d in by_time.items()) or "no set time"
        name = f" ({c['course_name']})" if c.get("course_name") else ""
        lines.append(f"- {c['course_code']}{name}: {when}, {c['location']}")
    return "\n".join(lines)
