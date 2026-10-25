"""Commute partner matching: opted-in students in the same guild, same general area, compatible times.

Only general areas and approximate times are shared, never addresses or full schedules.
"""
import re

from .availability import DayAvailability
from .timeutil import display, parse_window, to_minutes

TIME_TOLERANCE_MIN = 30


def normalize_area(area: str | None) -> str:
    s = re.sub(r"[^a-z0-9 ]", " ", (area or "").lower())
    s = re.sub(r"\b(the|area|near|around|asu)\b", " ", s)
    return " ".join(s.split())


def same_area(a: str | None, b: str | None) -> bool:
    na, nb = normalize_area(a), normalize_area(b)
    return bool(na) and bool(nb) and (na == nb or na in nb or nb in na)


def _modes_overlap(a: list[str] | None, b: list[str] | None) -> list[str]:
    la, lb = {m.lower() for m in a or []}, {m.lower() for m in b or []}
    if not la or not lb:
        return sorted(la or lb)
    return sorted(la & lb)


def find_matches(me: dict, my_av: DayAvailability, others: list[tuple[dict, DayAvailability]],
                 direction: str = "to_campus", around: str | None = None,
                 tolerance_min: int = TIME_TOLERANCE_MIN) -> list[dict]:
    """me / others: CommutePreferences dicts. Returns matches sorted best first, each with plain reasons."""
    target = to_minutes(around) if around else None
    if target is None:
        t = my_av.arriveBy if direction == "to_campus" else my_av.earliestLeaveCampus
        if t:
            target = to_minutes(t)
        elif me.get("usualDepartureWindow") and parse_window(me["usualDepartureWindow"]):
            target = parse_window(me["usualDepartureWindow"])[0]
    out = []
    for prefs, av in others:
        if prefs.get("discordUserId") == me.get("discordUserId"):
            continue
        if not prefs.get("rideSharingOptIn"):
            continue  # never match a student who hasn't opted in
        if prefs.get("discordGuildId") != me.get("discordGuildId"):
            continue
        if not same_area(prefs.get("generalOriginArea"), me.get("generalOriginArea")):
            continue
        modes = _modes_overlap(me.get("preferredTransportModes"), prefs.get("preferredTransportModes"))
        if me.get("preferredTransportModes") and prefs.get("preferredTransportModes") and not modes:
            continue
        their = av.arriveBy if direction == "to_campus" else av.earliestLeaveCampus
        if their is None and prefs.get("usualDepartureWindow") and parse_window(prefs["usualDepartureWindow"]):
            their_min = parse_window(prefs["usualDepartureWindow"])[0]
        elif their is not None:
            their_min = to_minutes(their)
        else:
            continue  # no classes or window that day: nothing to match on
        gap = abs(their_min - target) if target is not None else 0
        if target is not None and gap > tolerance_min:
            continue
        what = "on campus by" if direction == "to_campus" else "free to leave campus from"
        reasons = [f"also from {prefs.get('generalOriginArea')}",
                   f"{what} about {display(f'{their_min // 60:02d}:{their_min % 60:02d}')}"]
        if modes:
            reasons.append(f"open to {', '.join(modes)}")
        out.append({"discordUserId": prefs["discordUserId"], "minutesApart": gap, "sharedModes": modes,
                    "reasons": reasons})
    return sorted(out, key=lambda m: m["minutesApart"])
