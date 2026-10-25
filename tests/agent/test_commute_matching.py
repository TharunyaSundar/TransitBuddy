"""Deterministic, consent-gated in-memory matching tests."""
from datetime import datetime, timedelta
import json
from zoneinfo import ZoneInfo

import pytest

from src.agent.commute_response import CommutePlanResponse
from src.agent.logic.commute_matching import CommuteMatchService
from src.shared.contracts import Student

NOW = datetime(2026, 10, 26, 7, 0, tzinfo=ZoneInfo("America/Phoenix"))


def student(
    user_id: str,
    *,
    guild_id: str = "guild-a",
    opted_in: bool = True,
    area: str | None = "Tempe",
    modes: list[str] | None = None,
    timezone: str = "America/Phoenix",
) -> Student:
    return Student(
        discord_user_id=user_id,
        discord_guild_id=guild_id,
        display_name=f"Student {user_id}",
        university="Arizona State University",
        campus="Tempe",
        timezone=timezone,
        created_at="2026-10-25T00:00:00+00:00",
        updated_at="2026-10-25T00:00:00+00:00",
        home_address=f"private address for {user_id}",
        general_origin_area=area,
        preferred_transport_modes=["bus"] if modes is None else modes,
        commute_match_opt_in=opted_in,
    )


def plan(
    *,
    departure: str = "8:25 AM",
    travel_date: str = "2026-10-26",
    direction: str = "to_campus",
    campus: str = "Tempe",
    mode: str = "bus or train",
    status: str = "success",
    estimated: bool = True,
    duration: int | None = 25,
) -> CommutePlanResponse:
    return CommutePlanResponse(
        status=status,
        description="Estimated plan.",
        travel_date=travel_date,
        direction=direction,
        campus_destination=campus,
        recommended_departure_time=departure,
        estimated_duration_minutes=duration,
        transport_mode=mode,
        estimated=estimated,
    )


def test_matching_requires_explicit_opt_in_from_both_students():
    service = CommuteMatchService()
    opted_out = student("101", opted_in=False)
    assert service.record_plan(opted_out, plan(), NOW) == []
    assert service.record_plan(student("102"), plan(departure="8:30 AM"), NOW) == []
    assert service.active_intention_count == 1
    assert service.pending_match_count == 0


def test_matches_only_students_in_the_same_guild():
    service = CommuteMatchService()
    service.record_plan(student("101"), plan(), NOW)
    matches = service.record_plan(student("102", guild_id="guild-b"), plan(), NOW)
    assert matches == []
    assert service.pending_match_count == 0


def test_departure_difference_threshold_is_configurable_and_inclusive():
    service = CommuteMatchService()
    assert service.departure_tolerance_minutes == 15
    service.record_plan(student("101"), plan(departure="8:25 AM"), NOW)
    within = service.record_plan(student("102"), plan(departure="8:40 AM"), NOW)
    assert len(within) == 1
    assert within[0].departure_difference_minutes == 15
    assert within[0].shared_transport_modes == ("transit",)

    outside_service = CommuteMatchService(departure_tolerance_minutes=14)
    outside_service.record_plan(student("101"), plan(departure="8:25 AM"), NOW)
    assert outside_service.record_plan(student("102"), plan(departure="8:40 AM"), NOW) == []


@pytest.mark.parametrize(
    ("second_student", "second_plan"),
    [
        ({"modes": ["walking"]}, {"mode": "walking"}),
        ({}, {"travel_date": "2026-10-27"}),
        ({}, {"direction": "from_campus"}),
        ({}, {"campus": "Polytechnic"}),
        ({"area": "Mesa"}, {}),
        ({}, {"departure": "8:41 AM"}),
    ],
)
def test_incompatible_commute_intentions_do_not_match(second_student, second_plan):
    service = CommuteMatchService()
    service.record_plan(student("101"), plan(), NOW)
    assert service.record_plan(
        student("102", **second_student),
        plan(**second_plan),
        NOW,
    ) == []
    assert service.pending_match_count == 0


