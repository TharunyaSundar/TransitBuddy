"""/commute availability, /commute match and /commute plan.

Replies are private (ephemeral). /commute plan can be shared with the channel when share is set, so the group
sees the same proposal. Only names, general areas and approximate times of other students are shown.
"""
from typing import Callable

import discord
from discord import app_commands

from src.utils.logger import log

from .schedule import NOT_READY
from .setup import open_setup_form

DIRECTIONS = [app_commands.Choice(name="to campus", value="to_campus"),
              app_commands.Choice(name="from campus", value="from_campus")]
DAY_HELP = "today, tomorrow, a weekday (Monday) or a date (2026-10-26)"


def _classmates(interaction: discord.Interaction, *members: discord.Member | None) -> list[str]:
    """IDs of the classmates given to the command, without bots or the student themselves."""
    me = interaction.user.id
    return list(dict.fromkeys(str(m.id) for m in members if m is not None and not m.bot and m.id != me))


def _names(*members: discord.Member | None) -> dict[str, str]:
    """{user id: name shown in this server} for the classmates, so replies use names, not "a classmate"."""
    return {str(m.id): m.display_name for m in members if m is not None and getattr(m, "display_name", None)}


async def _answer(interaction: discord.Interaction, get_agent, call, private: bool = True) -> None:
    agent = get_agent()
    if agent is None:
        await interaction.response.send_message(NOT_READY, ephemeral=True)
        return
    await interaction.response.defer(ephemeral=private, thinking=True)
    try:
        text = await call(agent)
    except Exception as error:
        log(f"/commute failed: {error}")
        text = "I couldn't check that right now. Please try again in a minute."
    await interaction.followup.send(text, ephemeral=private,
                                    allowed_mentions=discord.AllowedMentions.none())


def build_commute_group(get_agent: Callable[[], object]) -> app_commands.Group:
    group = app_commands.Group(name="commute", description="Availability, commute partners and shared departures.",
                               guild_only=True)

    @group.command(name="availability", description="When you (and classmates) need to be on campus and are free.")
    @app_commands.describe(day=f"Which day: {DAY_HELP}", classmate1="Also show this classmate",
                           classmate2="Also show this classmate", classmate3="Also show this classmate")
    async def availability(interaction: discord.Interaction, day: str = "today",
                           classmate1: discord.Member | None = None, classmate2: discord.Member | None = None,
                           classmate3: discord.Member | None = None) -> None:
        user, guild = str(interaction.user.id), str(interaction.guild_id)
        others = _classmates(interaction, classmate1, classmate2, classmate3)
        names = _names(classmate1, classmate2, classmate3)
        await _answer(interaction, get_agent,
                      lambda a: a.commute_availability(user, guild, day, others, display_names=names))

    @group.command(name="match", description="Find opted-in students from your area with similar times.")
    @app_commands.describe(day=f"Which day: {DAY_HELP}", direction="Going to campus or leaving it",
                           around="A time, for example 9:00 AM (default: your class times)",
                           classmate1="Also consider this classmate", classmate2="Also consider this classmate",
                           classmate3="Also consider this classmate")
    @app_commands.choices(direction=DIRECTIONS)
    async def match(interaction: discord.Interaction, day: str = "today",
                    direction: app_commands.Choice[str] | None = None, around: str | None = None,
                    classmate1: discord.Member | None = None, classmate2: discord.Member | None = None,
                    classmate3: discord.Member | None = None) -> None:
        user, guild = str(interaction.user.id), str(interaction.guild_id)
        way = direction.value if direction else "to_campus"
        others = _classmates(interaction, classmate1, classmate2, classmate3)
        names = _names(classmate1, classmate2, classmate3)
        await _answer(interaction, get_agent,
                      lambda a: a.commute_match(user, guild, day, way, around, others, display_names=names))

    @group.command(name="plan", description="Propose one departure time for you and your classmates.")
    @app_commands.describe(classmate1="A classmate in the group", classmate2="Another classmate",
                           classmate3="Another classmate", day=f"Which day: {DAY_HELP}",
                           direction="Going to campus or leaving it",
                           travel_minutes="How long the trip takes (default 30, an estimate)",
                           arrive_by="When the group must be on campus, if not your first class (e.g. 10:00 AM)",
                           constraints="What people said, separated by ; e.g. Priya can't leave before 8:30 AM",
                           share="Post the proposal in this channel instead of only to you")
    @app_commands.choices(direction=DIRECTIONS)
    async def plan(interaction: discord.Interaction, classmate1: discord.Member,
                   classmate2: discord.Member | None = None, classmate3: discord.Member | None = None,
                   day: str = "today", direction: app_commands.Choice[str] | None = None,
                   travel_minutes: app_commands.Range[int, 1, 180] | None = None, arrive_by: str | None = None,
                   constraints: str | None = None, share: bool = False) -> None:
        user, guild = str(interaction.user.id), str(interaction.guild_id)
        way = direction.value if direction else "to_campus"
        others = _classmates(interaction, classmate1, classmate2, classmate3)
        if not others:
            await interaction.response.send_message("Add at least one classmate other than yourself.",
                                                    ephemeral=True)
            return
        await _answer(interaction, get_agent,
                      lambda a: a.commute_plan(user, guild, others, day, way, travel_minutes, arrive_by, constraints,
                                               display_names=_names(classmate1, classmate2, classmate3)),
                      private=not share)

    @group.command(name="setup", description="Save your area, usual departure time, ride-sharing and home address.")
    async def setup(interaction: discord.Interaction) -> None:
        agent = get_agent()
        if agent is None:
            await interaction.response.send_message(NOT_READY, ephemeral=True)
            return
        await open_setup_form(interaction, agent)

    @group.command(name="forget-address", description="Delete your saved home address.")
    async def forget_address(interaction: discord.Interaction) -> None:
        user, guild = str(interaction.user.id), str(interaction.guild_id)
        await _answer(interaction, get_agent, lambda a: a.forget_home_address(user, guild))

    return group
