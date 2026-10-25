"""AgentService wired to Developer 2's real DatabaseService on MongoDB.

Skipped unless TEST_MONGODB_URI is set (same switch as tests/database). Uses its own database,
transit_buddy_agent_test, which is dropped before and after each test. The model is scripted, so no LLM is needed.
"""
import asyncio
import json
import os

import pytest

from agent_helpers import MONDAY_7AM, ScriptedModel, tool_results
from src.agent import AgentService
from src.database import DatabaseService, connect_database, disconnect_database, get_database
from src.shared.contracts import CommutePreferences, Course, MeetingPattern, Student, StudentSchedule

TEST_URI = os.getenv("TEST_MONGODB_URI")
DB_NAME = "transit_buddy_agent_test"
GUILD = "g-agent"
pytestmark = pytest.mark.skipif(not TEST_URI, reason="TEST_MONGODB_URI not set")

PEOPLE = [  # fictional students: (id, name, area, window, opted in, first class Monday)
    ("u1", "Alex", "Mesa", "08:00-08:30", True, "09:00"),
    ("u2", "Priya", "Mesa", "08:00-08:40", True, "09:05"),
    ("u3", "Sam", "Mesa", "08:00-08:30", False, "09:00"),
]


async def seed(db: DatabaseService) -> None:
    for uid, name, area, window, opt_in, start in PEOPLE:
        await db.upsert_student(Student(discord_user_id=uid, discord_guild_id=GUILD, display_name=name,
                                        university="Arizona State University", campus="Tempe",
                                        timezone="America/Phoenix", created_at="", updated_at=""))
        await db.save_schedule(StudentSchedule(
            discord_user_id=uid, discord_guild_id=GUILD, semester="Fall 2026", confirmation_status="confirmed",
            updated_at="", courses=[Course(course_code="CSE 110", course_name="Principles of Programming",
                                           section="12345", location="Tempe - ISTB4 101",
                                           meeting_patterns=[MeetingPattern(day_of_week="Monday", start_time=start,
                                                                            end_time="09:50")])]))
        await db.save_commute_preferences(CommutePreferences(
            discord_user_id=uid, discord_guild_id=GUILD, general_origin_area=area,
            general_destination_area="ASU Tempe campus", preferred_transport_modes=["carpool"],
            usual_departure_window=window, ride_sharing_opt_in=opt_in))


def scenario(fn):
    """Run fn(db, make_agent) inside one event loop with a fresh, seeded test database."""
    async def wrapper():
        await connect_database(TEST_URI, DB_NAME)
        try:
            await get_database().client.drop_database(DB_NAME)
            from src.database.models import ensure_indexes
            await ensure_indexes(get_database())
            db = DatabaseService()
            await seed(db)

            def make_agent(script):
                model = ScriptedModel(script=script, seen=[])
                return AgentService(db, model=model, clock=lambda: MONDAY_7AM), model
            await fn(db, make_agent)
        finally:
            try:
                await connect_database(TEST_URI, DB_NAME)  # no-op if still connected
                await get_database().client.drop_database(DB_NAME)
            finally:
                await disconnect_database()  # never leak a client bound to this event loop
    asyncio.run(wrapper())


def ctx(message, user="u1", mentioned=None):
    return {"message": message, "discord_user_id": user, "discord_guild_id": GUILD, "channel_id": "c",
            "mentioned_user_ids": mentioned or []}


def test_availability_and_group_departure():
    async def t(db, make_agent):
        agent, model = make_agent([[("get_availability", {"day": "today"})], "ok"])
        await agent.process_message(ctx("when can I leave?", mentioned=["u2"]))
        people = json.loads(tool_results(model)[0])["people"]
        assert [p["who"] for p in people] == ["you", "Priya"]
        assert people[0]["onCampusBy"] == "8:50 AM"

        agent, model = make_agent([[("propose_group_departure", {"travel_minutes": 25,
                                     "stated_constraints": ["Priya can't leave before 8:28 AM"]})], "ok"])
        await agent.process_message(ctx("share a ride?", mentioned=["u2"]))
        r = json.loads(tool_results(model)[0])
        assert r["status"] == "conflict" and r["fitsEveryoneExcept"][0]["who"] == "Priya"
    scenario(t)


