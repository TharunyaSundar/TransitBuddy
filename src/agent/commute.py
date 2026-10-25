"""Commute calculations used by the agent and its internal command handlers.

Slash commands already give structured input, so these run the agent's tools directly, without the language
model: faster, no tokens, and every time shown comes from the schedule data and the negotiation logic.
"""
import json
import re
from types import SimpleNamespace

from .logic.timeutil import display, parse_window
from .tools.agent_tools import AgentContext

DEFAULT_TRAVEL_MIN = 30


async def run_tool(tool, ctx: AgentContext, **kwargs) -> dict:
    return json.loads(await tool.coroutine(runtime=SimpleNamespace(context=ctx), **kwargs))


def _window(text: str) -> str:
    """'08:00-08:30' -> '8:00 AM-8:30 AM'"""
    w = parse_window(text) if text else None
    if not w:
        return text
    return f"{display(f'{w[0] // 60:02d}:{w[0] % 60:02d}')}-{display(f'{w[1] // 60:02d}:{w[1] % 60:02d}')}"


def _who(name: str) -> str:
    return "You" if name == "you" else name


def _names(names: list[str], joiner: str = "and") -> str:
    """['you', 'Priya', 'Jordan'] -> 'you, Priya and Jordan' (for use mid-sentence)."""
    if len(names) <= 1:
        return "".join(names)
    return f"{', '.join(names[:-1])} {joiner} {names[-1]}"


def availability_text(r: dict) -> str:
    if not r.get("ok"):
        return r.get("error", "I couldn't check availability right now.")
    lines = [f"**{r['day']}**"]
    for p in r["people"]:
        if p["has_classes"]:
            text = f"on campus by {p['onCampusBy']}, classes over at {p['classesOverAt']}"
        elif "no confirmed schedule" in p.get("notes", []):
            text = "no saved schedule"
        else:
            text = "no classes"
        if p.get("usual_departure_window"):
            text += f"; usually leaves {_window(p['usual_departure_window'])}"
        if p.get("leaveHomeBy"):
            text += f"; leave home by {p['leaveHomeBy']} ({p['trip']})"
        lines.append(f"- {_who(p['who'])}: {text}")
    lines.append("\n\"Classes over at\" is when classes end, not when anyone has agreed to leave.")
    return "\n".join(lines)


def match_text(r: dict) -> str:
    if not r.get("ok"):
        if r.get("code") == "need_area":
            return ("I don't have your general area (for example Mesa or Downtown Phoenix) saved yet, "
                    "so I can't look for partners.")
        return r.get("error", "I couldn't look for partners right now.")
    where = "to campus" if r["direction"] == "to_campus" else "from campus"
    scope = "" if r.get("searchedWholeServer") else \
        "\nI can only check the classmates you added."
    if not r["matches"]:
        return (f"No opted-in students from your area with similar times and a shared way to travel, going "
                f"{where} on {r['day']}.{scope}")
    lines = [f"**Possible partners going {where} on {r['day']}:**"]
    for m in r["matches"]:
        lines.append(f"- **{m['who']}**: {', '.join(m['reasons'])}")
    lines.append(f"\nOnly students who opted in to ride-sharing are shown. Ask them before making plans.{scope}")
    return "\n".join(lines)


def _trip_line(r: dict) -> str:
    n, source = r["travelMinutesAssumed"], r.get("travelSource") or "estimate"
    if source == "given":
        return f"Based on a {n}-minute trip."
    if source.startswith("trip planner"):
        return f"Based on a {n}-minute trip: the longest trip from your saved homes, from the trip planner."
    return (f"Assuming a {n}-minute trip (an estimate: use the private commute setup form to save a home address, "
            f"or set travel_minutes).")


