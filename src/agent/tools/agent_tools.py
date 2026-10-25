"""LangChain tools. Each acts for the Discord user in runtime.context and stays inside their guild.

Privacy: other students are described by display name, general area and approximate times only, never by
address or full schedule. Matching only includes students who opted in.
"""
import functools
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from langchain.tools import ToolRuntime, tool
from pydantic import BaseModel, Field

from .. import db as dbcall
from ..logic.availability import day_availability, departure_window
from ..logic.matching import find_matches
from ..logic.negotiation import negotiate, window_text
from ..logic.schedule import format_schedule, normalize_schedule
from ..logic.timeutil import display, from_minutes, normalize_time, parse_window, resolve_day, to_minutes

DIRECTIONS = ("to_campus", "from_campus")
log = logging.getLogger(__name__)


@dataclass
class AgentContext:
    discord_user_id: str
    discord_guild_id: str
    db: Any
    channel_id: str = ""
    mentioned_user_ids: list[str] = field(default_factory=list)
    now: datetime | None = None
    pending: dict = field(default_factory=dict)  # pending schedules by user id (shared with AgentService)
    display_names: dict = field(default_factory=dict)  # user id -> name Discord showed, used before the database
    travel: Any = None  # TravelService: home -> class trip times (None or disabled = estimates only)
    events: dict = field(default_factory=dict)  # facts for the response metadata


def _out(d: Any) -> str:
    return json.dumps(d, ensure_ascii=False, default=str)


def _now(ctx: AgentContext) -> datetime:
    from ..logic.timeutil import now
    return ctx.now or now()


async def _name(ctx: AgentContext, user_id: str) -> str:
    if user_id == ctx.discord_user_id:
        return "you"
    if ctx.display_names.get(user_id):
        return ctx.display_names[user_id]
    s = await dbcall.call(ctx.db, "get_student", ctx.discord_guild_id, user_id)
    return (s or {}).get("display_name") or "a classmate"


async def _availability(ctx: AgentContext, user_id: str, day: str):
    sched = await dbcall.call(ctx.db, "get_student_schedule", ctx.discord_guild_id, user_id)
    if sched and sched.get("confirmation_status") != "confirmed":
        sched = None  # unconfirmed schedules are never used for planning
    prefs = await dbcall.call(ctx.db, "get_commute_preferences", ctx.discord_guild_id, user_id)
    return day_availability(user_id, sched, prefs, day), prefs, sched


def _guarded(fn):
    """Turn database errors into a tool result the model can explain, instead of crashing the turn."""
    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        try:
            return await fn(*args, **kwargs)
        except dbcall.DatabaseUnavailable:
            return _out({"ok": False, "error": "The schedule database isn't connected right now."})
        except ValueError as e:  # bad input, from our checks or DatabaseService validation
            return _out({"ok": False, "error": str(e)})
        except Exception:  # MongoDB down, timeouts, not connected: don't fail the whole reply
            log.exception("tool %s failed", fn.__name__)
            return _out({"ok": False, "error": "The schedule database had a problem. Try again in a minute."})
    return wrapper


@tool
@_guarded
async def get_my_schedule(runtime: ToolRuntime[AgentContext]) -> str:
    """Get the user's saved class schedule and whether it is confirmed."""
    ctx = runtime.context
    s = await dbcall.call(ctx.db, "get_student_schedule", ctx.discord_guild_id, ctx.discord_user_id)
    if not s:
        return _out({"ok": False, "error": "No schedule saved. Ask them to upload a screenshot of their class "
                                           "schedule or type their classes."})
    return _out({"ok": True, "status": s.get("confirmation_status"), "schedule": format_schedule(s)})


class ClassIn(BaseModel):
    course_code: str = Field(description="e.g. CSE 110")
    course_name: str = ""
    section: str = ""
    days: str = Field(description='e.g. "Mon/Wed/Fri" or "TTh"; empty for online without meetings')
    start_time: str = Field("", description='e.g. "9:00 AM" or "14:00"')
    end_time: str = Field("", description='e.g. "9:50 AM" or "15:15"')
    location: str = Field(description='as written, e.g. "Tempe - COOR 170" or "Online"')


