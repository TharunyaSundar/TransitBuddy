"""Discord client and guild slash-command registration."""

import discord
from discord.ext import commands

from src.config import settings
from src.discord_bot.commands.commute import build_commute_group
from src.discord_bot.commands.schedule import build_schedule_group
from src.utils.logger import log


def create_discord_client(*, register_commands_only: bool = False) -> commands.Bot:
	intents = discord.Intents.default()
	intents.guild_messages = True
	bot = commands.Bot(command_prefix=commands.when_mentioned, intents=intents)
	bot.agent = None  # AgentService, created in setup_hook once MongoDB is connected
	bot.tree.add_command(build_schedule_group(lambda: bot.agent))
	bot.tree.add_command(build_commute_group(lambda: bot.agent))

	@bot.tree.command(name="ping", description="Check whether Transit Buddy is online.")
	async def ping(interaction: discord.Interaction) -> None:
		await interaction.response.send_message("Pong! Transit Buddy is online.")

	@bot.tree.command(name="status", description="Show the current Transit Buddy bot status.")
	async def status(interaction: discord.Interaction) -> None:
		if bot.agent is None:
			text = "Transit Buddy is online. Schedule features are not connected (database unavailable)."
		else:
			text = "Transit Buddy is online. Use /schedule to save your classes and /commute to plan trips."
		await interaction.response.send_message(text)

	async def sync_guild_commands() -> None:
		if not settings.discord_guild_id:
			log("DISCORD_GUILD_ID missing; slash-command sync is skipped.")
			return

		guild = discord.Object(id=int(settings.discord_guild_id))
		bot.tree.copy_global_to(guild=guild)
		await bot.tree.sync(guild=guild)
		log("Discord slash commands registered successfully.")

	async def setup_agent() -> None:
		if not settings.mongodb_uri:
			log("MONGODB_URI missing; schedule commands will report that they are unavailable.")
			return
		try:
			from src.agent import AgentService
			from src.database import DatabaseService, connect_database

			await connect_database()
			bot.agent = AgentService(DatabaseService())
			log("Agent connected to MongoDB.")
		except Exception as error:
			log(f"Agent setup failed: {error}")

	async def setup_hook() -> None:
		if not register_commands_only:
			await setup_agent()
		await sync_guild_commands()

	bot.setup_hook = setup_hook

	@bot.event
	async def on_ready() -> None:
		log(f"Discord client ready: {bot.user}")
		if register_commands_only:
			await bot.close()

	@bot.event
	async def on_message(message: discord.Message) -> None:
		if message.author.bot or bot.user is None:
			return
		if bot.user in message.mentions:
			await message.reply(
				"Transit Buddy is online and ready for schedule and commute coordination."
			)
		await bot.process_commands(message)

	return bot


async def start_discord_client() -> commands.Bot | None:
	if not settings.discord_token:
		log("DISCORD_TOKEN missing; bot startup is skipped until credentials are configured.")
		return None

	bot = create_discord_client()
	try:
		await bot.start(settings.discord_token)
	except (discord.LoginFailure, discord.PrivilegedIntentsRequired) as error:
		log(f"Discord login failed: {error}")
		await bot.close()
		return None
	except Exception as error:
		log(f"Discord client failed: {error}")
		await bot.close()
		return None
	return bot


async def register_discord_commands() -> bool:
	if not settings.discord_token or not settings.discord_guild_id:
		log("Command registration requires DISCORD_TOKEN and DISCORD_GUILD_ID.")
		return False

	bot = create_discord_client(register_commands_only=True)
	try:
		await bot.start(settings.discord_token)
	except (discord.LoginFailure, discord.PrivilegedIntentsRequired) as error:
		log(f"Discord command registration failed: {error}")
		await bot.close()
		return False
	except Exception as error:
		log(f"Discord command registration failed: {error}")
		await bot.close()
		return False
	return True
