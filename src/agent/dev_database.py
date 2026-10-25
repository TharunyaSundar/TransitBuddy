"""In-memory DatabaseService with fictional ASU students, for agent tests and local runs before Developer 2's
MongoDB service is ready. Same async methods and shared Pydantic models as docs/integration-contracts.md.
"""
import uuid
from datetime import datetime, timezone

from ..shared.contracts import CommutePreferences, RideRequest, Student, StudentSchedule

DEMO_GUILD = "demo-guild"


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _need(model) -> None:
    if not model.discord_guild_id or not model.discord_user_id:
        raise ValueError("discord_guild_id and discord_user_id are required")


class InMemoryDatabaseService:
    def __init__(self):
        self.students: dict[tuple, Student] = {}
        self.schedules: dict[tuple, StudentSchedule] = {}
        self.preferences: dict[tuple, CommutePreferences] = {}
        self.rides: dict[str, RideRequest] = {}

    async def upsert_student(self, student: Student) -> Student:
        _need(student)
        key = (student.discord_guild_id, student.discord_user_id)
        old = self.students.get(key)
        doc = student.model_copy(update={"created_at": old.created_at if old else student.created_at or _now(),
                                         "updated_at": _now()})
        self.students[key] = doc
        return doc.model_copy(deep=True)

    async def get_student(self, discord_guild_id: str, discord_user_id: str) -> Student | None:
        doc = self.students.get((discord_guild_id, discord_user_id))
        return doc.model_copy(deep=True) if doc else None

    async def save_schedule(self, schedule: StudentSchedule) -> StudentSchedule:
        _need(schedule)
        doc = schedule.model_copy(update={"updated_at": _now()}, deep=True)
        self.schedules[(schedule.discord_guild_id, schedule.discord_user_id)] = doc
        return doc.model_copy(deep=True)

    async def get_student_schedule(self, discord_guild_id: str, discord_user_id: str) -> StudentSchedule | None:
        doc = self.schedules.get((discord_guild_id, discord_user_id))
        return doc.model_copy(deep=True) if doc else None

    async def get_schedules_for_users(self, discord_guild_id: str, discord_user_ids: list[str]) -> list[StudentSchedule]:
        return [self.schedules[(discord_guild_id, u)].model_copy(deep=True) for u in discord_user_ids
                if (discord_guild_id, u) in self.schedules]

    async def delete_student_schedule(self, discord_guild_id: str, discord_user_id: str) -> bool:
        return self.schedules.pop((discord_guild_id, discord_user_id), None) is not None

    async def save_commute_preferences(self, preferences: CommutePreferences) -> CommutePreferences:
        _need(preferences)
        self.preferences[(preferences.discord_guild_id, preferences.discord_user_id)] = preferences.model_copy(deep=True)
        return preferences.model_copy(deep=True)

    async def get_commute_preferences(self, discord_guild_id: str, discord_user_id: str) -> CommutePreferences | None:
        doc = self.preferences.get((discord_guild_id, discord_user_id))
        return doc.model_copy(deep=True) if doc else None

    async def get_opted_in_commute_preferences(self, discord_guild_id: str) -> list[CommutePreferences]:
        """Requested addition to the contract (see agent/README.md)."""
        return [p.model_copy(deep=True) for (g, _), p in self.preferences.items()
                if g == discord_guild_id and p.ride_sharing_opt_in]

    async def create_ride_request(self, request: RideRequest) -> RideRequest:
        _need(request)
        doc = request.model_copy(update={"request_id": request.request_id or uuid.uuid4().hex, "created_at": _now()})
        self.rides[doc.request_id] = doc
        return doc.model_copy(deep=True)

    async def get_open_ride_requests(self, discord_guild_id: str) -> list[RideRequest]:
        return [r.model_copy(deep=True) for r in self.rides.values()
                if r.discord_guild_id == discord_guild_id and r.status == "open"]

    async def update_ride_request_status(self, request_id: str, status: str) -> RideRequest | None:
        if request_id not in self.rides:
            return None
        self.rides[request_id] = self.rides[request_id].model_copy(update={"status": status})
        return self.rides[request_id].model_copy(deep=True)


def _course(code, name, days, start, end, location, section="1"):
    return {"course_code": code, "course_name": name, "section": section, "location": location,
            "meeting_patterns": [{"day_of_week": d, "start_time": start, "end_time": end} for d in days]}


def demo_database() -> InMemoryDatabaseService:
    """Four fictional students in DEMO_GUILD. 1001 is the default demo user."""
    db = InMemoryDatabaseService()
    people = [
        ("1001", "Alex", "Mesa", ["bus", "carpool"], "08:00-08:30", True,
         [_course("CSE 110", "Principles of Programming", ["Monday", "Wednesday", "Friday"], "09:00", "09:50", "Tempe - ISTB4 101"),
          _course("MAT 265", "Calculus for Engineers I", ["Tuesday", "Thursday"], "10:30", "11:45", "Tempe - COOR 170")]),
        ("1002", "Priya", "Mesa", ["carpool", "rideshare"], "08:00-08:40", True,
         [_course("EEE 120", "Digital Design Fundamentals", ["Monday", "Wednesday", "Friday"], "09:05", "09:55", "Tempe - BYENG 210"),
          _course("ENG 101", "First-Year Composition", ["Tuesday", "Thursday"], "13:30", "14:45", "Tempe - LL 104")]),
        ("1003", "Jordan", "Downtown Phoenix", ["bus", "light rail"], "07:30-08:15", True,
         [_course("PHY 121", "University Physics I", ["Monday", "Wednesday"], "09:00", "09:50", "Tempe - PSF 101")]),
        ("1004", "Sam", "Mesa", ["carpool"], "08:00-08:30", False,
         [_course("CSE 205", "Object-Oriented Programming", ["Monday", "Wednesday", "Friday"], "09:00", "09:50", "Tempe - BYENG 190")]),
    ]
    now = _now()
    for uid, name, area, modes, window, opt_in, courses in people:
        key = (DEMO_GUILD, uid)
        db.students[key] = Student(discord_user_id=uid, discord_guild_id=DEMO_GUILD, display_name=name,
                                   university="Arizona State University", campus="Tempe",
                                   timezone="America/Phoenix", created_at=now, updated_at=now)
        db.schedules[key] = StudentSchedule(discord_user_id=uid, discord_guild_id=DEMO_GUILD, semester="Fall 2026",
                                            courses=courses, confirmation_status="confirmed", updated_at=now)
        db.preferences[key] = CommutePreferences(discord_user_id=uid, discord_guild_id=DEMO_GUILD,
                                                 general_origin_area=area, general_destination_area="ASU Tempe campus",
                                                 preferred_transport_modes=modes, usual_departure_window=window,
                                                 ride_sharing_opt_in=opt_in)
    db.rides["r-demo1"] = RideRequest(request_id="r-demo1", discord_user_id="1002", discord_guild_id=DEMO_GUILD,
                                      origin_area="Mesa", destination_area="ASU Tempe campus",
                                      desired_departure_time="Monday 08:15", status="open", created_at=now)
    return db
