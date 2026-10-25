"""Commute handlers with fake Discord interactions and the agent's in-memory demo database (no Discord, Ollama
or MongoDB needed). These handlers are tested directly and are not registered as slash commands.
Demo students: 1001 Alex, 1002 Priya (Mesa, opted in),
1003 Jordan (Downtown Phoenix), 1004 Sam (Mesa, not opted in). The clock is Monday 7:00 AM."""
import asyncio
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from test_schedule_commands import FakeVision

from src.agent import AgentService
from src.agent.commute_response import CommutePlanResponse
from src.agent.dev_database import DEMO_GUILD, InMemoryDatabaseService, demo_database
from src.discord_bot.client import create_discord_client
from src.discord_bot.commands.commute import (
    _COMMUTE_COLORS,
    build_commute_group,
    build_commute_plan_group,
    commute_plan_embed,
)
from src.discord_bot.commands.schedule import NOT_READY

MONDAY_7AM = datetime(2026, 10, 26, 7, 0, tzinfo=ZoneInfo("America/Phoenix"))


class FakeResponse:
    def __init__(self):
        self.sent, self.deferred = [], None

    async def send_message(self, content=None, ephemeral=False, embed=None):
        self.sent.append({"content": content, "ephemeral": ephemeral, "embed": embed})

    async def defer(self, ephemeral=False, thinking=False):
        self.deferred = {"ephemeral": ephemeral, "thinking": thinking}


class FakeFollowup:
    def __init__(self):
        self.sent = []

    async def send(self, content=None, ephemeral=False, allowed_mentions=None, embed=None):
        self.sent.append({"content": content, "ephemeral": ephemeral, "allowed_mentions": allowed_mentions,
                          "embed": embed})


def interaction(user="1001"):
    return SimpleNamespace(user=SimpleNamespace(id=int(user)), guild_id=DEMO_GUILD, response=FakeResponse(),
                           followup=FakeFollowup())


def member(uid, bot=False, name=None):
    return SimpleNamespace(id=int(uid), bot=bot, display_name=name)


def agent_for(db=None):
    return AgentService(db or demo_database(), model=FakeVision(reply="unused"), clock=lambda: MONDAY_7AM)


def run(command, agent, user="1001", **kwargs):
    group = build_commute_group(lambda: agent)
    inter = interaction(user)
    asyncio.run(group.get_command(command).callback(inter, **kwargs))
    return inter


def reply(inter) -> dict:
    return inter.followup.sent[0]


def test_bot_does_not_register_commute_slash_group():
    bot = create_discord_client()
    group = bot.tree.get_command("commute")
    assert group is not None
    assert [c.name for c in group.commands] == ["plan"]


def test_plan_command_forwards_one_natural_language_request():
    class FakeAgent:
        async def commute_plan_request(self, user_id, guild_id, request):
            self.args = (user_id, guild_id, request)
            return CommutePlanResponse(
                status="success",
                description="Aim to reach your first class by 8:50 AM.",
                course_name="Software Verification",
                course_code="CSE 565",
                class_start_time="9:00 AM",
                campus_building="BYENG 210",
                travel_date="Monday, October 26",
                target_arrival_time="8:50 AM",
                estimated_duration_minutes=25,
                recommended_departure_time="8:25 AM",
                transport_mode="bus or train",
                estimated=True,
            )

    agent = FakeAgent()
    group = build_commute_plan_group(lambda: agent)
    command = group.get_command("plan")
    inter = interaction()

    asyncio.run(command.callback(inter, "Get me to campus before my first class tomorrow."))

    assert agent.args == ("1001", DEMO_GUILD, "Get me to campus before my first class tomorrow.")
    assert inter.response.deferred == {"ephemeral": True, "thinking": True}
    embed = reply(inter)["embed"]
    assert reply(inter)["ephemeral"]
    assert embed.title == "🚌 Your Commute Plan"
    assert embed.description == "Aim to reach your first class by 8:50 AM."
    assert [(field.name, field.value) for field in embed.fields] == [
        ("📚 Course", "CSE 565 — Software Verification"),
        ("⏰ Class starts", "9:00 AM"),
        ("📍 Campus building", "BYENG 210"),
        ("📅 Travel date", "Monday, October 26"),
        ("🎯 Target arrival", "8:50 AM"),
        ("🕒 Estimated commute", "~25 minutes (estimate)"),
        ("🚶 Recommended departure", "~8:25 AM (estimate)"),
        ("🚌 Transport", "bus or train"),
    ]
    assert "Transit conditions may change" in embed.footer.text
    assert reply(inter)["allowed_mentions"].everyone is False