@tool
@_guarded
async def prepare_schedule_from_text(classes: list[ClassIn], runtime: ToolRuntime[AgentContext],
                                     semester: str = "") -> str:
    """When the user TYPES their classes: check them and prepare them for confirmation. This does NOT save.
    Show the returned schedule and warnings and ask them to confirm with the Confirm button."""
    ctx = runtime.context
    raw = {"semester": semester, "courses": [{**c.model_dump(), "meeting_patterns": [
        {"days": c.days, "start_time": c.start_time, "end_time": c.end_time}] if c.days else []} for c in classes]}
    schedule, warnings = normalize_schedule(raw)
    ctx.pending[ctx.discord_user_id] = schedule
    ctx.events["pending_schedule"] = {"extracted_schedule": schedule, "validation_warnings": warnings,
                                     "confirmation_required": True}
    return _out({"ok": True, "saved": False, "schedule": format_schedule(schedule), "warnings": warnings})


@tool
@_guarded
async def get_availability(runtime: ToolRuntime[AgentContext], day: str = "today") -> str:
    """When the user (and anyone they @mentioned) can realistically travel on a day: must be on campus by,
    classes over at, usual departure window. day: "today", "tomorrow", "Monday"..."""
    ctx = runtime.context
    d = resolve_day(day, _now(ctx))
    out = []
    for uid in [ctx.discord_user_id, *ctx.mentioned_user_ids]:
        av, prefs, sched = await _availability(ctx, uid, d)
        entry = {"who": await _name(ctx, uid), "has_classes": av.has_classes, "notes": av.notes}
        if av.has_classes:
            entry.update(onCampusBy=display(av.arrive_by), classesOverAt=display(av.last_class_end))
            if uid == ctx.discord_user_id:  # only ever the student's own home, never a classmate's
                trip = await _trip(ctx, prefs, sched, d, av.arrive_by)
                if trip:
                    entry.update(leaveHomeBy=display(from_minutes(to_minutes(av.arrive_by) - trip.minutes)),
                                 trip=f"{trip.describe()} to {trip.destination}, from the trip planner")
        if av.preferred_window:
            entry["usual_departure_window"] = av.preferred_window
        out.append(entry)
    return _out({"ok": True, "day": d, "people": out})


@tool
@_guarded
async def find_commute_partners(runtime: ToolRuntime[AgentContext], day: str = "today",
                                direction: str = "to_campus", around_time: str | None = None) -> str:
    """Find opted-in students from the same general area with compatible times.
    direction: to_campus or from_campus. around_time: e.g. "9:00 AM" if the user named a time."""
    ctx = runtime.context
    if direction not in DIRECTIONS:
        direction = "to_campus"
    d = resolve_day(day, _now(ctx))
    my_av, my_prefs, _ = await _availability(ctx, ctx.discord_user_id, d)
    if not my_prefs or not my_prefs.get("general_origin_area"):
        return _out({"ok": False, "code": "need_area",
                     "error": "I need their general area first (e.g. Mesa, Downtown Phoenix). Ask, "
                              "then save_commute_preferences."})
    candidates: dict[str, dict] = {}
    whole_server = dbcall.has(ctx.db, "get_opted_in_commute_preferences")
    if whole_server:
        for p in await dbcall.call(ctx.db, "get_opted_in_commute_preferences", ctx.discord_guild_id) or []:
            candidates[p["discord_user_id"]] = p
    others = set(ctx.mentioned_user_ids) | {r["discord_user_id"] for r in
                                            await dbcall.call(ctx.db, "get_open_ride_requests", ctx.discord_guild_id) or []}
    for uid in others - set(candidates):
        p = await dbcall.call(ctx.db, "get_commute_preferences", ctx.discord_guild_id, uid)
        if p:
            candidates[uid] = p
    pairs = []
    for uid, p in candidates.items():
        if uid == ctx.discord_user_id:
            continue
        av, _, _ = await _availability(ctx, uid, d)
        pairs.append((p, av))
    around = normalize_time(around_time) if around_time else None
    matches = find_matches(my_prefs, my_av, pairs, direction, around)
    for m in matches:
        m["who"] = await _name(ctx, m.pop("discord_user_id"))
    return _out({"ok": True, "day": d, "direction": direction, "matches": matches[:5],
                 "searchedWholeServer": whole_server,
                 "note": "Only students who opted in to ride-sharing are included. Ask before connecting them."})


DEFAULT_TRAVEL_MIN = 30


def _first_class(sched: dict | None, day: str):
    from ..logic.schedule import classes_on
    classes = classes_on(sched, day)
    return classes[0] if classes else None


