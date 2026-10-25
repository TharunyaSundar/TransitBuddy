import asyncio

from .config import settings
from .discord_bot.client import start_discord_client
from .utils.logger import log


def main() -> None:
    log("Transit Buddy project initialized successfully.")
    log(f"Environment: {settings.app_env}")
    asyncio.run(start_discord_client())


if __name__ == "__main__":
    main()
