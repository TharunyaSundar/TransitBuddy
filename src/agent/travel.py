"""Travel times from a student's home address to their class building.

Uses the team's Never Late trip planner (POST /v2/plan, Google Maps behind it). Buildings come from
data/asu-buildings.json: 56 ASU Tempe buildings with addresses checked against ASU's own pages; a building
that isn't in the list falls back to the Memorial Union (campus centre), and the reply says so.

Privacy: the home address is sent only to the trip planner. It is never logged, shown to anyone, or passed
to the language model.

Settings: NEVER_LATE_TOKEN (without it travel times are off and plans use an estimate), NEVER_LATE_URL.
"""
import json
import logging
import math
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path

import httpx

log = logging.getLogger(__name__)

DEFAULT_URL = "https://never-late-api-966291054830.us-west1.run.app"
BUILDINGS = Path(__file__).resolve().parent / "data" / "asu-buildings.json"
CAMPUS_CENTRE = "MU"
MAX_HOME_KM = 100  # the Phoenix metro area; farther is almost always a mismatched address
TIMEOUT_S = 15

PLANNER_MODES = {  # student's words -> trip planner mode
    "carpool": "DRIVE", "rideshare": "DRIVE", "ride share": "DRIVE", "uber": "DRIVE", "lyft": "DRIVE",
    "drive": "DRIVE", "driving": "DRIVE", "car": "DRIVE",
    "bus": "TRANSIT", "light rail": "TRANSIT", "rail": "TRANSIT", "train": "TRANSIT", "shuttle": "TRANSIT",
    "transit": "TRANSIT", "orbit": "TRANSIT", "streetcar": "TRANSIT",
    "walk": "WALK", "walking": "WALK",
    "bike": "BICYCLE", "bicycle": "BICYCLE", "biking": "BICYCLE", "scooter": "BICYCLE",
}
MODE_WORDS = {"DRIVE": "car", "TRANSIT": "bus or train", "WALK": "walking", "BICYCLE": "bike"}


def planner_mode(modes: list[str] | None) -> str:
    """The first of the student's transport preferences the planner understands (default: car)."""
    for m in modes or []:
        found = PLANNER_MODES.get(m.strip().lower())
        if found:
            return found
    return "DRIVE"


@lru_cache(maxsize=1)
def _buildings() -> dict[str, dict]:
    with open(BUILDINGS) as f:
        return {b["code"]: b for b in json.load(f)["buildings"]}


def _short_name(name: str) -> str:
    return re.sub(r"\s+(Hall|Building|Center|Centre)$", "", name).strip()


def campus_centre() -> dict:
    return _buildings()[CAMPUS_CENTRE]


def find_building(location: str) -> dict | None:
    """'Tempe, ISTB4 101' or 'Tempe - Lattie F. Coor 4403' -> the verified building, or None."""
    text = location or ""
    for token in re.findall(r"[A-Z][A-Z0-9]{1,5}", text):
        if token in _buildings():
            return _buildings()[token]
    low = text.lower()
    for b in _buildings().values():
        if b["name"].lower() in low or (len(_short_name(b["name"])) > 6 and _short_name(b["name"]).lower() in low):
            return b
    return None


@dataclass
class TravelEstimate:
    minutes: int
    mode: str  # planner mode
    destination: str  # building name, or "campus (Memorial Union)" when the building isn't known
    exact_building: bool

    def describe(self) -> str:
        return f"{self.minutes} min by {MODE_WORDS.get(self.mode, self.mode.lower())}"


