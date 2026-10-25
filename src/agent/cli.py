"""Chat with the agent in the terminal (no Discord).

    python -m src.agent.cli            fictional in-memory demo data
    python -m src.agent.cli --mongo    Developer 2's MongoDB (MONGODB_URI; seed: python -m scripts.seed_demo_data)
Commands: /as <user_id>  switch student (demo data: 1001 Alex, 1002 Priya, 1003 Jordan, 1004 Sam;
                         seeded MongoDB: 900000000000000001 to ...004)
          /mention <id> [id...]  @mention students in the next messages (/mention to clear)
          /image <path>  extract a schedule screenshot     /confirm  save the pending schedule
"""
import asyncio
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv


async def main(use_mongo: bool) -> None:
    from . import AgentService
    from .dev_database import DEMO_GUILD, demo_database
    if use_mongo:
        from ..database import DatabaseService, connect_database, disconnect_database
        await connect_database()
        db, user = DatabaseService(), "900000000000000001"
    else:
        db, user = demo_database(), "1001"
    svc = AgentService(db)
    mentioned = []
    print(__doc__)
    try:
        await _loop(svc, user, mentioned, DEMO_GUILD)
    finally:
        if use_mongo:
            await disconnect_database()


async def _loop(svc, user: str, mentioned: list, guild: str) -> None:
    while True:
        try:
            line = (await asyncio.to_thread(input, f"[{user}]> ")).strip()
        except EOFError:
            return
        if not line:
            continue
        if line.startswith("/as "):
            user = line.split()[1]
            continue
        if line.startswith("/mention"):
            mentioned = line.split()[1:]
            continue
        if line.startswith("/image "):
            path = Path(line[7:].strip()).expanduser()
            mime = "image/jpeg" if path.suffix.lower() in (".jpg", ".jpeg") else "image/png"
            r = await svc.extract_schedule_from_image(path.read_bytes(), mime, user, guild)
            print(svc.format_schedule(r.extracted_schedule) or "(nothing found)")
            for w in r.validation_warnings:
                print("  warning:", w)
            print("Type /confirm to save it.")
            continue
        if line == "/confirm":
            try:
                await svc.save_confirmed_schedule(user, guild)
                print("Saved as confirmed.")
            except ValueError as e:
                print("Not saved:", e)
            continue
        resp = await svc.process_message({"message": line, "discord_user_id": user, "discord_guild_id": guild,
                                          "channel_id": "cli", "mentioned_user_ids": mentioned})
        print(resp.response_text)
        print(f"  (skills: {resp.metadata['skills_used']}, tools: {resp.metadata['tools_called']})\n")


if __name__ == "__main__":
    load_dotenv()
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "WARNING"))
    asyncio.run(main("--mongo" in sys.argv))
