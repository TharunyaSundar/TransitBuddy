"""Shared data contracts used by all three modules.

These are the only integration boundary between the Discord, database and
agent layers. Timestamps are ISO-8601 strings.
"""
from typing import Literal, Optional

from pydantic import BaseModel, Field

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
RIDE_REQUEST_STATUSES = ("open", "matched", "cancelled", "completed")

Weekday = Literal[
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"
]
ConfirmationStatus = Literal["pending_confirmation", "confirmed"]
RideRequestStatus = Literal["open", "matched", "cancelled", "completed"]


class Student(BaseModel):
    discord_user_id: str  # Discord snowflake
    discord_guild_id: str
    display_name: str
    university: str  # e.g. Arizona State University
    campus: str  # e.g. Tempe
    timezone: str  # IANA name, e.g. America/Phoenix
    created_at: str
    updated_at: str


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


class CommutePreferences(BaseModel):
    discord_user_id: str
    discord_guild_id: str
    general_origin_area: str
    general_destination_area: str
    preferred_transport_modes: list[str] = Field(default_factory=list)
    usual_departure_window: str  # e.g. 08:00-09:00
    ride_sharing_opt_in: bool
    # Private: set only through /commute setup and used only for this student's own travel times
    # (sent to the trip planner). Never shown to other students or used for matching.
    home_address: Optional[str] = None


class RideRequest(BaseModel):
    request_id: str
    discord_user_id: str
    discord_guild_id: str
    origin_area: str
    destination_area: str
    desired_departure_time: str
    status: RideRequestStatus
    created_at: str


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
