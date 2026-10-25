"""/commute plan: understand a free-text travel request, check the student's timetable, suggest a bus route.

1. understand_request: the language model turns the request into a few fields (class, day, starting place,
   other destination, arrival time). It sees the request and the student's class list, never the address.
2. resolve_trip: plain code picks the class and its start time from the saved timetable (or the destination
   and time the student named) and the building from the verified ASU list.
3. plan_commute: the trip planner (Never Late, Google Maps behind it) returns real journeys; route.py picks the
   bus route and a backup. Every time and stop in the reply comes from the planner.
"""
import asyncio
import json
import logging
import re
from datetime import datetime, timedelta

from langchain_core.messages import HumanMessage

from . import db as dbcall
from . import route
from .llm import chat_timeout_s
from .logic.schedule import classes_on, is_online
from .logic.timeutil import WEEKDAYS, display, next_date_for, normalize_time, resolve_day, to_minutes
from .travel import campus_centre, find_building

log = logging.getLogger(__name__)

ARRIVE_EARLY_MIN = 10  # be on campus this long before class
MAX_DAYS_AHEAD = 7  # the trip planner plans up to a week ahead
MODES = ["TRANSIT", "WALK", "BICYCLE"]
SETUP_HINT = 'use the "Set up your commute" button under /schedule view'

PROMPT = """A student asked Transit Buddy for a commute plan. Return ONLY JSON, no prose:
{{"course": the course code they mean (e.g. "CSE 110") or null,
 "day": "today", "tomorrow", a weekday like "Monday", or null,
 "from": the place they are starting from if they say it isn't home (e.g. "Tempe Marketplace"), else null,
 "to": a destination that is NOT one of their classes (e.g. "Hayden Library"), else null,
 "arrive_by": a time they say they must arrive (e.g. "2:00 PM"), else null}}
Use null for anything they didn't say. Don't guess.
Their classes: {classes}
Today is {today}.
Request: {request}"""


def _text(content) -> str:
    if isinstance(content, list):
        return " ".join(b.get("text", "") for b in content if isinstance(b, dict))
    return content or ""


def _parse_json(text: str) -> dict:
    s = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", s, re.S)
    if fence:
        s = fence.group(1)
    start, end = s.find("{"), s.rfind("}")
    data = json.loads(s[start:end + 1]) if start >= 0 and end > start else {}
    return {k: (str(v).strip() if v not in (None, "", "null") else None)
            for k, v in data.items() if k in ("course", "day", "from", "to", "arrive_by")}


def class_list(schedule: dict | None) -> str:
    out = []
    for c in (schedule or {}).get("courses", []):
        if is_online(c.get("location", "")) or not c.get("meeting_patterns"):
            continue
        times = {}
        for p in c["meeting_patterns"]:
            times.setdefault(p["start_time"], []).append(p["day_of_week"][:3])
        when = "; ".join(f"{'/'.join(d)} {display(t)}" for t, d in times.items())
        out.append(f"{c['course_code']} ({when})")
    return ", ".join(out) or "none saved"


async def understand_request(model, request: str, schedule: dict | None, now: datetime) -> dict:
    """The request as fields. If the model fails, an empty dict: 'my next class, from home'."""
    prompt = PROMPT.format(classes=class_list(schedule), today=now.strftime("%A, %B %d, %Y"), request=request)
    try:
        reply = await asyncio.wait_for(model.ainvoke([HumanMessage(prompt)]), timeout=chat_timeout_s())
        return _parse_json(_text(reply.content))
    except Exception as error:
        log.warning("couldn't understand the commute request: %s", type(error).__name__)
        return {}


def _code(text: str | None) -> str:
    return re.sub(r"\s+", "", (text or "").upper())


