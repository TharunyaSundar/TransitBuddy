import asyncio

import discord

from src.shared.contracts import AgentResponse
from src.discord_bot.client import create_discord_client


def test_client_uses_non_privileged_guild_intents():
    client = create_discord_client()

    assert client.intents.guilds
    assert client.intents.guild_messages
    assert not client.intents.message_content


def test_client_registers_only_ask_and_schedule_commands():
    client = create_discord_client()

    commands = {command.name: command for command in client.tree.get_commands()}

    assert set(commands) == {"ask", "schedule"}
    assert isinstance(commands["ask"], discord.app_commands.Command)
    assert isinstance(commands["schedule"], discord.app_commands.Group)
    assert {command.name for command in commands["schedule"].commands} == {"upload", "view"}


def test_ask_passes_discord_context_to_agent_and_replies_privately():
    class FakeAgentService:
        async def process_message(self, context):
            self.context = context
            return AgentResponse(response_text="You have class at 9 AM.")

    class FakeResponse:
        async def defer(self, **kwargs):
            self.defer_kwargs = kwargs

    class FakeFollowup:
        async def send(self, content, **kwargs):
            self.content = content
            self.send_kwargs = kwargs

    agent = FakeAgentService()
    interaction = type("Interaction", (), {})()
    interaction.user = type("User", (), {"id": 123})()
    interaction.guild_id = 456
    interaction.channel_id = 789
    interaction.response = FakeResponse()
    interaction.followup = FakeFollowup()
    command = create_discord_client(agent_service=agent).tree.get_command("ask")

    asyncio.run(command.callback(interaction, "When is class with <@!321>?"))

    assert agent.context.message == "When is class with <@!321>?"
    assert agent.context.discord_user_id == "123"
    assert agent.context.discord_guild_id == "456"
    assert agent.context.channel_id == "789"
    assert agent.context.mentioned_user_ids == ["321"]
    assert interaction.response.defer_kwargs == {"ephemeral": True, "thinking": True}
    assert interaction.followup.content == "You have class at 9 AM."
    assert interaction.followup.send_kwargs == {"ephemeral": True}

def test_ask_failure_still_answers():
    class BrokenAgentService:
        async def process_message(self, context):
            raise RuntimeError("model unreachable")

    class FakeResponse:
        async def defer(self, **kwargs):
            pass

    class FakeFollowup:
        async def send(self, content, **kwargs):
            self.content = content

    interaction = type("Interaction", (), {})()
    interaction.user = type("User", (), {"id": 123})()
    interaction.guild_id = 456
    interaction.channel_id = 789
    interaction.response = FakeResponse()
    interaction.followup = FakeFollowup()
    command = create_discord_client(agent_service=BrokenAgentService()).tree.get_command("ask")

    asyncio.run(command.callback(interaction, "When do I leave?"))

    # before the fix, the error handler itself crashed and Discord stayed on "thinking"
    assert "unavailable right now" in interaction.followup.content


def test_ask_shows_confirm_for_a_typed_schedule():
    class FakeAgentService:
        def __init__(self):
            self.pending = {"123": {"semester": "Fall 2026", "courses": [{"course_code": "CSE 110"}]}}
            self.saved = None

        async def process_message(self, context):
            return AgentResponse(response_text="Here's your schedule. Press Confirm to save it.",
                                 metadata={"pending_schedule": {"confirmation_required": True}})

        def pending_schedule(self, user_id):
            return self.pending.get(user_id)

        def discard_pending_schedule(self, user_id):
            self.pending.pop(user_id, None)

        async def save_confirmed_schedule(self, user_id, guild_id, schedule=None):
            self.saved = (user_id, guild_id, schedule)

    class FakeResponse:
        async def defer(self, **kwargs):
            pass

        async def edit_message(self, **kwargs):
            self.edited = kwargs

    class FakeFollowup:
        async def send(self, content, **kwargs):
            self.content, self.kwargs = content, kwargs

    agent = FakeAgentService()
    interaction = type("Interaction", (), {})()
    interaction.user = type("User", (), {"id": 123})()
    interaction.guild_id = 456
    interaction.channel_id = 789
    interaction.response = FakeResponse()
    interaction.followup = FakeFollowup()
    command = create_discord_client(agent_service=agent).tree.get_command("ask")

    asyncio.run(command.callback(interaction, "My classes: CSE 110 MWF 9:00-9:50 AM ISTB4 101"))

    view = interaction.followup.kwargs["view"]
    assert [c.label for c in view.children] == ["Confirm", "Cancel"]
    assert interaction.followup.kwargs["ephemeral"] is True
    press = type("Interaction", (), {})()
    press.user = interaction.user
    press.response = FakeResponse()
    asyncio.run(view.children[0].callback(press))  # Confirm
    assert agent.saved == ("123", "456", agent.pending["123"])
