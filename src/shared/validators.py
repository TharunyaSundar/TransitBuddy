import re
from typing import Any

from .contracts import CONFIRMATION_STATUSES, COURSE_WEEKDAYS, RIDE_REQUEST_STATUSES

_TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


def is_non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and value.strip() != ""


def is_valid_weekday(value: Any) -> bool:
    return isinstance(value, str) and value in COURSE_WEEKDAYS


def is_valid_confirmation_status(value: Any) -> bool:
    return isinstance(value, str) and value in CONFIRMATION_STATUSES


def is_valid_ride_request_status(value: Any) -> bool:
    return isinstance(value, str) and value in RIDE_REQUEST_STATUSES


def is_valid_time_string(value: Any) -> bool:
    """Validate a 24-hour HH:mm string."""
    return isinstance(value, str) and _TIME_RE.match(value) is not None


def _is_optional_string(value: Any) -> bool:
    """None or a string (blank allowed)."""
    return value is None or isinstance(value, str)


def is_valid_course(value: Any) -> bool:
    """Validate a basic course dict (snake_case keys, as in contracts.Course)."""
    if not isinstance(value, dict):
        return False

    patterns = value.get("meeting_patterns")
    return (
        is_non_empty_string(value.get("course_code"))
        and _is_optional_string(value.get("course_name"))
        and _is_optional_string(value.get("section"))
        and isinstance(patterns, list)
        and all(
            isinstance(p, dict)
            and is_valid_weekday(p.get("day_of_week"))
            and is_valid_time_string(p.get("start_time"))
            and is_valid_time_string(p.get("end_time"))
            for p in patterns
        )
        and is_non_empty_string(value.get("location"))
    )
