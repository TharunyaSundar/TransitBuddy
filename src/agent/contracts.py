"""Shared contracts from docs/integration-contracts.md, in Python.

Field names stay exactly as documented (camelCase), so the dicts match the MongoDB documents. Method names are
snake_case. DatabaseService is implemented by Developer 2; AgentService (agent/service.py) is used by Developer 1.
DatabaseService methods may be sync or async: the agent awaits them only when they return an awaitable.
"""
from typing import Any, Literal, Protocol, TypedDict

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
CONFIRMATION_STATUSES = ["pending_confirmation", "confirmed"]
RIDE_REQUEST_STATUSES = ["open", "matched", "cancelled", "completed"]

ConfirmationStatus = Literal["pending_confirmation", "confirmed"]
RideStatus = Literal["open", "matched", "cancelled", "completed"]


class Student(TypedDict):
    discordUserId: str
    discordGuildId: str
    displayName: str
    university: str
    campus: str
    timezone: str
    createdAt: str
    updatedAt: str


class MeetingPattern(TypedDict):
    dayOfWeek: str  # one of WEEKDAYS
    startTime: str  # HH:mm, 24-hour
    endTime: str  # HH:mm, 24-hour


class Course(TypedDict):
    courseCode: str
    courseName: str
    section: str
    meetingPatterns: list[MeetingPattern]
    location: str


class StudentSchedule(TypedDict):
    discordUserId: str
    discordGuildId: str
    semester: str
    courses: list[Course]
    confirmationStatus: ConfirmationStatus
    updatedAt: str


class CommutePreferences(TypedDict):
    discordUserId: str
    discordGuildId: str
    generalOriginArea: str
    generalDestinationArea: str
    preferredTransportModes: list[str]
    usualDepartureWindow: str  # "08:00-09:00"
    rideSharingOptIn: bool


class RideRequest(TypedDict):
    requestId: str
    discordUserId: str
    discordGuildId: str
    originArea: str
    destinationArea: str
    desiredDepartureTime: str
    status: RideStatus
    createdAt: str


class ProcessMessageContext(TypedDict, total=False):
    message: str  # required
    discordUserId: str  # required
    discordGuildId: str  # required ("dm" or "" for direct messages)
    channelId: str
    mentionedUserIds: list[str]
    displayName: str  # optional, used when the student has no record yet


class AgentResponse(TypedDict, total=False):
    responseText: str
    metadata: dict[str, Any]


class ScheduleExtractionResult(TypedDict):
    extractedSchedule: dict[str, Any]  # {"semester": str, "courses": [Course]}
    validationWarnings: list[str]
    confirmationRequired: bool


class DatabaseService(Protocol):
    """Developer 2's service. Every query is scoped to one Discord guild."""

    def upsert_student(self, student: Student) -> Student: ...
    def get_student(self, discord_guild_id: str, discord_user_id: str) -> Student | None: ...
    def save_schedule(self, schedule: StudentSchedule) -> StudentSchedule: ...
    def get_student_schedule(self, discord_guild_id: str, discord_user_id: str) -> StudentSchedule | None: ...
    def get_schedules_for_users(self, discord_guild_id: str, discord_user_ids: list[str]) -> list[StudentSchedule]: ...
    def delete_student_schedule(self, discord_guild_id: str, discord_user_id: str) -> bool: ...
    def save_commute_preferences(self, preferences: CommutePreferences) -> CommutePreferences: ...
    def get_commute_preferences(self, discord_guild_id: str, discord_user_id: str) -> CommutePreferences | None: ...
    def create_ride_request(self, request: RideRequest) -> RideRequest: ...
    def get_open_ride_requests(self, discord_guild_id: str) -> list[RideRequest]: ...
    def update_ride_request_status(self, request_id: str, status: RideStatus) -> RideRequest | None: ...

    # Optional (not in the documented contract yet; requested from Developer 2). Without it, commute matching
    # only considers students the user @mentions or who have open ride requests.
    # def get_opted_in_commute_preferences(self, discord_guild_id: str) -> list[CommutePreferences]: ...