def plan_text(r: dict) -> str:
    if not r.get("ok"):
        if r.get("code") == "no_info":
            no_schedule = r.get("noScheduleFor") or []
            no_class = [n for n in r.get("noInfoFor") or [] if n not in no_schedule]
            when = ("set arrive_by to when you need to be on campus" if r.get("direction", "to_campus") == "to_campus"
                    else "add a constraint like \"I can leave after 3 PM\"")
            parts = []
            if "you" in no_schedule:
                parts.append("You haven't saved a schedule yet: use /schedule upload.")
            others = [n for n in no_schedule if n != "you"]
            if others:
                verb = "hasn't" if len(others) == 1 else "haven't"
                parts.append(f"{_names(others)} {verb} saved a schedule yet. Ask them to run /schedule upload.")
            if no_class:
                who = _names(no_class)
                who = "Y" + who[1:] if who.startswith("you") else who
                verb = "have" if len(no_class) > 1 or no_class == ["you"] else "has"
                parts.append(f"{who} {verb} no classes on {r['day']}.")
            parts.append(f"Try again and {when}." if no_class else f"Or try again and {when}.")
            return " ".join(parts)
        if r.get("code") == "need_group":
            return "Add at least one classmate to plan with."
        return r.get("error", "I couldn't plan a departure right now.")
    trip = _trip_line(r)
    if r["status"] == "impossible_for_some":
        lines = [f"This can't work on {r['day']}:"]
        lines += [f"- {_who(n)} {why}" for n, why in r["participants"].items()]
        lines.append(trip)
        return "\n".join(lines)
    if r["status"] == "agreed" and r.get("leaveBy"):
        lines = [f"**Leave by {r['proposedDeparture']}** on {r['day']}",
                 "That's the latest time that gets everyone there on time. Nobody has a usual departure time "
                 "saved, so leave earlier if you can."]
    elif r["status"] == "agreed":
        lines = [f"**Proposed departure: {r['proposedDeparture']}** on {r['day']}",
                 f"Everyone can leave between {_window(r['commonWindow']).replace('-', ' and ')}."]
    else:
        lines = [f"No single time works for everyone on {r['day']}.",
                 f"**Closest: {r['compromiseDeparture']}**, which works for {_names(r['fits'])}."]
        lines += [f"- {_who(c['who'])} {c['detail']}" for c in r["fitsEveryoneExcept"]]
        lines.append("Suggest it to the group; nobody has to accept it.")
    lines.append("\nEach person's window:")
    lines += [f"- {_who(n)}: {w}" for n, w in r["windows"].items()]
    if r.get("ignoredConstraints"):
        lines.append("Couldn't use: " + "; ".join(f"\"{c}\"" for c in r["ignoredConstraints"])
                     + " (name someone in the group and a time).")
    lines.append(trip)
    return "\n".join(lines)


YES = {"yes", "y", "true", "1", "on", "sure", "ok"}
NO = {"no", "n", "false", "0", "off", ""}
_STREETISH = re.compile(r"\d{2,}\s+\w+|\b(st|ave|rd|blvd|dr|apt|unit)\b|#", re.I)


def parse_setup(area: str, window: str, modes: str, opt_in: str, address: str) -> dict:
    """The commute setup form -> Student fields. The home address is required; the area is required only to be
    matched with other students. Raises ValueError with a student-facing message."""
    from .logic.schedule import _start_end
    address = (address or "").strip()
    if not address:
        raise ValueError("Add your home address. It's private and only used for your own trip times.")
    if len(address) < 6 or not re.search(r"\d", address) or not re.search(r"[A-Za-z]", address):
        raise ValueError("Enter a full street address (for example 123 E Main St, Mesa, AZ).")
    if len(address) > 200:
        raise ValueError("That address is too long.")
    area = (area or "").strip()
    if area and _STREETISH.search(area):
        raise ValueError("The area should be general, like Mesa or North Tempe. Put your street address in the "
                         "home address box instead (it stays private).")
    usual = None
    if (window or "").strip():
        parts = re.split(r"\s*(?:-|–|—|to)\s*", window.strip(), maxsplit=1)
        start, end = _start_end(parts[0], parts[1]) if len(parts) == 2 else (None, None)
        if not start or not end or end <= start:
            raise ValueError("Write the usual departure time as a range, like 8:00-8:30 AM.")
        usual = f"{start}-{end}"
    choice = (opt_in or "").strip().lower()
    if choice not in YES | NO:
        raise ValueError("Answer yes or no to being matched with other students.")
    if choice in YES and not area:
        raise ValueError("Add your general area (for example Mesa) so I can match you with students near you, "
                         "or answer no.")
    mode_list = [m.strip().lower() for m in re.split(r"[,/;]|\band\b", modes or "") if m.strip()][:5]
    return {"home_address": address, "general_origin_area": area or None, "usual_departure_window": usual,
            "preferred_transport_modes": mode_list, "commute_match_opt_in": choice in YES}


def setup_summary(setup: dict, travel_on: bool) -> str:
    lines = ["Saved your commute setup:",
             "- Home address: saved privately. Only used for your own trip times"
             + ("." if travel_on else " (trip times are off on this bot, so plans use estimates).")]
    if setup["general_origin_area"]:
        lines.append(f"- Area: {setup['general_origin_area']}")
    if setup["usual_departure_window"]:
        lines.append(f"- Usually leave: {_window(setup['usual_departure_window'])}")
    if setup["preferred_transport_modes"]:
        lines.append(f"- Getting there: {', '.join(setup['preferred_transport_modes'])}")
    lines.append(f"- Commute matching: {'on' if setup['commute_match_opt_in'] else 'off'}")
    lines.append("Change it with \"Set up your commute\" under /schedule view; \"Delete my commute profile\" there "
                 "removes it.")
    return "\n".join(lines)
