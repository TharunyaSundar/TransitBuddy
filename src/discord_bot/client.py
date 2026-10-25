"""Discord client and guild slash-command registration."""

import re

import discord
from discord import app_commands
from discord.ext import commands

from src.config import settings
from src.discord_bot.commands.commute import build_commute_group
from src.discord_bot.commands.schedule import build_schedule_group
from src.shared.contracts import ProcessMessageContext
from src.utils.logger import log

_USER_MENTION = re.compile(r"<@!?(\d+)>")


def create_discord_client(
	*, register_commands_only: bool = False, agent_service=None
) -> commands.Bot:
	intents = discord.Intents.default()
	intents.guild_messages = True
	bot = commands.Bot(command_prefix=commands.when_mentioned, intents=intents)
	bot.agent = agent_service
	bot.tree.add_command(build_schedule_group(lambda: bot.agent))
	bot.tree.add_command(build_commute_group(lambda: bot.agent))

	@bot.tree.command(name="ping", description="Check whether Transit Buddy is online.")
	async def ping(interaction: discord.Interaction) -> None:
		await interaction.response.send_message("Pong! Transit Buddy is online.")

	@bot.tree.command(name="status", description="Show the current Transit Buddy bot status.")
	async def status(interaction: discord.Interaction) -> None:
		if bot.agent is None:
			text = "Transit Buddy is online, but schedule and assistant features are unavailable."
		else:
			text = "Transit Buddy is online. Use /ask, /schedule, or /commute for help."
		await interaction.response.send_message(text)

	@bot.tree.command(name="ask", description="Ask Transit Buddy about schedules and commutes.")
	@app_commands.describe(question="Ask about your schedule, availability, or commute options.")
	async def ask(interaction: discord.Interaction, question: str) -> None:
		if not question.strip():
			await interaction.response.send_message("Enter a question for Transit Buddy.", ephemeral=True)
			return

		await interaction.response.defer(ephemeral=True, thinking=True)
		try:
			if bot.agent is None:
				await interaction.followup.send(
					"Transit Buddy's assistant is unavailable because its database isn't connected.",
					ephemeral=True,
				)
				return
			response = await bot.agent.process_message(ProcessMessageContext(
				message=question.strip(),
				discord_user_id=str(interaction.user.id),
				discord_guild_id=str(interaction.guild_id or "dm"),
				channel_id=str(interaction.channel_id),
				mentioned_user_ids=_USER_MENTION.findall(question),
			))
			await interaction.followup.send(response.response_text, ephemeral=True)
		except Exception as error:
			log(f"Discord /ask failed: {error}")  # log is a plain function, not a logging.Logger
			await interaction.followup.send(
				"Transit Buddy's assistant is unavailable right now. Please try again later.",
				ephemeral=True,
			)

	async def sync_guild_commands() -> None:
		if not settings.discord_guild_id:
			log("DISCORD_GUILD_ID missing; slash-command sync is skipped.")
			return

		guild = discord.Object(id=int(settings.discord_guild_id))
		bot.tree.copy_global_to(guild=guild)
		await bot.tree.sync(guild=guild)
		log("Discord slash commands registered successfully.")

	async def setup_agent() -> None:
		if bot.agent is not None:
			return
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
	finally:
		from src.database import disconnect_database

		await disconnect_database()
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
