import asyncio
import os

import pytest

from src.database import DatabaseService, connect_database, disconnect_database, get_database
from src.shared.contracts import (
    Course, MeetingPattern, Student, StudentSchedule,
)

db = DatabaseService()
TEST_URI = os.getenv("TEST_MONGODB_URI")
needs_db = pytest.mark.skipif(not TEST_URI, reason="TEST_MONGODB_URI not set")


def run(coro):
    return asyncio.run(coro)


def student(g="g", u="u", name="A", address="123 Example St, Mesa, AZ"):
    return Student(discord_user_id=u, discord_guild_id=g, display_name=name, university="ASU",
                   campus="Tempe", timezone="America/Phoenix", created_at="", updated_at="",
                   home_address=address)


def schedule(g="g", u="u", status="confirmed", start="09:00"):
    return StudentSchedule(
        discord_user_id=u, discord_guild_id=g, semester="Fall 2026", confirmation_status=status,
        updated_at="",
        courses=[Course(course_code="CSE 565", course_name="X", section="1", location="Y",
                        meeting_patterns=[MeetingPattern(day_of_week="Monday", start_time=start, end_time="10:15")])],
    )


# --- no database needed ---

def test_missing_identifiers_rejected():
    with pytest.raises(ValueError):
        run(db.get_student("", "u"))
    with pytest.raises(ValueError):
        run(db.upsert_student(student(g="")))


def test_home_address_is_mandatory():
    with pytest.raises(ValueError):
        student(address="")
    with pytest.raises(ValueError):
        student(address="   ")
    with pytest.raises(ValueError):
        Student(discord_user_id="u", discord_guild_id="g", display_name="A", university="ASU",
                campus="Tempe", timezone="America/Phoenix", created_at="", updated_at="")


def test_bad_time_rejected_before_write():
    with pytest.raises(ValueError):
        run(db.save_schedule(schedule(start="9am")))


# --- integration (real MongoDB) ---

def in_db(coro_fn):
    async def wrapper():
        await connect_database(TEST_URI, "transit_buddy_test")
        try:
            database = get_database()
            await database.client.drop_database("transit_buddy_test")
            from src.database.models import ensure_indexes
            await ensure_indexes(database)
            await coro_fn()
        finally:
            await get_database().client.drop_database("transit_buddy_test")
            await disconnect_database()
    asyncio.run(wrapper())


@needs_db
def test_student_upsert_preserves_created_at():
    async def t():
        a = await db.upsert_student(student(name="A"))
        b = await db.upsert_student(student(name="B"))
        assert b.display_name == "B" and b.created_at == a.created_at
        assert await get_database()["students"].count_documents({}) == 1
    in_db(t)


@needs_db
def test_schedules_never_cross_guilds():
    async def t():
        await db.save_schedule(schedule("g1"))
        await db.save_schedule(schedule("g2"))
        assert await db.get_student_schedule("g3", "u") is None
        many = await db.get_schedules_for_users("g1", ["u", "x"])
        assert [s.discord_guild_id for s in many] == ["g1"]
        updated = await db.save_schedule(schedule("g1", status="pending_confirmation"))
        assert updated.confirmation_status == "pending_confirmation"
        assert await db.delete_student_schedule("g1", "u") is True
        assert await db.delete_student_schedule("g1", "u") is False
    in_db(t)


@needs_db
def test_home_address_saved_trimmed_and_updated():
    async def t():
        await db.upsert_student(student(address="  1 Main St, Tempe, AZ "))
        assert (await db.get_student("g", "u")).home_address == "1 Main St, Tempe, AZ"
        await db.upsert_student(student(address="2 Oak Ave, Mesa, AZ"))
        assert (await db.get_student("g", "u")).home_address == "2 Oak Ave, Mesa, AZ"
        assert await get_database()["students"].count_documents({}) == 1
    in_db(t)


@needs_db
def test_only_students_and_schedules_collections_exist():
    async def t():
        await db.upsert_student(student())
        await db.save_schedule(schedule())
        names = set(await get_database().list_collection_names())
        assert names == {"students", "schedules"}
    in_db(t)


@needs_db
def test_commute_profile_fields_opted_in_and_delete():
    async def t():
        await db.upsert_student(student(u="a").model_copy(update={
            "general_origin_area": "Mesa", "preferred_transport_modes": ["carpool"],
            "usual_departure_window": "08:00-08:30", "commute_match_opt_in": True}))
        await db.upsert_student(student(u="b"))  # address only: not opted in
        await db.upsert_student(student(g="other", u="c").model_copy(update={"commute_match_opt_in": True}))
        a = await db.get_student("g", "a")
        assert (a.general_origin_area, a.preferred_transport_modes, a.usual_departure_window) == \
            ("Mesa", ["carpool"], "08:00-08:30")
        assert (await db.get_student("g", "b")).commute_match_opt_in is False
        assert [s.discord_user_id for s in await db.get_opted_in_students("g")] == ["a"]  # not b, not other guild
        # a partial update (only the fields set) keeps the rest of the profile
        await db.upsert_student(Student.model_validate({
            "discord_user_id": "a", "discord_guild_id": "g", "display_name": "A2", "university": "ASU",
            "campus": "Tempe", "timezone": "America/Phoenix", "created_at": "", "updated_at": "",
            "home_address": "9 New St, Mesa, AZ"}))
        a = await db.get_student("g", "a")
        assert (a.display_name, a.home_address, a.general_origin_area, a.commute_match_opt_in) == \
            ("A2", "9 New St, Mesa, AZ", "Mesa", True)
        await db.save_schedule(schedule(u="a"))
        assert await db.delete_student("g", "a") is True
        assert await db.get_student("g", "a") is None
        assert await db.get_student_schedule("g", "a") is not None  # the schedule is separate and stays
        assert await db.delete_student("g", "a") is False
    in_db(t)
