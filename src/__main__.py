from .config import settings
from .utils.logger import log


def main() -> None:
    log("Transit Buddy project initialized successfully.")
    log("Initialization mode: Discord, MongoDB, and LangChain integrations are not yet active.")
    log(f"Environment: {settings.app_env}")


if __name__ == "__main__":
    main()
