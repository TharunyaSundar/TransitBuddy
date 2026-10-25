"""In-memory DatabaseService with fictional ASU students, for agent tests and local runs before Developer 2's
MongoDB service is ready. It follows the same contract (agent/contracts.py), so swapping it out is one line.
"""
import copy
import uuid
from datetime import datetime, timezone

DEMO_GUILD = "demo-guild"


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class InMemoryDatabaseService:
    def __init__(self):
        self.students: dict[tuple, dict] = {}
        self.schedules: dict[tuple, dict] = {}
        self.preferences: dict[tuple, dict] = {}
        self.rides: dict[str, dict] = {}

    @staticmethod
    def _need(**ids):
        missing = [k for k, v in ids.items() if not v]
        if missing:
            raise ValueError(f"missing {', '.join(missing)}")

    def upsert_student(self, student):
        self._need(discordGuildId=student.get("discordGuildId"), discordUserId=student.get("discordUserId"))
        key = (student["discordGuildId"], student["discordUserId"])
        old = self.students.get(key, {"createdAt": _now()})
        self.students[key] = {**old, **student, "updatedAt": _now()}
        return copy.deepcopy(self.students[key])

    def get_student(self, discord_guild_id, discord_user_id):
        return copy.deepcopy(self.students.get((discord_guild_id, discord_user_id)))

    def save_schedule(self, schedule):
        self._need(discordGuildId=schedule.get("discordGuildId"), discordUserId=schedule.get("discordUserId"))
        doc = {**schedule, "updatedAt": _now()}
        self.schedules[(schedule["discordGuildId"], schedule["discordUserId"])] = doc
        return copy.deepcopy(doc)

    def get_student_schedule(self, discord_guild_id, discord_user_id):
        return copy.deepcopy(self.schedules.get((discord_guild_id, discord_user_id)))

    def get_schedules_for_users(self, discord_guild_id, discord_user_ids):
        return [copy.deepcopy(self.schedules[(discord_guild_id, u)]) for u in discord_user_ids
                if (discord_guild_id, u) in self.schedules]

    def delete_student_schedule(self, discord_guild_id, discord_user_id):
        return self.schedules.pop((discord_guild_id, discord_user_id), None) is not None

    def save_commute_preferences(self, preferences):
        self._need(discordGuildId=preferences.get("discordGuildId"), discordUserId=preferences.get("discordUserId"))
        self.preferences[(preferences["discordGuildId"], preferences["discordUserId"])] = dict(preferences)
        return copy.deepcopy(preferences)

    def get_commute_preferences(self, discord_guild_id, discord_user_id):
        return copy.deepcopy(self.preferences.get((discord_guild_id, discord_user_id)))

    def get_opted_in_commute_preferences(self, discord_guild_id):
        return [copy.deepcopy(p) for (g, _), p in self.preferences.items()
                if g == discord_guild_id and p.get("rideSharingOptIn")]

    def create_ride_request(self, request):
        self._need(discordGuildId=request.get("discordGuildId"), discordUserId=request.get("discordUserId"))
        doc = {"requestId": request.get("requestId") or uuid.uuid4().hex[:8], "status": "open",
               "createdAt": _now(), **request}
        self.rides[doc["requestId"]] = doc
        return copy.deepcopy(doc)

    def get_open_ride_requests(self, discord_guild_id):
        return [copy.deepcopy(r) for r in self.rides.values()
                if r["discordGuildId"] == discord_guild_id and r["status"] == "open"]

    def update_ride_request_status(self, request_id, status):
        if request_id not in self.rides:
            return None
        self.rides[request_id]["status"] = status
        return copy.deepcopy(self.rides[request_id])


def _course(code, name, days, start, end, location, section="1"):
    return {"courseCode": code, "courseName": name, "section": section, "location": location,
            "meetingPatterns": [{"dayOfWeek": d, "startTime": start, "endTime": end} for d in days]}


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
    for uid, name, area, modes, window, opt_in, courses in people:
        db.upsert_student({"discordUserId": uid, "discordGuildId": DEMO_GUILD, "displayName": name,
                           "university": "Arizona State University", "campus": "Tempe",
                           "timezone": "America/Phoenix"})
        db.save_schedule({"discordUserId": uid, "discordGuildId": DEMO_GUILD, "semester": "Fall 2026",
                          "courses": courses, "confirmationStatus": "confirmed"})
        db.save_commute_preferences({"discordUserId": uid, "discordGuildId": DEMO_GUILD, "generalOriginArea": area,
                                     "generalDestinationArea": "ASU Tempe campus", "preferredTransportModes": modes,
                                     "usualDepartureWindow": window, "rideSharingOptIn": opt_in})
    db.create_ride_request({"requestId": "r-demo1", "discordUserId": "1002", "discordGuildId": DEMO_GUILD,
                            "originArea": "Mesa", "destinationArea": "ASU Tempe campus",
                            "desiredDepartureTime": "Monday 08:15", "status": "open"})
    return db
