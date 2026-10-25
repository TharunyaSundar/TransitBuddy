from dataclasses import dataclass, field
from typing import List, Literal


@dataclass
class Student:
    discord_user_id: str
    discord_guild_id: str
    display_name: str
    university: str
    campus: str
    timezone: str
    created_at: str
    updated_at: str


@dataclass
class MeetingPattern:
    day_of_week: Literal["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    start_time: str
    end_time: str


@dataclass
class Course:
    course_code: str
    course_name: str
    section: str
    meeting_patterns: List[MeetingPattern] = field(default_factory=list)
    location: str = ""


@dataclass
class StudentSchedule:
    discord_user_id: str
    discord_guild_id: str
    semester: str
    courses: List[Course] = field(default_factory=list)
    confirmation_status: Literal["pending_confirmation", "confirmed"] = "pending_confirmation"
    updated_at: str = ""


@dataclass
class CommutePreferences:
    discord_user_id: str
    discord_guild_id: str
    general_origin_area: str
    general_destination_area: str
    preferred_transport_modes: List[str] = field(default_factory=list)
    usual_departure_window: str = ""
    ride_sharing_opt_in: bool = False


@dataclass
class RideRequest:
    request_id: str
    discord_user_id: str
    discord_guild_id: str
    origin_area: str
    destination_area: str
    desired_departure_time: str
    status: Literal["open", "matched", "cancelled", "completed"] = "open"
    created_at: str = ""
