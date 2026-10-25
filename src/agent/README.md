# Transit Buddy agent (Developer 3)

A Python LangChain agent (`create_agent`, which runs on LangGraph) on an Ollama model. It sits between the
Discord bot (Developer 1) and the database (Developer 2):

```text
Discord (Developer 1) --AgentService--> agent (this folder) --DatabaseService--> MongoDB (Developer 2)
```

The model handles the conversation and chooses tools. The rules that must be right are plain Python with tests:
schedule cleanup and validation, availability, partner matching and group negotiation (`logic/`). Tools return
only general areas and approximate times for other students, and only students who opted in are matched.

## For Developer 1 (Discord)

```python
from agent import AgentService

agent = AgentService(database_service)   # Developer 2's DatabaseService instance

# every DM or @mention
resp = await agent.process_message({
    "message": text_without_the_bot_mention,
    "discordUserId": str(message.author.id),
    "discordGuildId": str(message.guild.id) if message.guild else "dm",
    "channelId": str(message.channel.id),
    "mentionedUserIds": [str(u.id) for u in message.mentions if not u.bot],
    "displayName": message.author.display_name,          # optional
})
await message.reply(resp["responseText"])               # at most 1,900 characters
# resp["metadata"]: skillsUsed, toolsCalled, and when the student typed their classes:
# resp["metadata"]["pendingSchedule"] -> show Confirm / Edit buttons, like a screenshot

# screenshot uploads
result = await agent.extract_schedule_from_image(await attachment.read(), attachment.content_type,
                                                 user_id, guild_id)
# result: extractedSchedule, validationWarnings, confirmationRequired (always True), formatted (ready to show)

# Confirm button (the ONLY path that saves a schedule)
await agent.save_confirmed_schedule(user_id, guild_id)            # or pass an edited schedule as 3rd arg
agent.discard_pending_schedule(user_id)                           # Edit / Cancel button
```

The agent never sends Discord messages and never saves an unconfirmed schedule.

## For Developer 2 (database)

`AgentService` takes any object with the `DatabaseService` methods from `docs/integration-contracts.md`, named in
snake_case (`get_student_schedule`, `save_commute_preferences`, `get_open_ride_requests`, and so on; full list in
`contracts.py`). Methods can be sync or async. Field names stay as documented (`discordUserId`,
`meetingPatterns`, ...).

One addition is requested: `get_opted_in_commute_preferences(discord_guild_id) -> list[CommutePreferences]`, so
"anyone heading to campus at 9?" can search the whole server. Without it, matching only sees @mentioned students
and students with open ride requests.

`dev_database.py` is an in-memory version of the contract with four fictional students, which the agent's tests
use. You can use it as a reference.

## Tools the model can call

| Tool | What it does |
| --- | --- |
| `get_my_schedule` | The student's saved schedule and whether it's confirmed |
| `prepare_schedule_from_text` | Typed classes, checked and held for the Confirm button (not saved) |
| `get_availability` | On campus by, classes over at, usual window: the student plus anyone @mentioned |
| `find_commute_partners` | Opted-in students, same general area, times within 30 minutes |
| `propose_group_departure` | Common departure window, or the best compromise and who would have to move by how much |
| `get_my_commute_preferences` / `save_commute_preferences` | General area only (street addresses are refused), modes, window, opt-in |
| `list_open_ride_requests` / `create_ride_request` / `update_my_ride_request` | Ride requests (students can only change their own) |

Skills are `src/skills/*/SKILL.md`. Each skill's description always goes into the prompt; the full rules go in
only for the one or two skills that match the message, to keep token use low.

## Setup and testing

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env                       # LLM_MODEL=glm-5.3-flash:cloud, LLM_REASONING=low
.venv/bin/python -m unittest discover -s tests/agent -v    # 29 offline tests: no model, network or database
.venv/bin/python tests/agent/live_smoke.py [schedule.png]  # real model, demo data
cd src && ../.venv/bin/python -m agent.cli                 # chat in the terminal (/as, /mention, /image, /confirm)
```

Model choice: `glm-5.3-flash:cloud` with thinking set to low. Among the Ollama flash models tested, it used the
fewest tokens on tool calls, and it reads schedule screenshots. Change it with `LLM_MODEL`.

## Known limits

- Chat history lives in memory (the last 10 messages per student per channel) and resets on restart.
- Travel time between areas isn't looked up. Group plans use the time the students give, or 30 minutes, which the
  reply calls an estimate.
- Live transit and campus shuttles are out of scope (README: future improvements).
