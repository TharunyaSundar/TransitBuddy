"""Consent-based matching for current commute plans.

All active intentions and pending pairs are process-local and are lost when the bot restarts.
The service stores no addresses, display names, or class schedule details.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Literal
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ...shared.contracts import Student
from ..commute_response import CommutePlanResponse

Direction = Literal["to_campus", "from_campus"]
DEFAULT_DEPARTURE_TOLERANCE_MINUTES = 15
DEFAULT_INTENTION_TTL = timedelta(hours=2)

_MODE_ALIASES = {
    "bike": "bicycle",
    "bicycle": "bicycle",
    "biking": "bicycle",
    "bus": "transit",
    "bus or train": "transit",
    "car": "drive",
    "carpool": "drive",
    "drive": "drive",
    "driving": "drive",
    "light rail": "transit",
    "lyft": "drive",
    "orbit": "transit",
    "rail": "transit",
    "ride share": "drive",
    "rideshare": "drive",
    "shuttle": "transit",
    "streetcar": "transit",
    "train": "transit",
    "transit": "transit",
    "uber": "drive",
    "walk": "walking",
    "walking": "walking",
}
_MODE_OUTPUT = {"bicycle": "bike", "drive": "car", "transit": "transit", "walking": "walking"}


class CommuteMatchCandidate(BaseModel):
    """A safe-to-present candidate. Participant identities remain inside the in-memory service."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    match_id: str
    travel_date: date
    direction: Direction
    departure_difference_minutes: int = Field(ge=0)
    shared_transport_modes: tuple[str, ...]


@dataclass(frozen=True)
class _ActiveIntention:
    guild_id: str
    user_id: str
    travel_date: date
    direction: Direction
    departure_at: datetime
    campus_destination: str
    origin_area: str
    preferred_modes: frozenset[str]
    estimated_mode: str
    estimated_duration_minutes: int
    created_at: datetime
    expires_at: datetime

    @property
    def fingerprint(self) -> tuple:
        return (
            self.travel_date, self.direction, self.departure_at, self.campus_destination,
            self.origin_area, self.preferred_modes, self.estimated_mode,
            self.estimated_duration_minutes,
        )


@dataclass(frozen=True)
class _PendingMatch:
    match_id: str
    participants: frozenset[tuple[str, str]]
    expires_at: datetime


def _normalize_place(value: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value.casefold()).split())


def _canonical_modes(values: list[str] | tuple[str, ...] | None) -> frozenset[str]:
    found = {_MODE_ALIASES[value.strip().casefold()] for value in values or ()
             if value and value.strip().casefold() in _MODE_ALIASES}
    return frozenset(found)


def _parse_departure(plan: CommutePlanResponse, student: Student) -> datetime:
    if not plan.travel_date or not plan.recommended_departure_time:
        raise ValueError("A current travel date and estimated departure time are required.")
    if not plan.direction or not plan.campus_destination or not plan.campus_destination.strip():
        raise ValueError("A direction and campus destination are required.")
    try:
        travel_day = date.fromisoformat(plan.travel_date)
        departure_time = datetime.strptime(plan.recommended_departure_time, "%I:%M %p").time()
        zone = ZoneInfo(student.timezone)
    except (ValueError, ZoneInfoNotFoundError) as error:
        raise ValueError("The commute plan has an invalid date, departure time, or timezone.") from error
    return datetime.combine(travel_day, departure_time, tzinfo=zone)


