import asyncio
import logging
import os

from .config import settings
from .discord_bot.client import start_discord_client
from .utils.logger import log


def main() -> None:
    # show the agent's timing and warning logs (stdout, so journalctl / the terminal shows them)
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    log("Transit Buddy project initialized successfully.")
    log(f"Environment: {settings.app_env}")
    asyncio.run(start_discord_client())


if __name__ == "__main__":
    main()