class TravelService:
    def __init__(self, url: str | None = None, token: str | None = None, caller=None):
        """caller: optional async (body) -> (status, json) for tests; defaults to the real planner."""
        self.url = (url or os.environ.get("NEVER_LATE_URL") or DEFAULT_URL).rstrip("/")
        self.token = token if token is not None else os.environ.get("NEVER_LATE_TOKEN", "")
        self._caller = caller
        self._cache: dict[tuple, TravelEstimate] = {}

    @property
    def enabled(self) -> bool:
        return bool(self._caller or self.token)

    async def _call(self, body: dict) -> tuple[int, dict | None]:
        if self._caller:
            return await self._caller(body)
        async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
            r = await client.post(f"{self.url}/v2/plan", json=body,
                                  headers={"content-type": "application/json", "x-skill-token": self.token})
            try:
                return r.status_code, r.json()
            except ValueError:
                return r.status_code, None

    def _body(self, address: str, building: dict, arrive_at: datetime, mode: str) -> dict:
        return {"origin": {"label": "Home", "address": address},
                "destination": {"label": f"{building['name']} ({building['code']})", "address": building["address"],
                                "lat": building["lat"], "lng": building["lng"]},
                "arrive_by": arrive_at.replace(second=0, microsecond=0).isoformat(),
                "modes": [mode], "buffer_min": 0}

    async def minutes(self, address: str | None, location: str | None, mode: str,
                      arrive_at: datetime) -> TravelEstimate | None:
        """Door-to-door minutes from home to the class building, or None if unknown (no address, no planner,
        planner error). Never raises."""
        if not address or not self.enabled:
            return None
        building = find_building(location or "")
        exact = building is not None
        building = building or _buildings()[CAMPUS_CENTRE]
        key = (address.strip().lower(), building["code"], mode, arrive_at.date(), arrive_at.strftime("%H:%M"))
        if key in self._cache:
            return self._cache[key]
        result = None
        try:
            status, data = await self._call(self._body(address, building, arrive_at, mode))
            journeys = [j for j in (data or {}).get("journeys") or [] if j.get("mode") == mode]
            if status == 200 and journeys:
                best = min(journeys, key=lambda j: j.get("total_min") or 10_000)
                result = TravelEstimate(int(best["total_min"]), mode,
                                        building["name"] if exact else "campus (Memorial Union)", exact)
            else:
                code = ((data or {}).get("error") or {}).get("code")
                log.warning("trip planner gave no %s journey (HTTP %s%s)", mode, status, f", {code}" if code else "")
        except Exception as error:  # timeouts, network: plans fall back to an estimate
            log.warning("trip planner call failed: %s", type(error).__name__)
        if result is not None:  # cache only real answers: a failure (e.g. HTTP 429, rate limit) is retried next time
            self._cache[key] = result
        return result

    async def plan(self, origin_address: str, origin_label: str, destination: dict, arrive_by: datetime,
                   modes: list[str], buffer_min: int = 0) -> tuple[int, dict | None]:
        """Full trip planner answer (journeys, map link, weather) for /commute plan. destination: a building
        from the verified list ({name, code, address, lat, lng}) or {label, address}. Never raises:
        (0, None) when the planner can't be reached."""
        if not self.enabled:
            return 0, None
        dest = {"label": destination.get("label") or f"{destination['name']} ({destination['code']})",
                "address": destination["address"]}
        if destination.get("lat") is not None:
            dest.update(lat=destination["lat"], lng=destination["lng"])
        body = {"origin": {"label": origin_label, "address": origin_address}, "destination": dest,
                "arrive_by": arrive_by.replace(second=0, microsecond=0).isoformat(), "modes": modes,
                "buffer_min": buffer_min}
        try:
            return await self._call(body)
        except Exception as error:
            log.warning("trip planner call failed: %s", type(error).__name__)
            return 0, None

    async def check_address(self, address: str, now: datetime) -> str:
        """'ok', 'not_found' (the planner can't locate it), 'too_far' (Google matched it to a place more than
        MAX_HOME_KM from campus: usually a typo or a missing city/state) or 'unavailable' (planner off or failing)."""
        if not self.enabled:
            return "unavailable"
        arrive = _next_weekday_morning(now)
        try:
            status, data = await self._call(self._body(address, _buildings()[CAMPUS_CENTRE], arrive, "DRIVE"))
        except Exception as error:
            log.warning("address check failed: %s", type(error).__name__)
            return "unavailable"
        code = ((data or {}).get("error") or {}).get("code")
        if code == "ADDRESS_NOT_FOUND" and ((data or {}).get("error") or {}).get("field") in (None, "origin"):
            return "not_found"
        origin = ((data or {}).get("resolved") or {}).get("origin") or {}
        if origin.get("lat") is not None and _km_from_campus(origin["lat"], origin["lng"]) > MAX_HOME_KM:
            return "too_far"
        return "ok" if status == 200 and (data or {}).get("journeys") else "unavailable"


def _km_from_campus(lat: float, lng: float) -> float:
    centre = _buildings()[CAMPUS_CENTRE]
    dlat, dlng = math.radians(lat - centre["lat"]), math.radians(lng - centre["lng"])
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat)) * math.cos(math.radians(centre["lat"])) * \
        math.sin(dlng / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(a))


def _next_weekday_morning(now: datetime) -> datetime:
    d = now + timedelta(days=1)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d.replace(hour=9, minute=0, second=0, microsecond=0)


def class_arrival(now: datetime, day: str, hhmm: str) -> datetime:
    """The next date for `day` (Monday...) at hh:mm, Phoenix time, never in the past."""
    from .logic.timeutil import next_date_for, to_minutes
    d = next_date_for(day, now)
    m = to_minutes(hhmm)
    when = now.replace(year=d.year, month=d.month, day=d.day, hour=m // 60, minute=m % 60, second=0, microsecond=0)
    return when if when > now else when + timedelta(days=7)
