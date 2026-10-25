"""/commute plan: the student describes their trip in their own words; the agent checks their timetable and
suggests a bus route with a backup. The reply is private (only the student sees it).
"""
from typing import Callable

import discord
from discord import app_commands

from src.utils.logger import log

NOT_READY = "Commute plans aren't available right now: the bot isn't connected to its database. Please try again later."


def build_commute_plan_group(get_agent: Callable[[], object]) -> app_commands.Group:
    group = app_commands.Group(name="commute", description="Plan your trip to campus.", guild_only=True)

    @group.command(name="plan", description="Get a bus route to class: when to leave, which bus, and a backup.")
    @app_commands.describe(request="e.g. how do I get to my Monday class? / I'm at Tempe Marketplace, CSE 110 tomorrow")
    async def plan(interaction: discord.Interaction, request: str = "my next class") -> None:
        agent = get_agent()
        if agent is None:
            await interaction.response.send_message(NOT_READY, ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)  # the trip planner takes a few seconds
        try:
            text = await agent.plan_commute(str(interaction.user.id), str(interaction.guild_id),
                                            request.strip() or "my next class")
        except Exception as error:
            log(f"/commute plan failed: {error}")
            text = "I couldn't plan that right now. Please try again in a minute."
        await interaction.followup.send(text, ephemeral=True)

    return group
