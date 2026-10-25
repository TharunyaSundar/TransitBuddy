"""Normalize and validate extracted schedules against the Course contract, collecting warnings for the student.

Nothing here saves anything: a schedule is only stored after the student confirms it.
"""
import re
from typing import Any

from ..contracts import WEEKDAYS
from .timeutil import display, normalize_days, normalize_time, to_minutes

ONLINE = re.compile(r"\b(online|remote|zoom|icourse|asu online|sync|tba|tbd)\b", re.I)
COURSE_CODE = re.compile(r"^([A-Za-z]{2,4})\s*-?\s*(\d{3}[A-Za-z]?)\b")


def is_online(location: str) -> bool:
    return bool(ONLINE.search(location or ""))


def normalize_course_code(code: str) -> str:
    m = COURSE_CODE.match((code or "").strip())
    return f"{m.group(1).upper()} {m.group(2).upper()}" if m else (code or "").strip().upper()


def _patterns(raw: dict, label: str, warnings: list[str]) -> list[dict]:
    """Accept meetingPatterns, or days/startTime/endTime shorthand from the model."""
    out = []
    items = raw.get("meetingPatterns")
    if not items and (raw.get("days") or raw.get("startTime")):
        items = [{"days": raw.get("days"), "startTime": raw.get("startTime"), "endTime": raw.get("endTime")}]
    for p in items or []:
        days = normalize_days(p.get("dayOfWeek") or p.get("days") or "")
        start, end = normalize_time(p.get("startTime", "")), normalize_time(p.get("endTime", ""))
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
        out += [{"dayOfWeek": d, "startTime": start, "endTime": end} for d in days]
    seen, unique = set(), []
    for p in out:
        k = (p["dayOfWeek"], p["startTime"], p["endTime"])
        if k not in seen:
            seen.add(k)
            unique.append(p)
    return sorted(unique, key=lambda p: (WEEKDAYS.index(p["dayOfWeek"]), p["startTime"]))


def normalize_schedule(raw: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Returns ({"semester", "courses": [Course]}, warnings)."""
    warnings: list[str] = []
    courses = []
    for i, c in enumerate(raw.get("courses") or [], 1):
        if not isinstance(c, dict):
            continue
        code = normalize_course_code(str(c.get("courseCode") or ""))
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
            "courseCode": code,
            "courseName": str(c.get("courseName") or "").strip(),
            "section": str(c.get("section") or "").strip(),
            "meetingPatterns": patterns,
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
    slots = [(c["courseCode"], p) for c in courses for p in c["meetingPatterns"]]
    for i, (a, pa) in enumerate(slots):
        for b, pb in slots[i + 1:]:
            if a != b and pa["dayOfWeek"] == pb["dayOfWeek"] and \
                    to_minutes(pa["startTime"]) < to_minutes(pb["endTime"]) and \
                    to_minutes(pb["startTime"]) < to_minutes(pa["endTime"]):
                warnings.append(f"{a} and {b} overlap on {pa['dayOfWeek']}; please check the times.")


def is_valid_course(c: dict) -> bool:
    """Port of src/shared/validators.js isValidCourse (section may be empty when the screenshot has none)."""
    return bool(c.get("courseCode") and c.get("courseName") is not None and isinstance(c.get("meetingPatterns"), list)
                and all(p.get("dayOfWeek") in WEEKDAYS and normalize_time(p.get("startTime", "")) == p.get("startTime")
                        and normalize_time(p.get("endTime", "")) == p.get("endTime") for p in c["meetingPatterns"])
                and c.get("location"))


def classes_on(schedule: dict | None, day: str) -> list[dict]:
    """[{courseCode, startTime, endTime, location}] meeting on `day`, sorted, online classes excluded."""
    out = []
    for c in (schedule or {}).get("courses", []):
        if is_online(c.get("location", "")):
            continue
        for p in c.get("meetingPatterns", []):
            if p["dayOfWeek"] == day:
                out.append({"courseCode": c["courseCode"], "startTime": p["startTime"], "endTime": p["endTime"],
                            "location": c.get("location", "")})
    return sorted(out, key=lambda x: x["startTime"])


def format_schedule(schedule: dict) -> str:
    """Discord-friendly list for the confirmation step."""
    lines = []
    if schedule.get("semester"):
        lines.append(f"**{schedule['semester']}**")
    for c in schedule.get("courses", []):
        by_time: dict[tuple, list[str]] = {}
        for p in c["meetingPatterns"]:
            by_time.setdefault((p["startTime"], p["endTime"]), []).append(p["dayOfWeek"][:3])
        when = "; ".join(f"{'/'.join(d)} {display(s)}-{display(e)}" for (s, e), d in by_time.items()) or "no set time"
        name = f" ({c['courseName']})" if c.get("courseName") else ""
        lines.append(f"- {c['courseCode']}{name}: {when}, {c['location']}")
    return "\n".join(lines)
