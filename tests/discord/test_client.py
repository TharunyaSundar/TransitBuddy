import asyncio

import discord

from src.shared.contracts import AgentResponse
from src.discord_bot.client import create_discord_client


def test_client_uses_non_privileged_guild_intents():
    client = create_discord_client()

    assert client.intents.guilds
    assert client.intents.guild_messages
    assert not client.intents.message_content


def test_client_registers_ping_and_status_commands():
    client = create_discord_client()

    ping = client.tree.get_command("ping")
    status = client.tree.get_command("status")
    ask = client.tree.get_command("ask")

    assert isinstance(ping, discord.app_commands.Command)
    assert isinstance(status, discord.app_commands.Command)
    assert isinstance(ask, discord.app_commands.Command)


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
