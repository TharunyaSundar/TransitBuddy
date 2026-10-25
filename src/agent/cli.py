"""Chat with the agent in the terminal using the fictional demo database (no Discord, no MongoDB).

    cd src && python -m agent.cli
Commands: /as <userId>  switch student (1001 Alex, 1002 Priya, 1003 Jordan, 1004 Sam)
          /mention <id> [id...]  @mention students in the next messages (/mention to clear)
          /image <path>  extract a schedule screenshot     /confirm  save the pending schedule
"""
import asyncio
import logging
import os
from pathlib import Path

from dotenv import load_dotenv


async def main() -> None:
    from . import AgentService
    from .dev_database import DEMO_GUILD, demo_database
    db = demo_database()
    svc = AgentService(db)
    user, mentioned = "1001", []
    print(__doc__)
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
            r = await svc.extract_schedule_from_image(path.read_bytes(), mime, user, DEMO_GUILD)
            print(r["formatted"] or "(nothing found)")
            for w in r["validationWarnings"]:
                print("  warning:", w)
            print("Type /confirm to save it.")
            continue
        if line == "/confirm":
            try:
                await svc.save_confirmed_schedule(user, DEMO_GUILD)
                print("Saved as confirmed.")
            except ValueError as e:
                print("Not saved:", e)
            continue
        resp = await svc.process_message({"message": line, "discordUserId": user, "discordGuildId": DEMO_GUILD,
                                          "channelId": "cli", "mentionedUserIds": mentioned})
        print(resp["responseText"])
        print(f"  (skills: {resp['metadata']['skillsUsed']}, tools: {resp['metadata']['toolsCalled']})\n")


if __name__ == "__main__":
    load_dotenv()
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "WARNING"))
    asyncio.run(main())
