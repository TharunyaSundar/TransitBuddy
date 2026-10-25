"""Normalize and validate extracted schedules against the Course contract, collecting warnings for the student.

Nothing here saves anything: a schedule is only stored after the student confirms it.
"""
import re
from typing import Any

from ...shared.contracts import COURSE_WEEKDAYS as WEEKDAYS
from ...shared.validators import is_non_empty_string, is_valid_time_string, is_valid_weekday
from ...shared.validators import is_valid_course as is_valid_course_shared
from .timeutil import display, normalize_days, normalize_time, to_minutes

ONLINE = re.compile(r"\b(online|remote|zoom|icourse|asu online|sync|tba|tbd)\b", re.I)
COURSE_CODE = re.compile(r"^([A-Za-z]{2,4})\s*-?\s*(\d{3}[A-Za-z]?)\b")


def is_online(location: str) -> bool:
    return bool(ONLINE.search(location or ""))


def normalize_course_code(code: str) -> str:
    m = COURSE_CODE.match((code or "").strip())
    return f"{m.group(1).upper()} {m.group(2).upper()}" if m else (code or "").strip().upper()


def _patterns(raw: dict, label: str, warnings: list[str]) -> list[dict]:
    """Accept meeting_patterns, or days/start_time/end_time shorthand from the model."""
    out = []
    items = raw.get("meeting_patterns")
    if not items and (raw.get("days") or raw.get("start_time")):
        items = [{"days": raw.get("days"), "start_time": raw.get("start_time"), "end_time": raw.get("end_time")}]
    for p in items or []:
        days = normalize_days(p.get("day_of_week") or p.get("days") or "")
        start, end = normalize_time(p.get("start_time", "")), normalize_time(p.get("end_time", ""))
        if not days:
            warnings.append(f"{label}: couldn't read the meeting days.")
            continue
        if not start or not end:
            warnings.append(f"{label}: couldn't read the start or end time.")
            continue
        if to_minutes(end) <= to_minutes(start):
            warnings.append(f"{label}: ends ({end}) before it starts ({start}); please check AM/PM.")
            continue
        if to_minutes(start) < 6 * 60 or to_minutes(start) > 22 * 60:
            warnings.append(f"{label}: starts at {start}, which is unusual; please check AM/PM.")
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
    for i, c in enumerate(raw.get("courses") or [], 1):
        if not isinstance(c, dict):
            continue
        code = normalize_course_code(str(c.get("course_code") or ""))
        label = code or f"Course {i}"
        if not code:
            warnings.append(f"Course {i}: missing course code.")
        location = str(c.get("location") or "").strip()
        online = is_online(location)
        patterns = _patterns(c, label, warnings)
        if not patterns and not online:
            warnings.append(f"{label}: no meeting times found.")
        if not location:
            warnings.append(f"{label}: no location found.")
        courses.append({
            "course_code": code,
            "course_name": str(c.get("course_name") or "").strip(),
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
    slots = [(c["course_code"], p) for c in courses for p in c["meeting_patterns"]]
    for i, (a, pa) in enumerate(slots):
        for b, pb in slots[i + 1:]:
            if a != b and pa["day_of_week"] == pb["day_of_week"] and \
                    to_minutes(pa["start_time"]) < to_minutes(pb["end_time"]) and \
                    to_minutes(pb["start_time"]) < to_minutes(pa["end_time"]):
                warnings.append(f"{a} and {b} overlap on {pa['day_of_week']}; please check the times.")


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
    """[{course_code, start_time, end_time, location}] meeting on `day`, sorted, online classes excluded."""
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