def test_commute_embed_omits_unavailable_optional_fields_and_private_data():
    result = CommutePlanResponse(
        status="success",
        description="Your commute estimate is ready.",
        course_code="CSE 565",
    )

    embed = commute_plan_embed(result)

    assert [(field.name, field.value) for field in embed.fields] == [("📚 Course", "CSE 565")]
    assert "123 Main Street" not in embed.description


def test_commute_embed_formats_clarifications_unsupported_and_errors():
    for status, expected_title in (
        ("clarification", "❓ Commute Details Needed"),
        ("unsupported", "ℹ️ Commute Plan Not Supported"),
        ("error", "⚠️ Commute Plan Unavailable"),
    ):
        embed = commute_plan_embed(CommutePlanResponse(status=status, description="Please clarify your request."))
        assert embed.title == expected_title
        assert embed.color.value == _COMMUTE_COLORS[status].value
        assert not embed.fields
        assert "Please clarify your request." == embed.description
        assert "Transit conditions may change" in embed.footer.text


def test_commute_plan_agent_failure_is_address_free_and_private():
    class BrokenAgent:
        async def commute_plan_request(self, *args):
            raise RuntimeError("private address: 123 Main Street")

    inter = interaction()
    command = build_commute_plan_group(lambda: BrokenAgent()).get_command("plan")
    asyncio.run(command.callback(inter, "Get me to campus by 9 AM."))
    assert inter.response.deferred == {"ephemeral": True, "thinking": True}
    sent = reply(inter)
    assert sent["ephemeral"]
    assert "123 Main Street" not in sent["embed"].description
    assert "123 Main Street" not in sent["embed"].footer.text


def test_legacy_string_response_is_not_displayed():
    class LegacyAgent:
        async def commute_plan_request(self, *args):
            return "Trip starts at 123 Main Street."

    inter = interaction()
    command = build_commute_plan_group(lambda: LegacyAgent()).get_command("plan")
    asyncio.run(command.callback(inter, "Get me to campus by 9 AM."))

    embed = reply(inter)["embed"]
    assert embed.title == "⚠️ Commute Plan Unavailable"
    assert "123 Main Street" not in embed.description


def test_availability_is_private_and_skips_bots_and_self():
    inter = run("availability", agent_for(), classmate1=member(1002), classmate2=member(999, bot=True),
                classmate3=member(1001))
    out = reply(inter)
    assert inter.response.deferred == {"ephemeral": True, "thinking": True} and out["ephemeral"]
    assert "- You: on campus by 8:50 AM, classes over at 9:50 AM; usually leaves 8:00 AM-8:30 AM" in out["content"]
    assert "- Priya: on campus by 8:55 AM" in out["content"]
    assert out["content"].count("\n- ") == 2  # only you and Priya (no bot, no duplicate of you)
    assert out["allowed_mentions"].users is False  # never pings anyone


def test_match_only_opted_in_same_area():
    out = reply(run("match", agent_for(), classmate1=member(1002), classmate2=member(1003), classmate3=member(1004)))
    assert "**Priya**: also from Mesa, on campus by about 8:55 AM" in out["content"]
    assert "Sam" not in out["content"] and "Jordan" not in out["content"]  # not opted in / other area
    assert "can only check classmates" not in out["content"]  # demo database can search the whole server


def test_match_explains_limited_search_without_opted_in_query():
    class NoServerSearch(InMemoryDatabaseService):
        get_opted_in_students = None  # a database without the server-wide opted-in query

    db = NoServerSearch()
    db.__dict__.update(demo_database().__dict__)
    out = reply(run("match", agent_for(db)))
    assert "No opted-in students from your area with similar times and a shared way to travel, going to campus on Monday." in out["content"]
    assert "I can only check the classmates you added." in out["content"]
    out = reply(run("match", agent_for(db), classmate1=member(1002)))
    assert "**Priya**" in out["content"]  # added to the command, and opted in


