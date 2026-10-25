"""/schedule upload and /schedule view.

Everything is ephemeral (only the student sees it). An uploaded screenshot is read by the agent and shown
for review; it is saved only when the student presses Confirm (AgentService.save_confirmed_schedule).
"""
from typing import Callable

import discord
from discord import app_commands

from src.utils.logger import log

from .setup import SetupPromptView

MAX_IMAGE_BYTES = 8 * 1024 * 1024
REVIEW_TIMEOUT_S = 600
SEMESTER_HINT = ("The screenshot doesn't show the semester. Cancel and upload again with the semester option, "
                 "for example: /schedule upload semester: Fall 2026")
NOT_READY = "Schedules aren't available right now: the bot isn't connected to its database. Please try again later."


def _review_text(body: str, warnings: list[str]) -> str:
    text = f"Here's what I read from your screenshot:\n{body}"
    if warnings:
        text += "\n\nPlease check:\n" + "\n".join(f"- {w}" for w in warnings)
    text += "\n\nPress Confirm to save it, or Cancel to discard it."
    return text[:1990]


class ConfirmScheduleView(discord.ui.View):
    """Confirm / Cancel for one extracted schedule. Only the student who uploaded it can press them."""

    def __init__(self, agent, user_id: str, guild_id: str, schedule: dict):
        super().__init__(timeout=REVIEW_TIMEOUT_S)
        self.agent, self.user_id, self.guild_id, self.schedule = agent, user_id, guild_id, schedule

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return str(interaction.user.id) == self.user_id

    def _forget_if_still_pending(self) -> None:
        if self.agent.pending_schedule(self.user_id) is self.schedule:  # a newer upload replaces this one
            self.agent.discard_pending_schedule(self.user_id)

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        try:
            await self.agent.save_confirmed_schedule(self.user_id, self.guild_id, self.schedule)
        except ValueError as error:  # a class is missing a code, location or valid times
            await interaction.response.send_message(f"Not saved: {error}", ephemeral=True)
            return
        except Exception as error:
            log(f"Saving schedule failed: {error}")
            await interaction.response.send_message("Saving failed. Please try again in a minute.", ephemeral=True)
            return
        self.stop()
        await interaction.response.edit_message(
            content="Saved your schedule. Use /schedule view to see it.\nNext, set up your commute so I can plan "
                    "trips: your area, usual departure time, ride-sharing and (optional, private) home address.",
            view=SetupPromptView(self.agent, self.user_id))

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self._forget_if_still_pending()
        self.stop()
        await interaction.response.edit_message(content="Not saved. Upload it again any time with "
                                                        "/schedule upload.", view=None)

    async def on_timeout(self) -> None:
        self._forget_if_still_pending()


def build_schedule_group(get_agent: Callable[[], object]) -> app_commands.Group:
    group = app_commands.Group(name="schedule", description="Upload or view your class schedule.",
                               guild_only=True)

    @group.command(name="upload", description="Upload a screenshot of your class schedule to review and save.")
    @app_commands.describe(image="A screenshot of your schedule (for example from My ASU)",
                           semester="The term, for example Fall 2026 (if the screenshot doesn't show it)")
    async def upload(interaction: discord.Interaction, image: discord.Attachment,
                     semester: str | None = None) -> None:
        if not (image.content_type or "").startswith("image/"):
            await interaction.response.send_message("Please attach an image (PNG or JPG) of your schedule.",
                                                    ephemeral=True)
            return
        if image.size > MAX_IMAGE_BYTES:
            await interaction.response.send_message("That image is too large (8 MB max).", ephemeral=True)
            return
        agent = get_agent()
        if agent is None:
            await interaction.response.send_message(NOT_READY, ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)  # reading takes a few seconds
        user_id, guild_id = str(interaction.user.id), str(interaction.guild_id)
        try:
            result = await agent.extract_schedule_from_image(await image.read(), image.content_type,
                                                             user_id, guild_id)
        except Exception as error:
            log(f"Schedule extraction failed: {error}")
            await interaction.followup.send("I couldn't read that screenshot right now. Please try again.",
                                            ephemeral=True)
            return
        schedule = result.extracted_schedule
        warnings = list(result.validation_warnings)
        if semester and semester.strip():
            schedule["semester"] = semester.strip()  # same dict the agent holds for Confirm
        if schedule.get("semester"):
            warnings = [w for w in warnings if not w.startswith("Semester not shown")]
        else:
            warnings = [SEMESTER_HINT if w.startswith("Semester not shown") else w for w in warnings]
        if not schedule.get("courses"):  # the warnings say why: timeout, model error, or no classes in it
            await interaction.followup.send("\n".join(warnings) or "I couldn't find any classes in that image.",
                                            ephemeral=True)
            return
        view = ConfirmScheduleView(agent, user_id, guild_id, schedule)
        await interaction.followup.send(_review_text(agent.format_schedule(schedule), warnings),
                                        view=view, ephemeral=True)

    @group.command(name="view", description="Show your saved class schedule.")
    async def view(interaction: discord.Interaction) -> None:
        agent = get_agent()
        if agent is None:
            await interaction.response.send_message(NOT_READY, ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            text = await agent.view_schedule(str(interaction.user.id), str(interaction.guild_id))
        except Exception as error:
            log(f"Viewing schedule failed: {error}")
            text = "I couldn't load your schedule right now. Please try again in a minute."
        await interaction.followup.send(text, ephemeral=True)

    return group