def _when(day: str, hhmm: str, now: datetime) -> datetime:
    d = next_date_for(day, now)
    m = to_minutes(hhmm)
    return now.replace(year=d.year, month=d.month, day=d.day, hour=m // 60, minute=m % 60, second=0, microsecond=0)


def _day_label(when: datetime, now: datetime) -> str:
    if when.date() == now.date():
        return "today"
    if when.date() == (now + timedelta(days=1)).date():
        return "tomorrow"
    return f"{WEEKDAYS[when.weekday()]}, {when.strftime('%b')} {when.day}"


def resolve_trip(asked: dict, schedule: dict | None, now: datetime) -> dict:
    """Which trip: {"title", "start", "location"} or {"error"}. Plain code, using the saved timetable."""
    day = None
    if asked.get("day"):
        try:
            day = resolve_day(asked["day"], now)
        except ValueError:
            return {"error": f"I couldn't tell which day \"{asked['day']}\" means. Try today, tomorrow or a weekday."}
    arrive_by = normalize_time(asked["arrive_by"]) if asked.get("arrive_by") else None

    if asked.get("to"):  # somewhere that isn't one of their classes
        if not arrive_by:
            return {"error": f"What time do you need to be at {asked['to']}? Add it, e.g. \"to {asked['to']} by "
                             "2:00 PM\"."}
        start = _when(day or WEEKDAYS[now.weekday()], arrive_by, now)
        if start <= now:
            start += timedelta(days=7 if day else 1)
        return {"title": f"**{asked['to']}**, {_day_label(start, now)} at {display(arrive_by)}",
                "start": start, "location": asked["to"], "is_class": False}

    if not schedule or not schedule.get("courses"):
        return {"error": "I don't have your class schedule yet. Save it with /schedule upload, then ask again."}
    want = _code(asked.get("course"))
    if want and not any(_code(c.get("course_code")) == want for c in schedule["courses"]):
        return {"error": f"{asked['course']} isn't in your saved schedule. Check /schedule view."}

    for ahead in range(0, MAX_DAYS_AHEAD + 1):
        d = now + timedelta(days=ahead)
        name = WEEKDAYS[d.weekday()]
        if day and name != day:
            continue
        for c in classes_on(schedule, name):
            if want and _code(c["course_code"]) != want:
                continue
            start = _when(name, c["start_time"], d)
            if start <= now:
                continue
            if arrive_by:  # they named their own arrival time for this class
                start = _when(name, arrive_by, d)
                if start <= now:
                    continue
            return {"title": f"**{c['course_code']}**, {_day_label(start, now)} at {display(start.strftime('%H:%M'))}",
                    "start": start, "location": c["location"], "is_class": True}
    what = asked.get("course") or "a class"
    when = f" on {day}" if day else " in the next week"
    return {"error": f"I couldn't find {what}{when} that hasn't started yet in your saved schedule."}


async def plan_commute(agent, user_id: str, guild_id: str, request: str) -> str:
    now = agent.clock()
    guild = guild_id or "dm"
    schedule = await dbcall.call(agent.db, "get_student_schedule", guild, user_id)
    if schedule and schedule.get("confirmation_status") != "confirmed":
        schedule = None
    asked = await understand_request(agent.model, request, schedule, now)
    trip = resolve_trip(asked, schedule, now)
    if trip.get("error"):
        return trip["error"]
    if not agent.travel.enabled:
        return "Bus routes aren't available on this bot right now: the trip planner isn't set up."

    # where from: a place they named, else their saved home (the address goes only to the trip planner)
    if asked.get("from"):
        place = find_building(asked["from"])
        origin_label = asked["from"]
        origin_address = place["address"] if place else asked["from"]
        origin_words = asked["from"]
    else:
        student = await dbcall.call(agent.db, "get_student", guild, user_id)
        if not student or not student.get("home_address"):
            return (f"I need your home address to plan from home: {SETUP_HINT}. Or say where you're starting, "
                    "e.g. \"from Tempe Marketplace\".")
        origin_label, origin_address, origin_words = "Home", student["home_address"], "home"

    building = find_building(trip["location"])
    note = ""
    if building:
        destination = building
    elif trip["is_class"]:
        destination = campus_centre()
        note = f"(I don't have the address of \"{trip['location']}\", so this plans to the Memorial Union.)"
    else:
        destination = {"label": trip["location"], "address": trip["location"]}

    status, data = await agent.travel.plan(origin_address, origin_label, destination, trip["start"], MODES,
                                           ARRIVE_EARLY_MIN if trip["is_class"] else 0)
    error = ((data or {}).get("error") or {})
    if status == 429 or error.get("code") == "RATE_LIMITED":
        return "The trip planner is busy right now. Please try again in a minute."
    if status in (400, 401, 403) or (status == 0 and data is None):
        return "The trip planner isn't working right now. Please try again in a few minutes."
    if error.get("code") == "ADDRESS_NOT_FOUND":
        if error.get("field") == "destination":
            return f"The trip planner couldn't find {trip['location']}. Try the building name or its address."
        where = f"\"{origin_words}\"" if origin_words != "home" else f"your saved home address ({SETUP_HINT} to check it)"
        return f"The trip planner couldn't find {where}."

    journeys = (data or {}).get("journeys") or []
    usable = route.usable(journeys, now)
    buses_left = any(j.get("mode") == "TRANSIT" for j in journeys) and \
        not any(j.get("mode") == "TRANSIT" for j in usable)
    if not usable:
        link = (data or {}).get("maps_link")
        return ("I couldn't find a bus, walk or bike route that still works for that trip."
                + (f"\n{link}" if link else ""))
    early = ARRIVE_EARLY_MIN if trip["is_class"] else 0
    choice = route.choose(usable, trip["start"], early, buses_left=buses_left)
    text = route.reply(data or {}, choice, trip["title"], trip["start"], origin_words, early, now)
    if note:
        text = text.replace("\n", f"\n{note}\n", 1)
    return text[:1900]
