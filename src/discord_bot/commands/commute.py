"""Commute interaction handlers (not currently registered as slash commands).

Replies are private (ephemeral) by default. The group-plan handler can share a proposal with the channel.
Only names, general areas and approximate times of other students are shown.
"""
from typing import Callable

import discord
from discord import app_commands

from src.agent.commute_response import CommutePlanResponse
from src.utils.logger import log

from .schedule import NOT_READY
from .setup import open_setup_form

DIRECTIONS = [app_commands.Choice(name="to campus", value="to_campus"),
              app_commands.Choice(name="from campus", value="from_campus")]
DAY_HELP = "today, tomorrow, a weekday (Monday) or a date (2026-10-26)"
_COMMUTE_COLORS = {
    "success": discord.Color.green(),
    "clarification": discord.Color.gold(),
    "unsupported": discord.Color.orange(),
    "error": discord.Color.red(),
}
_COMMUTE_TITLES = {
    "success": "🚌 Your Commute Plan",
    "clarification": "❓ Commute Details Needed",
    "unsupported": "ℹ️ Commute Plan Not Supported",
    "error": "⚠️ Commute Plan Unavailable",
}


def commute_plan_embed(result: CommutePlanResponse) -> discord.Embed:
    """Render an address-free commute result as a concise Discord embed."""
    embed = discord.Embed(
        title=_COMMUTE_TITLES[result.status],
        description=result.description,
        color=_COMMUTE_COLORS[result.status],
    )
    if result.status == "success":
        course = " — ".join(value for value in (result.course_code, result.course_name) if value)
        fields = (
            ("📚 Course", course or None),
            ("⏰ Class starts", result.class_start_time),
            ("📍 Campus building", result.campus_building),
            ("📅 Travel date", result.travel_date),
            ("🎯 Target arrival", result.target_arrival_time),
            ("🕒 Estimated commute", f"~{result.estimated_duration_minutes} minutes (estimate)"
             if result.estimated_duration_minutes is not None else None),
            ("🚶 Recommended departure", f"~{result.recommended_departure_time} (estimate)"
             if result.recommended_departure_time else None),
            ("🚌 Transport", result.transport_mode),
        )
        for name, value in fields:
            if value:
                embed.add_field(name=name, value=value, inline=True)
    embed.set_footer(text="Transit conditions may change. Travel duration and departure times are estimates.")
    return embed


def _as_commute_response(result: CommutePlanResponse | str) -> CommutePlanResponse:
    if isinstance(result, CommutePlanResponse):
        return result
    return CommutePlanResponse(
        status="error",
        description="I couldn't prepare your commute plan right now. Please try again in a minute.",
    )


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

    @group.command(name="setup", description="Save your home address, area, usual departure time and matching opt-in.")
    async def setup(interaction: discord.Interaction) -> None:
        agent = get_agent()
        if agent is None:
            await interaction.response.send_message(NOT_READY, ephemeral=True)
            return
        await open_setup_form(interaction, agent)

    @group.command(name="forget-address", description="Delete your commute profile, including your home address.")
    async def forget_address(interaction: discord.Interaction) -> None:
        user, guild = str(interaction.user.id), str(interaction.guild_id)
        await _answer(interaction, get_agent, lambda a: a.delete_commute_profile(user, guild))

    return group


def build_commute_plan_group(get_agent: Callable[[], object]) -> app_commands.Group:
    group = app_commands.Group(name="commute", description="Plan your commute to or from campus.",
                               guild_only=True)

    @group.command(name="plan", description="Plan a campus commute using a natural-language request.")
    @app_commands.describe(request="Describe where and when you need to travel.")
    async def plan(interaction: discord.Interaction, request: str) -> None:
        user, guild = str(interaction.user.id), str(interaction.guild_id or "dm")
        agent = get_agent()
        if agent is None:
            result = CommutePlanResponse(
                status="error",
                description="Transit Buddy is unavailable right now. Please try again in a minute.",
            )
            await interaction.response.send_message(embed=commute_plan_embed(result), ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            result = await agent.commute_plan_request(user, guild, request)
        except Exception as error:
            log(f"/commute plan failed ({type(error).__name__}).")
            result = CommutePlanResponse(
                status="error",
                description="I couldn't prepare your commute plan right now. Please try again in a minute.",
            )
        await interaction.followup.send(
            embed=commute_plan_embed(_as_commute_response(result)),
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    return group
