from src.config import is_configured, settings


def test_defaults():
    assert settings.default_timezone
    assert isinstance(is_configured("discord_token"), bool)
