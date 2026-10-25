"""When a student can realistically travel, from their confirmed schedule and stated preferences.

Class availability and commute availability are different things: a class ending at 10:15 doesn't mean the
student leaves at 10:15. Each window says where it came from so replies can be honest about it.
"""
from dataclasses import asdict, dataclass, field

from .schedule import classes_on
from .timeutil import from_minutes, parse_window, to_minutes

ARRIVAL_BUFFER_MIN = 10  # arrive this long before the first class
EXIT_BUFFER_MIN = 10  # earliest realistic exit after the last class (walk out, pack up)
END_OF_DAY = 23 * 60 + 59


@dataclass
class DayAvailability:
    userId: str
    day: str
    hasClasses: bool
    firstClassStart: str | None = None
    lastClassEnd: str | None = None
    arriveBy: str | None = None  # to campus: first class minus the arrival buffer
    earliestLeaveCampus: str | None = None  # from campus: last class end plus the exit buffer
    preferredWindow: str | None = None  # the student's usualDepartureWindow, if set
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def day_availability(user_id: str, schedule: dict | None, preferences: dict | None, day: str) -> DayAvailability:
    classes = classes_on(schedule, day)
    pref = (preferences or {}).get("usualDepartureWindow") or None
    a = DayAvailability(userId=user_id, day=day, hasClasses=bool(classes), preferredWindow=pref)
    if schedule is None:
        a.notes.append("no confirmed schedule")
    elif schedule.get("confirmationStatus") != "confirmed":
        a.notes.append("schedule not confirmed yet")
    if classes:
        first, last = classes[0], max(classes, key=lambda c: c["endTime"])
        a.firstClassStart, a.lastClassEnd = first["startTime"], last["endTime"]
        a.arriveBy = from_minutes(to_minutes(first["startTime"]) - ARRIVAL_BUFFER_MIN)
        a.earliestLeaveCampus = from_minutes(to_minutes(last["endTime"]) + EXIT_BUFFER_MIN)
        a.notes.append("leave-campus time is when classes are over, not a confirmed departure time")
    if pref and not parse_window(pref):
        a.notes.append(f"couldn't read departure window {pref!r}")
    return a


def departure_window(av: DayAvailability, direction: str, travel_min: int,
                     stated: dict | None = None, arrive_by: str | None = None) -> tuple[int, int, list[str]] | None:
    """The (earliest, latest) departure in minutes for a trip `direction` ("to_campus"/"from_campus").

    Sources, strongest first: what the student said in this conversation (`stated` earliest/latest HH:mm),
    their saved usualDepartureWindow, then their class times. `arrive_by` (HH:mm) is a group arrival time
    that replaces the class-based one. None if nothing tells us when they must arrive or leave.
    """
    stated = stated or {}
    pref = parse_window(av.preferredWindow) if av.preferredWindow else None
    why = []
    if direction == "to_campus":
        target = arrive_by or av.arriveBy  # a group arrival time the user gave overrides class times
        if not target and not stated.get("latest"):
            return None
        latest = END_OF_DAY
        if target:
            latest = to_minutes(target) - travel_min
            why.append(f"must arrive by {target}")
        earliest = 0
        if pref:
            earliest = pref[0]
            latest = min(latest, pref[1]) if not target else latest
            why.append(f"usually leaves {av.preferredWindow}")
    else:
        if not av.hasClasses and not stated and not pref:
            return None
        earliest, latest = 0, END_OF_DAY
        if av.earliestLeaveCampus:
            earliest = to_minutes(av.earliestLeaveCampus)
            why.append(f"classes over at {av.lastClassEnd}")
        if pref:
            earliest, latest = max(earliest, pref[0]), max(pref[1], earliest)
            why.append(f"usually leaves {av.preferredWindow}")
    if stated.get("earliest"):
        earliest = to_minutes(stated["earliest"])
        why.append(f"said they can leave from {stated['earliest']}")
    if stated.get("latest"):
        latest = to_minutes(stated["latest"])
        why.append(f"said they must leave by {stated['latest']}")
    return earliest, latest, why
