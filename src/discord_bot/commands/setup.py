"""The commute setup form (a Discord modal): general area, usual departure time, transport, ride-sharing
opt-in and an optional, private home address. Opened by /commute setup or the button shown after a schedule
is saved. Everything is ephemeral; the address is never shown back to anyone.
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

        self.area = field("General area you come from", "Used to match you with nearby students",
                          max_length=60, placeholder="e.g. Mesa, Downtown Phoenix, North Tempe",
                          default=defaults.get("area") or None)
        self.window = field("Usual time you leave for campus", None, required=False, max_length=30,
                            placeholder="e.g. 8:00-8:30 AM", default=defaults.get("window") or None)
        self.modes = field("How you get there", None, required=False, max_length=60,
                           placeholder="e.g. carpool, bus, bike", default=defaults.get("modes") or None)
        self.opt_in = field("Match me with others for shared rides?", "Only students who say yes are matched",
                            max_length=5, placeholder="yes or no", default=defaults.get("opt_in") or "no")
        self.address = field("Home address (optional)", "Private: only used for your own trip times",
                             required=False, max_length=200, placeholder="e.g. 123 E Main St, Mesa, AZ",
                             default=defaults.get("address") or None)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)  # checking the address takes a moment
        try:
            text = await self.agent.save_commute_setup(
                str(interaction.user.id), self.guild_id, self.area.value, self.window.value, self.modes.value,
                self.opt_in.value, self.address.value)
        except ValueError as error:
            text = f"Not saved: {error} Run /commute setup to try again."
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
    """Shown after a schedule is saved: one button that opens the setup form."""

    def __init__(self, agent, user_id: str):
        super().__init__(timeout=600)
        self.agent, self.user_id = agent, user_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return str(interaction.user.id) == self.user_id

    @discord.ui.button(label="Set up your commute", style=discord.ButtonStyle.primary)
    async def setup(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await open_setup_form(interaction, self.agent)