async def _trip(ctx: AgentContext, prefs: dict | None, sched: dict | None, day: str, arrive_by: str | None):
    """Home -> first class building on `day`, arriving by `arrive_by` (HH:mm). None if unknown."""
    if not ctx.travel or not (prefs or {}).get("home_address") or not arrive_by:
        return None
    from ..travel import class_arrival, planner_mode
    first = _first_class(sched, day)
    return await ctx.travel.minutes(prefs["home_address"], first["location"] if first else None,
                                    planner_mode(prefs.get("preferred_transport_modes")),
                                    class_arrival(_now(ctx), day, arrive_by))


async def _group_trip(ctx: AgentContext, group: list[str], day: str, direction: str,
                      arrive_by: str | None) -> tuple[int, str]:
    """Trip time for a group plan: the longest home -> campus trip among members with a saved address
    (everyone leaves together, so the farthest one sets it), else a 30-minute estimate."""
    if direction != "to_campus" or not ctx.travel:
        return DEFAULT_TRAVEL_MIN, "estimate"
    trips = []
    for uid in group:
        av, prefs, sched = await _availability(ctx, uid, day)
        target = normalize_time(arrive_by) if arrive_by else av.arrive_by
        trip = await _trip(ctx, prefs, sched, day, target)
        if trip:
            trips.append(trip.minutes)
    if not trips:
        return DEFAULT_TRAVEL_MIN, "estimate"
    return max(trips), f"trip planner ({len(trips)} of {len(group)} homes)"


_TIME = r"(\d{1,2}(?::\d{2})?\s*(?:am|pm|a\.m\.|p\.m\.)?)"
_EARLIEST = re.compile(r"(?:not before|can'?t leave before|cannot leave before|no earlier than|earliest|after|from|"
                       r"not until|only after)\s*(?:at\s*)?" + _TIME, re.I)
_ARRIVE = re.compile(r"(?:arrive|be on campus|on campus|be there|get there|be at (?:campus|class|asu))\D{0,12}?"
                     r"(?:by|before|at)\s*" + _TIME, re.I)
_LATEST = re.compile(r"(?:no later than|latest|must leave by|has to leave by|by|before|until)\s*(?:at\s*)?" + _TIME,
                     re.I)


def parse_constraint(text: str, me: str, names: dict[str, str]) -> tuple[str | None, dict]:
    """'Priya can't leave before 8:28 AM' -> ('1002', {'earliest': '08:28'}). Who: 'I/me/my' or a group
    member's name; times after 'not before/after/from' are earliest, after 'by/before/until' are latest,
    and 'on campus by / arrive by' is an arrival time (arrive_by)."""
    t = " " + text.strip() + " "
    who = None
    for uid, n in names.items():
        if uid != me and n and n != "a classmate" and re.search(rf"\b{re.escape(n.split()[0])}\b", t, re.I):
            who = uid
            break
    if who is None and (re.search(r"\b(i|me|my|i'm|myself)\b", t, re.I) or not text.strip()):
        who = me
    out = {}
    m = _EARLIEST.search(t)
    if m and normalize_time(m.group(1)):
        out["earliest"] = normalize_time(m.group(1))
        t = t.replace(m.group(0), " ")
    m = _ARRIVE.search(t)
    if m and normalize_time(m.group(1)):
        out["arrive_by"] = normalize_time(m.group(1))  # an arrival time, not a departure time
        t = t.replace(m.group(0), " ")
    m = _LATEST.search(t)
    if m and normalize_time(m.group(1)):
        out["latest"] = normalize_time(m.group(1))
    return who, out