def test_partners_without_opted_in_query_use_mentions_and_rides():
    async def t(db, make_agent):
        # DatabaseService has no get_opted_in_commute_preferences: only @mentions and ride requests are searched
        agent, model = make_agent([[("find_commute_partners", {"day": "today"})], "ok"])
        await agent.process_message(ctx("anyone heading in at 9?", mentioned=["u2", "u3"]))
        matches = json.loads(tool_results(model)[0])["matches"]
        assert [m["who"] for m in matches] == ["Priya"]  # Sam hasn't opted in
    scenario(t)


def test_preferences_and_ride_requests_persist():
    async def t(db, make_agent):
        agent, _ = make_agent([[("save_commute_preferences", {"general_origin_area": "Chandler",
                                                              "usual_departure_window": "7:30am-8am"})], "Saved."])
        await agent.process_message(ctx("I moved to Chandler, I leave 7:30-8"))
        p = await db.get_commute_preferences(GUILD, "u1")
        assert (p.general_origin_area, p.usual_departure_window, p.ride_sharing_opt_in) == ("Chandler", "07:30-08:00", True)

        agent, _ = make_agent([[("create_ride_request", {"origin_area": "Chandler", "destination_area": "ASU Tempe campus",
                                                         "desired_departure_time": "Monday 7:45 AM"})], "Posted."])
        resp = await agent.process_message(ctx("post a ride request"))
        rid = resp.metadata["ride_request_created"]
        assert [r.request_id for r in await db.get_open_ride_requests(GUILD)] == [rid]

        agent, model = make_agent([[("update_my_ride_request", {"request_id": rid, "status": "cancelled"})], "Done."])
        await agent.process_message(ctx("cancel it", user="u2"))  # not Priya's request
        assert json.loads(tool_results(model)[0])["ok"] is False
        agent, model = make_agent([[("update_my_ride_request", {"request_id": rid, "status": "cancelled"})], "Done."])
        await agent.process_message(ctx("cancel it"))
        assert json.loads(tool_results(model)[0])["ok"] is True
        assert await db.get_open_ride_requests(GUILD) == []
    scenario(t)


def test_schedule_confirm_flow_saves_only_complete_schedules():
    async def t(db, make_agent):
        await db.delete_student_schedule(GUILD, "u1")
        agent, _ = make_agent([[("prepare_schedule_from_text", {"semester": "Fall 2026", "classes": [
            {"course_code": "MAT 265", "days": "TTh", "start_time": "10:30 AM", "end_time": "11:45 AM",
             "location": "Tempe - COOR 170"}]})], "Press Confirm."])
        resp = await agent.process_message(ctx("MAT 265 TTh 10:30-11:45 COOR 170"))
        assert resp.metadata["pending_schedule"]["confirmation_required"]
        assert await db.get_student_schedule(GUILD, "u1") is None  # nothing saved before Confirm
        with pytest.raises(ValueError, match="section number"):
            await agent.save_confirmed_schedule("u1", GUILD)
        fixed = agent.pending_schedule("u1")
        fixed["courses"][0].update(course_name="Calculus for Engineers I", section="54321")
        saved = await agent.save_confirmed_schedule("u1", GUILD, fixed)
        stored = await db.get_student_schedule(GUILD, "u1")
        assert saved.confirmation_status == stored.confirmation_status == "confirmed"
        assert stored.courses[0].meeting_patterns[0].day_of_week == "Tuesday"
    scenario(t)


def test_database_down_is_explained_not_crashed():
    async def t(db, make_agent):
        await disconnect_database()  # simulate MongoDB going away mid-session
        agent, model = make_agent([[("get_my_schedule", {})], "The database had a problem."])
        resp = await agent.process_message(ctx("what's my schedule?"))
        assert "problem" in json.loads(tool_results(model)[0])["error"]
        assert resp.response_text == "The database had a problem."
    scenario(t)
