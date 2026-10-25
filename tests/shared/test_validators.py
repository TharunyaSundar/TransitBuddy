from src.shared.validators import (
    is_valid_course,
    is_valid_time_string,
    is_valid_weekday,
)


def test_time_string():
    assert is_valid_time_string("08:30")
    assert not is_valid_time_string("25:00")
    assert not is_valid_time_string(830)


def test_weekday():
    assert is_valid_weekday("Monday")
    assert not is_valid_weekday("Funday")


def test_course():
    course = {
        "course_code": "CSE 565",
        "course_name": "Software Verification",
        "section": "12345",
        "location": "BYENG 210",
        "meeting_patterns": [
            {"day_of_week": "Monday", "start_time": "09:00", "end_time": "10:15"}
        ],
    }
    assert is_valid_course(course)
    course["meeting_patterns"][0]["start_time"] = "9am"
    assert not is_valid_course(course)
