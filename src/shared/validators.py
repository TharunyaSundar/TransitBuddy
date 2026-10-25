import re

COURSE_WEEKDAYS = [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
]
CONFIRMATION_STATUSES = ["pending_confirmation", "confirmed"]
RIDE_REQUEST_STATUSES = ["open", "matched", "cancelled", "completed"]
TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


def is_non_empty_string(value):
    return isinstance(value, str) and value.strip() != ""


def is_valid_weekday(value):
    return isinstance(value, str) and value in COURSE_WEEKDAYS


def is_valid_confirmation_status(value):
    return isinstance(value, str) and value in CONFIRMATION_STATUSES


def is_valid_ride_request_status(value):
    return isinstance(value, str) and value in RIDE_REQUEST_STATUSES


def is_valid_time_string(value):
    return isinstance(value, str) and bool(TIME_RE.match(value))


def is_valid_course(value):
    if not isinstance(value, dict):
        return False

    return (
        is_non_empty_string(value.get("course_code"))
        and is_non_empty_string(value.get("course_name"))
        and is_non_empty_string(value.get("section"))
        and isinstance(value.get("meeting_patterns"), list)
        and all(
            is_valid_weekday(pattern.get("day_of_week"))
            and is_valid_time_string(pattern.get("start_time"))
            and is_valid_time_string(pattern.get("end_time"))
            for pattern in value.get("meeting_patterns", [])
        )
        and is_non_empty_string(value.get("location"))
    )