def test_match_without_saved_area():
    out = reply(run("match", agent_for(), user="2002"))
    assert "general area" in out["content"] and "saved" in out["content"]


def test_plan_agreed_private_and_shared():
    inter = run("plan", agent_for(), classmate1=member(1002), travel_minutes=25)
    out = reply(inter)
    assert out["ephemeral"]
    assert "**Proposed departure: 8:00 AM** on Monday" in out["content"]
    assert "Everyone can leave between 8:00 AM and 8:25 AM." in out["content"]
    assert "Based on a 25-minute trip." in out["content"]
    shared = run("plan", agent_for(), classmate1=member(1002), share=True)
    assert shared.response.deferred["ephemeral"] is False and reply(shared)["ephemeral"] is False
    assert "Assuming a 30-minute trip" in reply(shared)["content"]  # default travel time is labelled


def test_plan_conflict_names_who_moves():
    out = reply(run("plan", agent_for(), classmate1=member(1002), travel_minutes=25,
                    constraints="Priya can't leave before 8:28 AM; nonsense here"))
    assert "No single time works for everyone on Monday." in out["content"]
    assert "**Closest: 8:25 AM**, which works for you." in out["content"]
    assert "Priya would have to leave earlier than they said (8:28 AM-8:30 AM) by 3 min" in out["content"]
    assert "Couldn't use: \"nonsense here\"" in out["content"]


def test_plan_impossible_and_no_info():
    out = reply(run("plan", agent_for(), classmate1=member(1002), travel_minutes=25,
                    constraints="Priya not before 8:40"))
    assert "Priya can't leave until 8:40 AM but would have to leave by 8:30 AM" in out["content"]
    out = reply(run("plan", agent_for(), classmate1=member(1002), day="saturday"))
    assert out["content"].startswith("You and Priya have no classes on Saturday. Try again and set arrive_by")
    out = reply(run("plan", agent_for(), classmate1=member(1002), day="saturday", arrive_by="10:00 AM",
                    travel_minutes=25))
    assert "**Proposed departure: 8:00 AM** on Saturday" in out["content"]


def test_plan_needs_someone_else_and_bad_day():
    inter = run("plan", agent_for(), classmate1=member(1001))
    assert inter.response.sent[0]["content"] == "Add at least one classmate other than yourself."
    assert inter.response.sent[0]["ephemeral"] is True
    out = reply(run("availability", agent_for(), day="someday"))
    assert "can't read the day" in out["content"]


def test_not_ready_and_failures_are_friendly():
    group = build_commute_group(lambda: None)
    inter = interaction()
    asyncio.run(group.get_command("availability").callback(inter))
    assert inter.response.sent[0]["content"] == NOT_READY

    class Broken:
        async def commute_availability(self, *a):
            raise RuntimeError("boom")
    inter = interaction()
    asyncio.run(build_commute_group(lambda: Broken()).get_command("availability").callback(inter))
    assert "try again" in reply(inter)["content"]


def test_plan_without_saved_departure_times_says_leave_by_not_midnight():
    # the screenshot case: nobody has a usual departure time, arrive by 8:00 AM, default 30-minute trip
    db = demo_database()
    for key, s in db.students.items():
        db.students[key] = s.model_copy(update={"usual_departure_window": None})
    out = reply(run("plan", agent_for(db), classmate1=member(1002, name="Priya"), day="saturday",
                    arrive_by="8:00 AM"))["content"]
    assert out.startswith("**Leave by 7:30 AM** on Saturday")
    assert "12:00 AM" not in out
    assert "- You: by 7:30 AM (must arrive by 8:00 AM)" in out
    assert "- Priya: by 7:30 AM (must arrive by 8:00 AM)" in out


def test_replies_use_discord_names_for_students_without_a_profile():
    out = reply(run("plan", agent_for(), classmate1=member(5005, name="Riya")))["content"]
    assert "Riya hasn't saved a schedule yet. Ask them to run /schedule upload." in out
    assert "a classmate" not in out
    out = reply(run("availability", agent_for(), classmate1=member(5005, name="Riya")))["content"]
    assert "- Riya: no saved schedule" in out
