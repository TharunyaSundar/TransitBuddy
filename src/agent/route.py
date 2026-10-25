"""/commute plan: choose a bus route (and a backup) from the trip planner's journeys and write the reply.

Rules (from the Cubbie Transit Buddy skill this project grew out of):
- every time, route and stop comes from the trip planner; nothing is invented or adjusted;
- a journey whose first bus has already left (or can't be reached in time) is dropped;
- the primary is the on-time bus journey with the fewest transfers, then the latest departure;
- the backup boards later than the primary (so it still works if the first bus is missed) and still arrives
  before class; a different route is preferred;
- if no bus gets there on time, say so plainly and offer a walk/bike option or the earliest arrival.
"""
from datetime import datetime, timedelta

from .logic.timeutil import display

ON_TIME, REDUCED, LATE = "on_time", "reduced", "late"
MAX_WALK_MIN = 20  # longer walks to or from a stop are dropped


def _t(iso: str) -> datetime:
    return datetime.fromisoformat(iso)


def _hm(iso: str) -> str:
    return display(_t(iso).strftime("%H:%M"))


def transit_legs(j: dict) -> list[dict]:
    return [s for s in j.get("steps") or [] if s.get("type") == "transit"]


def boarding(j: dict) -> datetime:
    legs = transit_legs(j)
    return _t(legs[0]["depart_at"]) if legs else _t(j["leave_by"])


def status(j: dict, start: datetime, buffer_min: int) -> str:
    arrive = _t(j["arrive_at"])
    if arrive <= start - timedelta(minutes=buffer_min):
        return ON_TIME
    return REDUCED if arrive < start else LATE


def usable(journeys: list[dict], now: datetime) -> list[dict]:
    """Drop journeys that can't be caught any more or need a long walk to or from a stop."""
    out = []
    for j in journeys:
        steps = j.get("steps") or []
        if j.get("mode") == "TRANSIT":
            if not transit_legs(j):
                continue
            if any(s.get("type") == "walk" and (s.get("minutes") or 0) > MAX_WALK_MIN for s in steps):
                continue
            first_walk = steps[0].get("minutes", 0) if steps and steps[0].get("type") == "walk" else 0
            if boarding(j) < now + timedelta(minutes=first_walk):
                continue
        out.append(j)
    return out


def choose(journeys: list[dict], start: datetime, buffer_min: int, buses_left: bool = False) -> dict:
    """journeys: the usable ones. buses_left: the planner had buses, but all of them have already left."""
    st = {j["id"]: status(j, start, buffer_min) for j in journeys}
    buses = [j for j in journeys if j.get("mode") == "TRANSIT"]
    others = [j for j in journeys if j.get("mode") != "TRANSIT"]
    notes, primary, backup = [], None, None
    on_time = [j for j in buses if st[j["id"]] == ON_TIME]
    if on_time:
        primary = min(on_time, key=lambda j: (len(transit_legs(j)), -boarding(j).timestamp()))
    else:
        reduced = [j for j in buses if st[j["id"]] == REDUCED]
        if reduced:
            primary = max(reduced, key=boarding)
            notes.append("reduced")
    if primary:
        later = [j for j in buses if j is not primary and boarding(j) > boarding(primary) and st[j["id"]] != LATE]
        later.sort(key=lambda j: (st[j["id"]] != ON_TIME, j.get("route") == primary.get("route"),
                                  len(transit_legs(j)), boarding(j)))
        backup = later[0] if later else None
    alt = next((j for j in others if j.get("mode") in ("WALK", "BICYCLE") and st[j["id"]] == ON_TIME
                and (j.get("mode") != "WALK" or (j.get("total_min") or 0) <= MAX_WALK_MIN)), None)
    if primary is None:
        if alt:
            primary, alt = alt, None
            notes.append("buses_left" if buses_left else "no_bus" if buses else "walkable")
        elif journeys:
            primary = min(journeys, key=lambda j: _t(j["arrive_at"]))
            if buses_left:
                notes.append("buses_left")
    late = primary is not None and st[primary["id"]] == LATE
    return {"primary": primary, "backup": backup, "alt": alt, "late": late, "notes": notes, "status": st}


