"""Environment configuration loader."""
import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    app_env: str = "development"
    discord_token: str = ""
    discord_client_id: str = ""
    discord_guild_id: str = ""
    mongodb_uri: str = ""
    mongodb_database: str = "transit_buddy"
    llm_provider: str = ""
    llm_model: str = ""
    openai_api_key: str = ""
    google_api_key: str = ""
    default_timezone: str = "America/Phoenix"


def load_settings() -> Settings:
    return Settings(
        app_env=os.getenv("APP_ENV") or "development",
        discord_token=os.getenv("DISCORD_TOKEN", ""),
        discord_client_id=os.getenv("DISCORD_CLIENT_ID", ""),
        discord_guild_id=os.getenv("DISCORD_GUILD_ID", ""),
        mongodb_uri=os.getenv("MONGODB_URI", ""),
        mongodb_database=os.getenv("MONGODB_DATABASE") or "transit_buddy",
        llm_provider=os.getenv("LLM_PROVIDER", ""),
        llm_model=os.getenv("LLM_MODEL", ""),
        openai_api_key=os.getenv("OPENAI_API_KEY", ""),
        google_api_key=os.getenv("GOOGLE_API_KEY", ""),
        default_timezone=os.getenv("DEFAULT_TIMEZONE") or "America/Phoenix",
    )


settings = load_settings()


def is_configured(name: str) -> bool:
    """Return True if the named setting is a non-blank value."""
    return bool(str(getattr(settings, name, "")).strip())
