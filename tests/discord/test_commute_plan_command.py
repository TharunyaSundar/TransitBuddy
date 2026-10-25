"""/commute plan in Discord: private reply, the request reaches the agent, failures stay friendly."""
import asyncio
from types import SimpleNamespace

from src.discord_bot.client import create_discord_client
from src.discord_bot.commands.plan import NOT_READY, build_commute_plan_group


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

    async def send(self, content, ephemeral=False, **kw):
        self.sent.append({"content": content, "ephemeral": ephemeral})


def interaction():
    return SimpleNamespace(user=SimpleNamespace(id=1001), guild_id="demo-guild", response=FakeResponse(),
                           followup=FakeFollowup())


class FakeAgent:
    def __init__(self, fail=False):
        self.fail, self.calls = fail, []

    async def plan_commute(self, user_id, guild_id, request):
        self.calls.append((user_id, guild_id, request))
        if self.fail:
            raise RuntimeError("boom")
        return "**CSE 110**, today at 9:00 AM\n**Leave at 8:28 AM** from home: take **48th St**"


def plan_command(agent):
    return build_commute_plan_group(lambda: agent).get_command("plan")


def test_registered_on_the_bot():
    group = create_discord_client().tree.get_command("commute")
    assert [c.name for c in group.commands] == ["plan"] and group.guild_only


def test_private_reply_and_request_passed_through():
    agent = FakeAgent()
    inter = interaction()
    asyncio.run(plan_command(agent).callback(inter, "  I'm at Tempe Marketplace, CSE 110 tomorrow  "))
    assert inter.response.deferred == {"ephemeral": True, "thinking": True}
    assert agent.calls == [("1001", "demo-guild", "I'm at Tempe Marketplace, CSE 110 tomorrow")]
    assert inter.followup.sent[0]["ephemeral"] and "48th St" in inter.followup.sent[0]["content"]


def test_default_request_is_next_class():
    agent = FakeAgent()
    asyncio.run(plan_command(agent).callback(interaction(), "   "))
    assert agent.calls[0][2] == "my next class"


def test_not_ready_and_failure_are_friendly():
    inter = interaction()
    asyncio.run(plan_command(None).callback(inter, "class"))
    assert inter.response.sent[0] == {"content": NOT_READY, "ephemeral": True}
    inter = interaction()
    asyncio.run(plan_command(FakeAgent(fail=True)).callback(inter, "class"))
    assert "couldn't plan that right now" in inter.followup.sent[0]["content"]