def _leave(j: dict, now: datetime) -> str:
    return "Leave now" if _t(j["leave_by"]) <= now else f"Leave at {_hm(j['leave_by'])}"


def _bus_steps(j: dict) -> str:
    steps, legs, parts = j.get("steps") or [], transit_legs(j), []
    if steps and steps[0].get("type") == "walk":
        parts.append(f"walk {steps[0].get('minutes')} min to {legs[0]['boarding_stop']}")
    for i, leg in enumerate(legs):
        toward = f" toward {leg['direction']}" if leg.get("direction") else ""
        where = "" if i == 0 else f" at {leg['boarding_stop']}"
        parts.append(f"{'take' if i == 0 else 'then change to'} **{leg['route']}**{toward}{where} at "
                     f"{_hm(leg['depart_at'])}, get off at {leg['destination_stop']}")
    if len(steps) > 1 and steps[-1].get("type") == "walk":
        parts.append(f"walk {steps[-1].get('minutes')} min")
    return ", ".join(parts)


def _word(j: dict) -> str:
    return {"WALK": "walk", "BICYCLE": "bike", "DRIVE": "drive"}.get(j.get("mode"), "go")


def describe(j: dict, origin: str, now: datetime) -> str:
    if j.get("mode") == "TRANSIT":
        return f"**{_leave(j, now)}** from {origin}: {_bus_steps(j)}. Arrive about {_hm(j['arrive_at'])}."
    return (f"**{_leave(j, now)}** from {origin} and {_word(j)} ({j.get('total_min')} min). "
            f"Arrive about {_hm(j['arrive_at'])}.")


def reply(data: dict, choice: dict, title: str, start: datetime, origin: str, buffer_min: int, now: datetime) -> str:
    """Short Discord reply: what and when, leave time + route, backup, one note, data caveat, map link."""
    p, b, alt = choice["primary"], choice["backup"], choice["alt"]
    lines = [title]
    if p is None:
        lines.append("I couldn't find a way there that leaves in time.")
    else:
        if "buses_left" in choice["notes"]:
            lines.append("The buses that would get you there in time have already left. Your best option now:")
        elif "no_bus" in choice["notes"]:
            lines.append("No bus gets you there on time, but you can make it this way:")
        lines.append(describe(p, origin, now))
        if choice["late"]:
            lines.append("Heads up: every option gets you there after class starts. This is the earliest arrival.")
        elif "reduced" in choice["notes"]:
            lines.append(f"Heads up: this gets you there before class, but not {buffer_min} min early.")
        if b:
            leg = transit_legs(b)[0]
            short = "" if choice["status"][b["id"]] == ON_TIME else f" (less than {buffer_min} min early)"
            lines.append(f"Backup if you miss it: **{leg['route']}** from {leg['boarding_stop']} at "
                         f"{_hm(leg['depart_at'])}, arrive about {_hm(b['arrive_at'])}{short}.")
        elif p.get("mode") == "TRANSIT" and not choice["late"]:
            lines.append("I didn't find a later bus that still gets you there in time, so don't miss this one.")
        if alt:
            when = "leave now" if _t(alt["leave_by"]) <= now else f"leave at {_hm(alt['leave_by'])}"
            lines.append(f"Or {_word(alt)}: {when} ({alt.get('total_min')} min).")
    weather = (data.get("weather") or {})
    if weather.get("impact"):
        lines.append(f"Weather: {weather['impact']}.")
    for a in (weather.get("alerts") or [])[:1]:
        lines.append(f"Weather alert: {a.get('event')}.")
    if p is not None and any(j and j.get("mode") == "TRANSIT" for j in (p, b)):
        lines.append("Bus times are posted schedules, not live, and service alerts weren't checked.")
    if data.get("maps_link"):
        lines.append(data["maps_link"])
    return "\n".join(lines)
