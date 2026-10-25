"""/commute availability, match and plan with fake Discord interactions and the agent's in-memory demo database
(no Discord, Ollama or MongoDB needed). Demo students: 1001 Alex, 1002 Priya (Mesa, opted in),
1003 Jordan (Downtown Phoenix), 1004 Sam (Mesa, not opted in). The clock is Monday 7:00 AM."""
import asyncio
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from test_schedule_commands import FakeVision

from src.agent import AgentService
from src.agent.dev_database import DEMO_GUILD, InMemoryDatabaseService, demo_database
from src.discord_bot.client import create_discord_client
from src.discord_bot.commands.commute import build_commute_group
from src.discord_bot.commands.schedule import NOT_READY

MONDAY_7AM = datetime(2026, 10, 26, 7, 0, tzinfo=ZoneInfo("America/Phoenix"))


class FakeResponse:
    def __init__(self):
        self.sent, self.deferred = [], None

    async def send_message(self, content, ephemeral=False):
        self.sent.append({"content": content, "ephemeral": ephemeral})

    async def defer(self, ephemeral=False, thinking=False):
        self.deferred = {"ephemeral": ephemeral, "thinking": thinking}


class FakeFollowup:
    def __init__(self):
        self.sent = []

    async def send(self, content, ephemeral=False, allowed_mentions=None):
        self.sent.append({"content": content, "ephemeral": ephemeral, "allowed_mentions": allowed_mentions})


def interaction(user="1001"):
    return SimpleNamespace(user=SimpleNamespace(id=int(user)), guild_id=DEMO_GUILD, response=FakeResponse(),
                           followup=FakeFollowup())


def member(uid, bot=False):
    return SimpleNamespace(id=int(uid), bot=bot)


def agent_for(db=None):
    return AgentService(db or demo_database(), model=FakeVision(reply="unused"), clock=lambda: MONDAY_7AM)


def run(command, agent, user="1001", **kwargs):
    group = build_commute_group(lambda: agent)
    inter = interaction(user)
    asyncio.run(group.get_command(command).callback(inter, **kwargs))
    return inter


def reply(inter) -> dict:
    return inter.followup.sent[0]


def test_bot_registers_commute_group():
    bot = create_discord_client()
    group = bot.tree.get_command("commute")
    assert sorted(c.name for c in group.commands) == ["availability", "match", "plan"]
    assert group.guild_only
    plan = group.get_command("plan")
    assert [p.name for p in plan.parameters if p.required] == ["classmate1"]


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
        get_opted_in_commute_preferences = None  # like Developer 2's DatabaseService today

    db = NoServerSearch()
    db.__dict__.update(demo_database().__dict__)
    out = reply(run("match", agent_for(db)))
    assert "**Priya**" in out["content"]  # found through her open ride request
    assert "I can only check classmates you add" in out["content"]
    db.rides.clear()
    out = reply(run("match", agent_for(db)))
    assert "No opted-in students with similar times going to campus on Monday." in out["content"]


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
    assert "I don't have classes or saved times on Saturday for you or Priya" in out["content"]
    out = reply(run("plan", agent_for(), classmate1=member(1002), day="saturday", arrive_by="10:00 AM",
                    travel_minutes=25))
    assert "**Proposed departure: 8:00 AM** on Saturday" in out["content"]


def test_plan_needs_someone_else_and_bad_day():
    inter = run("plan", agent_for(), classmate1=member(1001))
    assert inter.response.sent[0] == {"content": "Add at least one classmate other than yourself.", "ephemeral": True}
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
