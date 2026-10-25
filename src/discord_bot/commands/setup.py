"""The commute setup form (a Discord modal): home address (required, private), general area, usual departure
time, transport and the commute-matching opt-in, saved on the student record. Opened by the "Set up your commute"
button after a schedule is saved and under /schedule view. Everything is ephemeral; the address is never shown
to anyone else.
"""
import discord

from src.utils.logger import log


class CommuteSetupModal(discord.ui.Modal, title="Commute setup"):
    def __init__(self, agent, guild_id: str, defaults: dict):
        super().__init__(timeout=600)
        self.agent, self.guild_id = agent, guild_id
        def field(text, description, **kw):
            box = discord.ui.TextInput(**kw)
            self.add_item(discord.ui.Label(text=text, description=description, component=box))
            return box

        self.address = field("Home address (required)", "Private: only used for your own trip times",
                             max_length=200, placeholder="e.g. 123 E Main St, Mesa, AZ",
                             default=defaults.get("address") or None)
        self.area = field("General area you come from", "Needed to be matched with nearby students",
                          required=False, max_length=60, placeholder="e.g. Mesa, Downtown Phoenix, North Tempe",
                          default=defaults.get("area") or None)
        self.window = field("Usual time you leave for campus", None, required=False, max_length=30,
                            placeholder="e.g. 8:00-8:30 AM", default=defaults.get("window") or None)
        self.modes = field("How you get there", None, required=False, max_length=60,
                           placeholder="e.g. carpool, bus, bike", default=defaults.get("modes") or None)
        self.opt_in = field("Match me with students near me?", "Only students who say yes are matched",
                            max_length=5, placeholder="yes or no", default=defaults.get("opt_in") or "no")

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)  # checking the address takes a moment
        try:
            text = await self.agent.save_commute_setup(
                str(interaction.user.id), self.guild_id, self.area.value, self.window.value, self.modes.value,
                self.opt_in.value, self.address.value, display_name=getattr(interaction.user, "display_name", None))
        except ValueError as error:
            text = f"Not saved: {error} Use the Set up your commute button to try again."
        except Exception as error:
            log(f"Saving commute setup failed: {error}")
            text = "Saving failed. Please try again in a minute."
        await interaction.followup.send(text, ephemeral=True)


async def open_setup_form(interaction: discord.Interaction, agent) -> None:
    """Show the form, pre-filled with what the student saved before (only they see it)."""
    guild_id = str(interaction.guild_id or "dm")
    try:
        defaults = await agent.commute_setup_defaults(str(interaction.user.id), guild_id)
    except Exception as error:
        log(f"Loading commute setup failed: {error}")
        defaults = {}
    await interaction.response.send_modal(CommuteSetupModal(agent, guild_id, defaults))


class SetupPromptView(discord.ui.View):
    """"Set up your commute" (opens the form), plus "Delete my commute profile" when the student has one.
    Shown after a schedule is saved and under /schedule view."""

    def __init__(self, agent, user_id: str, can_delete: bool = False):
        super().__init__(timeout=600)
        self.agent, self.user_id = agent, user_id
        if not can_delete:
            self.remove_item(self.delete)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return str(interaction.user.id) == self.user_id

    @discord.ui.button(label="Set up your commute", style=discord.ButtonStyle.primary)
    async def setup(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await open_setup_form(interaction, self.agent)

    @discord.ui.button(label="Delete my commute profile", style=discord.ButtonStyle.danger)
    async def delete(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        try:
            text = await self.agent.delete_commute_profile(self.user_id, str(interaction.guild_id or "dm"))
        except Exception as error:
            log(f"Deleting commute profile failed: {error}")
            text = "Deleting failed. Please try again in a minute."
        button.disabled = True
        await interaction.response.edit_message(view=self)
        await interaction.followup.send(text, ephemeral=True)
