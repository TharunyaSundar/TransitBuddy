import os

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    def load_dotenv():
        return False


load_dotenv()


def get_env(name: str, default: str = "") -> str:
    return os.getenv(name, default)


env = {
    "NODE_ENV": get_env("NODE_ENV", "development"),
    "DISCORD_TOKEN": get_env("DISCORD_TOKEN", ""),
    "DISCORD_CLIENT_ID": get_env("DISCORD_CLIENT_ID", ""),
    "DISCORD_GUILD_ID": get_env("DISCORD_GUILD_ID", ""),
    "MONGODB_URI": get_env("MONGODB_URI", ""),
    "MONGODB_DATABASE": get_env("MONGODB_DATABASE", "transit_buddy"),
    "LLM_PROVIDER": get_env("LLM_PROVIDER", ""),
    "LLM_MODEL": get_env("LLM_MODEL", ""),
    "OPENAI_API_KEY": get_env("OPENAI_API_KEY", ""),
    "GOOGLE_API_KEY": get_env("GOOGLE_API_KEY", ""),
    "DEFAULT_TIMEZONE": get_env("DEFAULT_TIMEZONE", "America/Phoenix"),
}
