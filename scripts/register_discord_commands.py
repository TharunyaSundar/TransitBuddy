"""Register the Discord bot's guild slash commands."""

import asyncio

from src.discord_bot.client import register_discord_commands


if __name__ == "__main__":
	asyncio.run(register_discord_commands())
