import discord

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

    assert isinstance(ping, discord.app_commands.Command)
    assert isinstance(status, discord.app_commands.Command)