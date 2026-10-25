import asyncio
import os

import pytest

from src.database import DatabaseService, connect_database, disconnect_database, get_database
from src.shared.contracts import (
    CommutePreferences, Course, MeetingPattern, RideRequest, Student, StudentSchedule,
)

db = DatabaseService()
TEST_URI = os.getenv("TEST_MONGODB_URI")
needs_db = pytest.mark.skipif(not TEST_URI, reason="TEST_MONGODB_URI not set")


def run(coro):
    return asyncio.run(coro)


def student(g="g", u="u", name="A"):
    return Student(discord_user_id=u, discord_guild_id=g, display_name=name, university="ASU",
                   campus="Tempe", timezone="America/Phoenix", created_at="", updated_at="")


def schedule(g="g", u="u", status="confirmed", start="09:00"):
    return StudentSchedule(
        discord_user_id=u, discord_guild_id=g, semester="Fall 2026", confirmation_status=status,
        updated_at="",
        courses=[Course(course_code="CSE 565", course_name="X", section="1", location="Y",
                        meeting_patterns=[MeetingPattern(day_of_week="Monday", start_time=start, end_time="10:15")])],
    )


def ride(g="g", u="u"):
    return RideRequest(request_id="", discord_user_id=u, discord_guild_id=g, origin_area="a",
                       destination_area="b", desired_departure_time="08:30", status="open", created_at="")


# --- no database needed ---

def test_missing_identifiers_rejected():
    with pytest.raises(ValueError):
        run(db.get_student("", "u"))
    with pytest.raises(ValueError):
        run(db.get_open_ride_requests(""))
    with pytest.raises(ValueError):
        run(db.upsert_student(student(g="")))


def test_bad_time_rejected_before_write():
    with pytest.raises(ValueError):
        run(db.save_schedule(schedule(start="9am")))


def test_bad_ride_status_rejected():
    with pytest.raises(ValueError):
        run(db.update_ride_request_status("id", "bogus"))


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
def test_commute_preferences_round_trip():
    async def t():
        p = CommutePreferences(discord_user_id="u", discord_guild_id="g", general_origin_area="a",
                               general_destination_area="b", preferred_transport_modes=["bus"],
                               usual_departure_window="08:00-09:00", ride_sharing_opt_in=True)
        await db.save_commute_preferences(p)
        got = await db.get_commute_preferences("g", "u")
        assert got.ride_sharing_opt_in and got.preferred_transport_modes == ["bus"]
        assert await db.get_commute_preferences("g", "nobody") is None
    in_db(t)


@needs_db
def test_ride_request_lifecycle():
    async def t():
        r = await db.create_ride_request(ride())
        assert r.request_id and r.status == "open"
        assert len(await db.get_open_ride_requests("g")) == 1
        assert await db.get_open_ride_requests("other") == []
        assert (await db.update_ride_request_status(r.request_id, "matched")).status == "matched"
        assert await db.get_open_ride_requests("g") == []
        assert await db.update_ride_request_status("missing", "open") is None
    in_db(t)


@needs_db
def test_opted_in_preferences_and_private_home_address():
    async def t():
        def prefs(g, u, opt_in, address=None):
            return CommutePreferences(discord_user_id=u, discord_guild_id=g, general_origin_area="Mesa",
                                      general_destination_area="ASU Tempe campus", preferred_transport_modes=[],
                                      usual_departure_window="", ride_sharing_opt_in=opt_in, home_address=address)
        await db.save_commute_preferences(prefs("g", "a", True, "123 Example St, Mesa, AZ"))
        await db.save_commute_preferences(prefs("g", "b", False))
        await db.save_commute_preferences(prefs("other", "c", True))
        opted = await db.get_opted_in_commute_preferences("g")
        assert [p.discord_user_id for p in opted] == ["a"]  # not b (opted out), not c (other guild)
        assert (await db.get_commute_preferences("g", "a")).home_address == "123 Example St, Mesa, AZ"
        assert (await db.get_commute_preferences("g", "b")).home_address is None
        await db.save_commute_preferences(prefs("g", "a", True, None))  # forget the address
        assert (await db.get_commute_preferences("g", "a")).home_address is None
    in_db(t)
