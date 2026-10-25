"""DatabaseService implementation of docs/integration-contracts.md."""
from ...shared.contracts import CommutePreferences, RideRequest, Student, StudentSchedule
from ...shared.validators import is_valid_course
from .. import repositories as repos
from ..repositories import ride_requests


def _validate_schedule(schedule: StudentSchedule) -> None:
    for course in schedule.courses:
        if not is_valid_course(course.model_dump()):
            raise ValueError(f"Invalid course in schedule: {course.course_code!r}")


class DatabaseService:
    """Callers must run ``connect_database()`` first."""

    async def upsert_student(self, student: Student) -> Student:
        return await repos.students.upsert(student)

    async def get_student(self, discord_guild_id: str, discord_user_id: str) -> Student | None:
        return await repos.students.find(discord_guild_id, discord_user_id)

    async def save_schedule(self, schedule: StudentSchedule) -> StudentSchedule:
        _validate_schedule(schedule)
        return await repos.schedules.upsert(schedule)

    async def get_student_schedule(
        self, discord_guild_id: str, discord_user_id: str
    ) -> StudentSchedule | None:
        return await repos.schedules.find(discord_guild_id, discord_user_id)

    async def get_schedules_for_users(
        self, discord_guild_id: str, discord_user_ids: list[str]
    ) -> list[StudentSchedule]:
        return await repos.schedules.find_many(discord_guild_id, discord_user_ids)

    async def delete_student_schedule(self, discord_guild_id: str, discord_user_id: str) -> bool:
        return await repos.schedules.delete(discord_guild_id, discord_user_id)

    async def save_commute_preferences(self, preferences: CommutePreferences) -> CommutePreferences:
        return await repos.commute_preferences.upsert(preferences)

    async def get_commute_preferences(
        self, discord_guild_id: str, discord_user_id: str
    ) -> CommutePreferences | None:
        return await repos.commute_preferences.find(discord_guild_id, discord_user_id)

    async def create_ride_request(self, request: RideRequest) -> RideRequest:
        return await ride_requests.create(request)

    async def get_open_ride_requests(self, discord_guild_id: str) -> list[RideRequest]:
        return await ride_requests.find_open(discord_guild_id)

    async def update_ride_request_status(self, request_id: str, status: str) -> RideRequest | None:
        return await ride_requests.update_status(request_id, status)
