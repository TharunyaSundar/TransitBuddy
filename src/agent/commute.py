"""Commute answers for slash commands (/commute availability, match, plan).

Slash commands already give structured input, so these run the agent's tools directly, without the language
model: faster, no tokens, and every time shown comes from the schedule data and the negotiation logic.
"""
import json
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
        "\nI can only check classmates you add to the command and students with open ride requests."
    if not r["matches"]:
        return f"No opted-in students with similar times going {where} on {r['day']}.{scope}"
    lines = [f"**Possible partners going {where} on {r['day']}:**"]
    for m in r["matches"]:
        lines.append(f"- **{m['who']}**: {', '.join(m['reasons'])}")
    lines.append(f"\nOnly students who opted in to ride-sharing are shown. Ask them before making plans.{scope}")
    return "\n".join(lines)


def plan_text(r: dict, travel_given: bool) -> str:
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
    trip = (f"Based on a {r['travelMinutesAssumed']}-minute trip." if travel_given else
            f"Assuming a {r['travelMinutesAssumed']}-minute trip (set travel_minutes if it's different).")
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
