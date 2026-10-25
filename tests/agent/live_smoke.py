"""Live check with the real Ollama model and the demo database: python tests/agent/live_smoke.py [image.png]
Not part of the unit tests (needs the Ollama app running and signed in)."""
import asyncio
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # run as a script from anywhere

from dotenv import load_dotenv  # noqa: E402

from transit_buddy.agent import AgentService
from transit_buddy.agent.dev_database import DEMO_GUILD, demo_database
from agent_helpers import MONDAY_7AM

TURNS = [
    ("1001", [], "When can I leave campus today?"),
    ("1001", [], "Anyone heading to ASU around 9 AM today?"),
    ("1001", ["1002"], "Can we share an Uber to campus today? It's about 25 minutes."),
    ("1001", ["1002"], "Priya can't leave before 8:28 though."),
    ("1001", [], "What ride requests are open?"),
    ("1001", [], "I live at 1234 E Main St, save that as my area"),
    ("1003", [], "My classes are CSE 230 TTh 12:00-1:15 PM BYENG 209 and HST 109 online. Fall 2026."),
    ("1001", ["1002"], "Can we share a ride on Saturday?"),
    ("1001", [], "what's the capital of France?"),
]


async def main() -> None:
    load_dotenv()
    logging.disable(logging.NOTSET)
    svc = AgentService(demo_database(), clock=lambda: MONDAY_7AM)  # a class day for the demo students
    for user, mentioned, msg in TURNS:
        t = time.time()
        r = await svc.process_message({"message": msg, "discord_user_id": user, "discord_guild_id": DEMO_GUILD,
                                       "channel_id": "smoke", "mentioned_user_ids": mentioned})
        meta = {k: v for k, v in r.metadata.items() if k != "pending_schedule"}
        print(f"\n[{user}] {msg}\n  {meta} {time.time() - t:.1f}s\n{r.response_text}")
        if "pending_schedule" in r.metadata:
            print("  pending:", r.metadata["pending_schedule"]["validation_warnings"])
    if len(sys.argv) > 1:
        r = await svc.extract_schedule_from_image(open(sys.argv[1], "rb").read(), "image/png", "1004", DEMO_GUILD)
        print("\n[screenshot]\n" + svc.format_schedule(r.extracted_schedule), "\nwarnings:", r.validation_warnings)


if __name__ == "__main__":
    asyncio.run(main())
