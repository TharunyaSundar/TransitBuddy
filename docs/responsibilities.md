# Developer Responsibilities

This project is intentionally split into three independent implementation tracks. Each developer has a clear ownership area to reduce integration risk during the hackathon.

## Developer 1 — Discord Integration

Branch: feature/discord-bot

Responsibilities:

1. Create the Discord application.
2. Configure bot permissions.
3. Invite the bot to the development Discord server.
4. Implement the discord.py client.
5. Implement slash commands.
6. Handle bot mentions.
7. Handle screenshot uploads.
8. Forward screenshots to AgentService.
9. Display extracted schedules.
10. Implement confirmation buttons.
11. Forward student messages to the LangChain agent.
12. Display agent responses in Discord.
13. Handle errors and timeouts.
14. Test Discord interactions.

Owned area:

- transit_buddy/discord_bot/
- scripts/register_discord_commands.py
- tests/discord/

Non-goals:

- No database models.
- No LangChain reasoning.

## Developer 2 — MongoDB Database

Branch: feature/mongodb

Responsibilities:

1. Create MongoDB Atlas database.
2. Configure database connectivity.
3. Create Pydantic/PyMongo models.
4. Implement student storage.
5. Implement class schedule storage.
6. Implement commute preference storage.
7. Implement ride request storage.
8. Implement repository methods.
9. Implement database services.
10. Add schema validation.
11. Create indexes.
12. Create fictional ASU demo data.
13. Test database operations.

Owned area:

- transit_buddy/database/
- scripts/seed_demo_data.py
- tests/database/

Non-goals:

- No Discord interactions.
- No LangChain reasoning.

## Developer 3 — LangChain Agent

Branch: feature/langchain-agent

Responsibilities:

1. Configure LangChain (Python).
2. Configure the selected LLM.
3. Implement multimodal screenshot extraction.
4. Implement the AI agent.
5. Implement the skill loader.
6. Create skill instructions.
7. Implement LangChain tools.
8. Query student schedules through DatabaseService.
9. Implement commute matching logic.
10. Implement ride-sharing coordination.
11. Implement availability calculations.
12. Handle conflicting student constraints.
13. Generate Discord-friendly responses.
14. Test agent behavior.

Owned area:

- transit_buddy/agent/
- transit_buddy/skills/
- tests/agent/

Non-goals:

- No Discord handlers.
- No database models.

## Collaboration Rule

All cross-system communication must follow the documented shared contracts and service interfaces. This keeps the project modular and lets each developer capture their own milestone branch under a clear domain boundary.
