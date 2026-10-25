from ...shared.contracts import Student, StudentSchedule
from ..connection import get_database
from ..models import SCHEDULES, STUDENTS
from .guild_scoped import GuildScopedRepository

students = GuildScopedRepository(lambda: get_database()[STUDENTS], Student, created_at=True)
schedules = GuildScopedRepository(lambda: get_database()[SCHEDULES], StudentSchedule)
