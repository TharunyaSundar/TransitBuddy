from ...shared.contracts import CommutePreferences, Student, StudentSchedule
from ..connection import get_database
from ..models import COMMUTE_PREFERENCES, SCHEDULES, STUDENTS
from .guild_scoped import GuildScopedRepository

students = GuildScopedRepository(lambda: get_database()[STUDENTS], Student, created_at=True)
schedules = GuildScopedRepository(lambda: get_database()[SCHEDULES], StudentSchedule)
commute_preferences = GuildScopedRepository(
    lambda: get_database()[COMMUTE_PREFERENCES], CommutePreferences
)