class CommuteMatchService:
    """In-memory active-intention and pending-match store.

    Call ``record_plan`` only after a student receives a successful, estimated plan. It returns
    opaque candidates without participant identity; later invitation code can resolve match IDs
    inside trusted bot logic. Matching never examines home addresses or class schedules.
    """

    def __init__(
        self,
        departure_tolerance_minutes: int = DEFAULT_DEPARTURE_TOLERANCE_MINUTES,
        intention_ttl: timedelta = DEFAULT_INTENTION_TTL,
    ) -> None:
        if departure_tolerance_minutes < 0:
            raise ValueError("departure_tolerance_minutes must be non-negative.")
        if intention_ttl <= timedelta(0):
            raise ValueError("intention_ttl must be positive.")
        self.departure_tolerance_minutes = departure_tolerance_minutes
        self.intention_ttl = intention_ttl
        self._intentions: dict[tuple[str, str], _ActiveIntention] = {}
        self._pending: dict[str, _PendingMatch] = {}
        self._pairs: dict[frozenset[tuple[str, str]], str] = {}

    @property
    def active_intention_count(self) -> int:
        return len(self._intentions)

    @property
    def pending_match_count(self) -> int:
        return len(self._pending)

    def record_plan(
        self,
        student: Student,
        plan: CommutePlanResponse,
        now: datetime | None = None,
    ) -> list[CommuteMatchCandidate]:
        """Save an opted-in student's live plan and return newly-created compatible candidates."""
        key = (student.discord_guild_id, student.discord_user_id)
        if not student.commute_match_opt_in:
            self.remove_student(*key)
            return []
        try:
            zone = ZoneInfo(student.timezone)
        except ZoneInfoNotFoundError as error:
            raise ValueError("The student's timezone must be a valid IANA timezone.") from error
        current = now or datetime.now(zone)
        if current.tzinfo is None or current.utcoffset() is None:
            raise ValueError("now must be timezone-aware.")
        current = current.astimezone(zone)
        self._expire(current)
        if plan.status != "success" or not plan.estimated or plan.estimated_duration_minutes is None:
            raise ValueError("Matching requires a successful commute plan with an estimated duration.")
        if plan.estimated_duration_minutes <= 0:
            raise ValueError("The commute estimate must be positive.")
        departure_at = _parse_departure(plan, student)
        modes = _canonical_modes(student.preferred_transport_modes)
        estimated_modes = _canonical_modes([plan.transport_mode] if plan.transport_mode else [])
        origin_area = _normalize_place(student.general_origin_area or "")
        campus = _normalize_place(plan.campus_destination or "")
        if not origin_area or not campus or not modes or not estimated_modes:
            raise ValueError("Matching requires an origin area, campus destination, and recognized transport mode.")
        if not (modes & estimated_modes):
            raise ValueError("The estimated transport mode is not in the student's saved preferences.")
        if departure_at <= current:
            self.remove_student(*key)
            return []

        intention = _ActiveIntention(
            guild_id=student.discord_guild_id,
            user_id=student.discord_user_id,
            travel_date=departure_at.date(),
            direction=plan.direction,
            departure_at=departure_at,
            campus_destination=campus,
            origin_area=origin_area,
            preferred_modes=modes,
            estimated_mode=next(iter(estimated_modes)),
            estimated_duration_minutes=plan.estimated_duration_minutes,
            created_at=current,
            expires_at=current + self.intention_ttl,
        )
        previous = self._intentions.get(key)
        if previous is not None and previous.fingerprint == intention.fingerprint:
            return []
        if previous is not None:
            self._remove_matches_for(key)
        self._intentions[key] = intention

        candidates: list[CommuteMatchCandidate] = []
        for other_key, other in tuple(self._intentions.items()):
            if other_key == key or other.guild_id != student.discord_guild_id:
                continue
            shared_modes = intention.preferred_modes & other.preferred_modes
            if not shared_modes or intention.estimated_mode != other.estimated_mode:
                continue
            if intention.travel_date != other.travel_date or intention.direction != other.direction:
                continue
            if intention.campus_destination != other.campus_destination:
                continue
            if intention.origin_area != other.origin_area:
                continue
            difference = abs(int((intention.departure_at - other.departure_at).total_seconds() // 60))
            if difference > self.departure_tolerance_minutes:
                continue
            pair = frozenset((key, other_key))
            if pair in self._pairs:
                continue
            match_id = uuid4().hex
            expires_at = min(intention.expires_at, other.expires_at)
            self._pending[match_id] = _PendingMatch(match_id, pair, expires_at)
            self._pairs[pair] = match_id
            candidates.append(CommuteMatchCandidate(
                match_id=match_id,
                travel_date=intention.travel_date,
                direction=intention.direction,
                departure_difference_minutes=difference,
                shared_transport_modes=tuple(sorted(_MODE_OUTPUT[mode] for mode in shared_modes)),
            ))
        return sorted(candidates, key=lambda candidate: (candidate.departure_difference_minutes, candidate.match_id))

    def remove_student(self, guild_id: str, user_id: str) -> None:
        """Remove a student's active intention and pending pairs, e.g. after opt-out."""
        key = (guild_id, user_id)
        self._intentions.pop(key, None)
        self._remove_matches_for(key)

    def _remove_matches_for(self, key: tuple[str, str]) -> None:
        for pair, match_id in tuple(self._pairs.items()):
            if key in pair:
                self._pairs.pop(pair, None)
                self._pending.pop(match_id, None)

    def _expire(self, now: datetime) -> None:
        for key, intention in tuple(self._intentions.items()):
            if intention.expires_at <= now or intention.departure_at <= now:
                self._intentions.pop(key, None)
                self._remove_matches_for(key)
        for match_id, pending in tuple(self._pending.items()):
            if pending.expires_at <= now:
                self._pending.pop(match_id, None)
                self._pairs.pop(pending.participants, None)