def test_preferred_modes_must_overlap_the_estimated_mode():
    service = CommuteMatchService()
    service.record_plan(student("101", modes=["bus", "carpool"]), plan(), NOW)
    assert service.record_plan(
        student("102", modes=["carpool"]),
        plan(mode="car"),
        NOW,
    ) == []

    matched_service = CommuteMatchService()
    matched_service.record_plan(student("201", modes=["bus", "carpool"]), plan(), NOW)
    result = matched_service.record_plan(
        student("202", modes=["carpool", "bus"]),
        plan(),
        NOW,
    )
    assert len(result) == 1


def test_student_cannot_match_with_themselves():
    service = CommuteMatchService()
    owner = student("101")
    assert service.record_plan(owner, plan(), NOW) == []
    assert service.record_plan(owner, plan(), NOW) == []
    assert service.active_intention_count == 1
    assert service.pending_match_count == 0


@pytest.mark.parametrize(
    ("profile", "result"),
    [
        ({"area": None}, plan()),
        ({"modes": []}, plan()),
        ({}, plan(campus="")),
        ({}, plan(mode="unknown")),
        ({}, plan(status="unsupported")),
        ({}, plan(estimated=False)),
        ({}, plan(duration=None)),
        ({}, plan(duration=0)),
    ],
)
def test_missing_or_invalid_current_plan_data_is_rejected(profile, result):
    service = CommuteMatchService()
    with pytest.raises(ValueError):
        service.record_plan(student("101", **profile), result, NOW)
    assert service.active_intention_count == 0


def test_repeated_intention_does_not_create_duplicate_pending_match():
    service = CommuteMatchService()
    service.record_plan(student("101"), plan(), NOW)
    initial = service.record_plan(student("102"), plan(departure="8:30 AM"), NOW)
    repeated = service.record_plan(student("102"), plan(departure="8:30 AM"), NOW)
    assert len(initial) == 1
    assert repeated == []
    assert service.pending_match_count == 1
    assert not hasattr(initial[0], "user_id")
    payload = json.loads(initial[0].model_dump_json())
    assert set(payload) == {
        "match_id", "travel_date", "direction", "departure_difference_minutes", "shared_transport_modes",
    }
    assert "discord_user_id" not in payload
    assert "Student 101" not in initial[0].model_dump_json()
    assert "Student 102" not in initial[0].model_dump_json()


def test_expired_intentions_and_pending_matches_are_removed():
    service = CommuteMatchService(intention_ttl=timedelta(minutes=30))
    service.record_plan(student("101"), plan(), NOW)
    service.record_plan(student("102"), plan(departure="8:30 AM"), NOW)
    assert service.pending_match_count == 1

    later = NOW + timedelta(minutes=31)
    assert service.record_plan(student("103"), plan(departure="8:30 AM"), later) == []
    assert service.active_intention_count == 1
    assert service.pending_match_count == 0


def test_departures_are_resolved_in_each_students_configured_timezone():
    service = CommuteMatchService()
    service.record_plan(student("101", timezone="America/Phoenix"), plan(), NOW)
    utc_now = NOW.astimezone(ZoneInfo("UTC"))
    # 8:35 AM Phoenix is 15:35 UTC: the two departures are exactly ten minutes apart.
    matches = service.record_plan(
        student("102", timezone="UTC"),
        plan(departure="3:35 PM"),
        utc_now,
    )
    assert len(matches) == 1
    assert matches[0].departure_difference_minutes == 10


def test_explicit_consent_revocation_removes_active_and_pending_state():
    service = CommuteMatchService()
    service.record_plan(student("101"), plan(), NOW)
    service.record_plan(student("102"), plan(), NOW)
    assert service.pending_match_count == 1
    service.remove_student("guild-a", "101")
    assert service.active_intention_count == 1
    assert service.pending_match_count == 0


def test_matching_rejects_naive_now_and_expired_departures():
    service = CommuteMatchService()
    with pytest.raises(ValueError, match="timezone-aware"):
        service.record_plan(student("101"), plan(), datetime(2026, 10, 26, 7))
    assert service.record_plan(
        student("101"), plan(departure="6:30 AM"), NOW
    ) == []
    assert service.active_intention_count == 0
