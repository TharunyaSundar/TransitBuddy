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
from src.agent import AgentService
from src.shared.contracts import ProcessMessageContext

agent = AgentService(database_service)   # Developer 2's DatabaseService instance

# every DM or @mention
resp = await agent.process_message(ProcessMessageContext(
    message=text_without_the_bot_mention,
    discord_user_id=str(message.author.id),
    discord_guild_id=str(message.guild.id) if message.guild else "dm",
    channel_id=str(message.channel.id),
    mentioned_user_ids=[str(u.id) for u in message.mentions if not u.bot],
))
await message.reply(resp.response_text)                 # at most 1,900 characters
# resp.metadata: skills_used, tools_called, and when the student typed their classes:
# resp.metadata["pending_schedule"] -> show Confirm / Edit buttons, like a screenshot

# screenshot uploads -> ScheduleExtractionResult
result = await agent.extract_schedule_from_image(await attachment.read(), attachment.content_type,
                                                 user_id, guild_id)
text = agent.format_schedule(result.extracted_schedule)  # short list to show with the buttons
# result.validation_warnings: show these too; result.confirmation_required is always True

# Confirm button (the ONLY path that saves a schedule). Not in docs/integration-contracts.md yet.
await agent.save_confirmed_schedule(user_id, guild_id)            # or pass an edited schedule as 3rd arg
agent.discard_pending_schedule(user_id)                           # Edit / Cancel button
text = await agent.view_schedule(user_id, guild_id)              # saved + pending schedule, for /schedule view
# /commute commands: structured input, answered without the language model
text = await agent.commute_availability(user_id, guild_id, "today", classmate_ids)
text = await agent.commute_match(user_id, guild_id, "today", "to_campus", "9:00 AM", classmate_ids)
text = await agent.commute_plan(user_id, guild_id, classmate_ids, "today", "to_campus", travel_minutes=25,
                                arrive_by=None, constraints="Priya can't leave before 8:30 AM")
```

The agent never sends Discord messages and never saves an unconfirmed schedule. `/schedule upload` and
`/schedule view` (`src/discord_bot/commands/schedule.py`) and the `/commute` commands
(`src/discord_bot/commands/commute.py`) are working examples of these calls.

## Wiring with Developer 2's database

The app (Developer 1's startup code) connects once and passes the real service in:

```python
from src.agent import AgentService
from src.database import DatabaseService, connect_database

await connect_database()                      # MONGODB_URI / MONGODB_DATABASE from .env
agent = AgentService(DatabaseService())
```

How the agent works with `src/database`:
- Every write is validated into the shared model (`StudentSchedule`, `CommutePreferences`, `RideRequest`) before
  it reaches `DatabaseService`, and results are read back with `model_dump()` (`agent/db.py`).
- `save_schedule` only accepts courses that pass the shared `is_valid_course`: a course code, a location and
  valid meeting times (course name and section are optional). The agent applies the same check, and
  `save_confirmed_schedule` raises `ValueError` saying which class needs what, so Discord can ask the student.
- `create_ride_request` sends an empty `request_id`, and the database assigns it.
- If MongoDB is down or not connected, the tool reports a database problem and the agent tells the student;
  the reply doesn't crash.
- The contract has no "all opted-in students in a server" query, so "anyone heading to campus at 9?" only
  searches @mentioned students and students with open ride requests. Adding
  `async get_opted_in_commute_preferences(discord_guild_id) -> list[CommutePreferences]` to `DatabaseService`
  (the `guild_optin` index already exists) would let it search the whole server; the agent uses it
  automatically when it's there.

`dev_database.py` is an in-memory version of the same contract with four fictional students, for tests and
for the terminal chat without MongoDB.

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
cp .env.example .env                                  # LLM_MODEL=glm-5.3-flash:cloud, LLM_REASONING=low
.venv/bin/python -m pytest tests                      # offline: agent, shared and database unit tests
TEST_MONGODB_URI=mongodb://localhost:27017 .venv/bin/python -m pytest tests   # plus real-MongoDB tests
.venv/bin/python tests/agent/live_smoke.py [schedule.png]   # real model, demo data
.venv/bin/python -m src.agent.cli                    # terminal chat, demo data (/as, /mention, /image, /confirm)
.venv/bin/python -m src.agent.cli --mongo            # terminal chat on MongoDB (MONGODB_URI; seed with
                                                      # python -m scripts.seed_demo_data, guild demo-guild)
```

`tests/agent/test_with_database.py` runs the agent against Developer 2's `DatabaseService` on a real MongoDB,
in its own `transit_buddy_agent_test` database that it drops afterwards.

Model choice: `glm-5.3-flash:cloud` with thinking set to low. Among the Ollama flash models tested, it used the
fewest tokens on tool calls, and it reads schedule screenshots. Change it with `LLM_MODEL`.

## Known limits

- Chat history lives in memory (the last 10 messages per student per channel) and resets on restart.
- Travel time between areas isn't looked up. Group plans use the time the students give, or 30 minutes, which the
  reply calls an estimate.
- Live transit and campus shuttles are out of scope (README: future improvements).