@tool
@_guarded
async def propose_group_departure(runtime: ToolRuntime[AgentContext], day: str = "today",
                                  direction: str = "to_campus", travel_minutes: int | None = None,
                                  arrive_by: str | None = None,
                                  stated_constraints: list[Any] | str | None = None) -> str:
    """Negotiate one departure time for the user and the students they @mentioned, from their schedules and
    saved departure windows. stated_constraints: what people said in the chat, one short sentence each, e.g.
    ["Priya can't leave before 8:28 AM", "I must leave by 8:20 AM"]. travel_minutes: trip length the group
    gave; leave it empty otherwise (the tool uses trip times from saved home addresses, or a 30-minute
    estimate, and says which). arrive_by: only if the user named a time
    the group must be on campus (otherwise class times are used). Only report times this tool returns."""
    ctx = runtime.context
    if direction not in DIRECTIONS:
        direction = "to_campus"
    if not ctx.mentioned_user_ids:
        return _out({"ok": False, "code": "need_group",
                     "error": "Ask who is in the group: they can @mention the other students."})
    d = resolve_day(day, _now(ctx))
    group = [ctx.discord_user_id, *ctx.mentioned_user_ids]
    names = {uid: await _name(ctx, uid) for uid in group}
    travel_source = "given"
    if travel_minutes is None:
        travel_minutes, travel_source = await _group_trip(ctx, group, d, direction, arrive_by)
    items = [stated_constraints] if isinstance(stated_constraints, str) else list(stated_constraints or [])
    stated, ignored = {}, []
    for item in items:
        text = " ".join(str(v) for v in item.values()) if isinstance(item, dict) else str(item)
        uid, times = parse_constraint(text, ctx.discord_user_id, names)
        if uid is None or not times:
            ignored.append(text)
            continue
        if "arrive_by" in times:  # convert an arrival time to the latest departure
            arrive = times.pop("arrive_by")
            times.setdefault("latest", from_minutes(to_minutes(arrive) - travel_minutes))
        stated.setdefault(uid, {}).update(times)
    target = normalize_time(arrive_by) if arrive_by else None
    windows, missing, no_schedule = {}, [], []
    for uid in group:
        av, _, _ = await _availability(ctx, uid, d)
        w = departure_window(av, direction, travel_minutes, stated.get(uid), target)
        if w is None:
            missing.append(names[uid])
            if "no confirmed schedule" in av.notes:
                no_schedule.append(names[uid])
        else:
            windows[uid] = w
    if not windows or missing:
        need = "what time they need to be on campus" if direction == "to_campus" else "when they can leave"
        return _out({"ok": False, "code": "no_info", "day": d, "noInfoFor": missing, "noScheduleFor": no_schedule,
                     "error": f"No classes or saved times on {d} for {', '.join(missing)}. Ask {need} "
                              "(then pass arrive_by or stated_constraints). Don't suggest a time yourself."})
    result = negotiate(windows)
    if "participants" in result:  # impossible_for_some: name them instead of IDs
        result["participants"] = {names[u]: why for u, why in result["participants"].items()}
    for c in result.get("fitsEveryoneExcept", []):
        c["who"] = names[c.pop("discord_user_id")]
    if "fits" in result:
        result["fits"] = [names[u] for u in result["fits"]]
    for k in ("proposedDeparture", "compromiseDeparture"):
        if k in result:
            result[k] = display(result[k])
    result["windows"] = {names[u]: window_text(w[0], w[1]) + (f" ({'; '.join(w[2])})" if w[2] else "")
                         for u, w in windows.items()}
    result.update(ok=True, day=d, direction=direction, travelMinutesAssumed=travel_minutes, travelSource=travel_source)
    result["constraintsUsed"] = {names[u]: c for u, c in stated.items()}
    if ignored:
        result["ignoredConstraints"] = ignored
    return _out(result)


@tool
@_guarded
async def get_my_commute_preferences(runtime: ToolRuntime[AgentContext]) -> str:
    """Get the user's saved commute preferences (general area, modes, usual departure window, opt-in)."""
    ctx = runtime.context
    p = await dbcall.call(ctx.db, "get_commute_preferences", ctx.discord_guild_id, ctx.discord_user_id)
    if not p:
        return _out({"ok": False, "error": "No preferences saved yet. They can save them with /commute setup."})
    p = {**p, "home_address": "saved (private)" if p.get("home_address") else "not saved"}  # never the address
    return _out({"ok": True, "preferences": p})


_ADDRESS = re.compile(r"\d{2,}\s+\w+|\b(st|ave|rd|blvd|dr|apt|unit|#)\b", re.I)


