"""Seed fictional ASU demo data. Run: python -m scripts.seed_demo_data"""
import asyncio

from src.config import settings
from src.database import DatabaseService, connect_database, disconnect_database
from src.shared.constants import DEFAULT_CAMPUS, DEFAULT_TIMEZONE, DEFAULT_UNIVERSITY
from src.shared.contracts import (
    Course,
    MeetingPattern,
    Student,
    StudentSchedule,
)

GUILD_ID = settings.discord_guild_id or "demo-guild"
MW = ["Monday", "Wednesday"]
TTH = ["Tuesday", "Thursday"]


def course(code, name, section, days, start, end, location) -> Course:
    return Course(
        course_code=code,
        course_name=name,
        section=section,
        location=location,
        meeting_patterns=[MeetingPattern(day_of_week=d, start_time=start, end_time=end) for d in days],
    )


# Fictional students only. Ids are fake snowflakes.
DEMO_STUDENTS = [
    ("900000000000000001", "Maya Patel", "1000 E Apache Blvd, Tempe, AZ", [
        course("CSE 565", "Software Verification", "12345", MW, "09:00", "10:15", "BYENG 210"),
        course("CSE 572", "Data Mining", "23456", MW, "13:30", "14:45", "GWC 487"),
    ]),
    ("900000000000000002", "Jordan Lee", "1010 E Apache Blvd, Tempe, AZ", [
        course("CSE 551", "Algorithms", "34567", MW, "09:00", "10:15", "BYENG 220"),
        course("EEE 598", "Embedded Systems", "45678", TTH, "10:30", "11:45", "GWC 101"),
    ]),
    ("900000000000000003", "Sam Rivera", "500 N Central Ave, Phoenix, AZ", [
        course("CSE 578", "Data Visualization", "56789", TTH, "09:00", "10:15", "SCOB 120"),
    ]),
    ("900000000000000004", "Priya Natarajan", "200 W Main St, Mesa, AZ", [
        course("CSE 475", "Computer Security", "67890", MW, "10:30", "11:45", "BYENG 105"),
    ]),
]


async def seed() -> None:
    await connect_database()
    db = DatabaseService()

    for user_id, name, home_address, courses in DEMO_STUDENTS:
        await db.upsert_student(Student(
            discord_user_id=user_id, discord_guild_id=GUILD_ID, display_name=name,
            university=DEFAULT_UNIVERSITY, campus=DEFAULT_CAMPUS, timezone=DEFAULT_TIMEZONE,
            created_at="", updated_at="", home_address=home_address,
        ))
        await db.save_schedule(StudentSchedule(
            discord_user_id=user_id, discord_guild_id=GUILD_ID, semester="Fall 2026",
            courses=courses, confirmation_status="confirmed", updated_at="",
        ))
    print(f"Seeded {len(DEMO_STUDENTS)} demo students in guild {GUILD_ID}.")


async def main() -> None:
    try:
        await seed()
    finally:
        await disconnect_database()


if __name__ == "__main__":
    asyncio.run(main())
