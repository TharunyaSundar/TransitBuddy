"""Shared data contracts used by all three modules.

These are the only integration boundary between the Discord, database and
agent layers. Timestamps are ISO-8601 strings.
"""
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

COURSE_WEEKDAYS = (
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
)
CONFIRMATION_STATUSES = ("pending_confirmation", "confirmed")

Weekday = Literal[
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"
]
ConfirmationStatus = Literal["pending_confirmation", "confirmed"]


class Student(BaseModel):
    discord_user_id: str  # Discord snowflake
    discord_guild_id: str
    display_name: str
    university: str  # e.g. Arizona State University
    campus: str  # e.g. Tempe
    timezone: str  # IANA name, e.g. America/Phoenix
    created_at: str
    updated_at: str
    # Required and private: never show it to other students.
    home_address: str
    # Optional commute profile, saved with the home address from the private setup form. Only the general area
    # and approximate times are ever shown to other students, and only if they opted in to matching.
    general_origin_area: Optional[str] = None  # e.g. Mesa, Downtown Phoenix
    preferred_transport_modes: list[str] = Field(default_factory=list)  # e.g. ["carpool", "bus"]
    usual_departure_window: Optional[str] = None  # leaving for campus, 24-hour HH:mm-HH:mm, e.g. 08:00-08:30
    commute_match_opt_in: bool = False  # True only if the student agreed to be matched with other students

    @field_validator("home_address")
    @classmethod
    def _home_address_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("home_address is required.")
        return value


class MeetingPattern(BaseModel):
    day_of_week: Weekday
    start_time: str  # 24-hour HH:mm
    end_time: str  # 24-hour HH:mm


class Course(BaseModel):
    course_code: str  # e.g. CSE 565
    course_name: Optional[str] = None
    section: Optional[str] = None
    meeting_patterns: list[MeetingPattern] = Field(default_factory=list)
    location: str


class StudentSchedule(BaseModel):
    discord_user_id: str
    discord_guild_id: str
    semester: str  # e.g. Fall 2026
    courses: list[Course] = Field(default_factory=list)
    confirmation_status: ConfirmationStatus
    updated_at: str


class ProcessMessageContext(BaseModel):
    message: str
    discord_user_id: str
    discord_guild_id: str
    channel_id: str
    mentioned_user_ids: list[str] = Field(default_factory=list)


class AgentResponse(BaseModel):
    response_text: str
    metadata: Optional[dict] = None


class ScheduleExtractionResult(BaseModel):
    extracted_schedule: dict
    validation_warnings: list[str] = Field(default_factory=list)
    confirmation_required: bool = True