@tool
@_guarded
async def save_commute_preferences(runtime: ToolRuntime[AgentContext], general_origin_area: str | None = None,
                                   general_destination_area: str | None = None,
                                   preferred_transport_modes: list[str] | None = None,
                                   usual_departure_window: str | None = None,
                                   ride_sharing_opt_in: bool | None = None) -> str:
    """Save what the user told you about their commute. Pass only what they said.
    general_origin_area: a general area like "Mesa" or "Downtown Phoenix", never a street address.
    preferred_transport_modes: e.g. ["carpool", "bus"]. usual_departure_window: e.g. "08:00-08:30".
    ride_sharing_opt_in: only true if they clearly agreed to be matched with other students."""
    ctx = runtime.context
    if general_origin_area and _ADDRESS.search(general_origin_area):
        return _out({"ok": False, "error": "That looks like a street address. Ask for a general area instead "
                                           "(neighborhood or city), for privacy."})
    if usual_departure_window and not parse_window(usual_departure_window):
        return _out({"ok": False, "error": "usual_departure_window must look like 08:00-08:30"})
    old = await dbcall.call(ctx.db, "get_commute_preferences", ctx.discord_guild_id, ctx.discord_user_id) or {}
    w = parse_window(usual_departure_window) if usual_departure_window else None
    prefs = {
        "discord_user_id": ctx.discord_user_id, "discord_guild_id": ctx.discord_guild_id,
        "general_origin_area": general_origin_area or old.get("general_origin_area", ""),
        "general_destination_area": general_destination_area or old.get("general_destination_area") or "ASU Tempe campus",
        "preferred_transport_modes": preferred_transport_modes or old.get("preferred_transport_modes", []),
        "usual_departure_window": f"{from_minutes(w[0])}-{from_minutes(w[1])}" if w else old.get("usual_departure_window", ""),
        "ride_sharing_opt_in": ride_sharing_opt_in if ride_sharing_opt_in is not None else old.get("ride_sharing_opt_in", False),
        "home_address": old.get("home_address"),  # only /commute setup changes the private address
    }
    saved = await dbcall.call(ctx.db, "save_commute_preferences", prefs)
    shown = {**(saved or prefs), "home_address": "saved (private)" if prefs["home_address"] else "not saved"}
    return _out({"ok": True, "saved": shown})


@tool
@_guarded
async def list_open_ride_requests(runtime: ToolRuntime[AgentContext]) -> str:
    """Open ride requests in this server (general areas and times only)."""
    ctx = runtime.context
    rows = await dbcall.call(ctx.db, "get_open_ride_requests", ctx.discord_guild_id) or []
    out = [{"request_id": r["request_id"], "who": await _name(ctx, r["discord_user_id"]), "from": r["origin_area"],
            "to": r["destination_area"], "when": r["desired_departure_time"]} for r in rows]
    return _out({"ok": True, "requests": out})


@tool
@_guarded
async def create_ride_request(origin_area: str, destination_area: str, desired_departure_time: str,
                              runtime: ToolRuntime[AgentContext]) -> str:
    """Post a ride request for the user, only when they asked to. Use general areas, never addresses.
    desired_departure_time: e.g. "Monday 8:15 AM"."""
    ctx = runtime.context
    if _ADDRESS.search(origin_area) or _ADDRESS.search(destination_area):
        return _out({"ok": False, "error": "Use general areas (e.g. Mesa, ASU Tempe campus), not addresses."})
    req = {"request_id": "", "discord_user_id": ctx.discord_user_id, "discord_guild_id": ctx.discord_guild_id,
           "origin_area": origin_area, "destination_area": destination_area,
           "desired_departure_time": desired_departure_time, "status": "open",
           "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat()}
    saved = await dbcall.call(ctx.db, "create_ride_request", req)  # DatabaseService assigns request_id
    ctx.events["ride_request_created"] = (saved or req)["request_id"]
    return _out({"ok": True, "request": saved or req})


@tool
@_guarded
async def update_my_ride_request(request_id: str, status: str, runtime: ToolRuntime[AgentContext]) -> str:
    """Mark one of the user's own open ride requests as matched, cancelled or completed."""
    ctx = runtime.context
    if status not in ("matched", "cancelled", "completed"):
        return _out({"ok": False, "error": "status must be matched, cancelled or completed"})
    mine = [r for r in await dbcall.call(ctx.db, "get_open_ride_requests", ctx.discord_guild_id) or []
            if r["request_id"] == request_id and r["discord_user_id"] == ctx.discord_user_id]
    if not mine:
        return _out({"ok": False, "error": "No open ride request with that ID belongs to this user."})
    r = await dbcall.call(ctx.db, "update_ride_request_status", request_id, status)
    return _out({"ok": bool(r), "request": r})


ALL_TOOLS = [get_my_schedule, prepare_schedule_from_text, get_availability, find_commute_partners,
             propose_group_departure, get_my_commute_preferences, save_commute_preferences,
             list_open_ride_requests, create_ride_request, update_my_ride_request]
