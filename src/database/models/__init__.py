"""Collection names and index definitions.

Documents are stored in the shape of ``src.shared.contracts``
(snake_case fields). Every collection is scoped by ``discord_guild_id``.
"""
from pymongo import ASCENDING, IndexModel

STUDENTS = "students"
SCHEDULES = "schedules"

_IDENTITY = [("discord_guild_id", ASCENDING), ("discord_user_id", ASCENDING)]

INDEXES: dict[str, list[IndexModel]] = {
    STUDENTS: [
        IndexModel(_IDENTITY, unique=True, name="guild_user_unique"),
        IndexModel([("discord_guild_id", ASCENDING), ("commute_match_opt_in", ASCENDING)], name="guild_optin"),
    ],
    SCHEDULES: [IndexModel(_IDENTITY, unique=True, name="guild_user_unique")],
}


async def ensure_indexes(database) -> None:
    for name, indexes in INDEXES.items():
        await database[name].create_indexes(indexes)
