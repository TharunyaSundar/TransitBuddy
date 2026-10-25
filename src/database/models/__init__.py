"""Collection names and index definitions.

Documents are stored in the shape of ``src.shared.contracts``
(snake_case fields). Every collection is scoped by ``discord_guild_id``.
"""
from pymongo import ASCENDING, IndexModel

STUDENTS = "students"
SCHEDULES = "schedules"
COMMUTE_PREFERENCES = "commute_preferences"
RIDE_REQUESTS = "ride_requests"

_IDENTITY = [("discord_guild_id", ASCENDING), ("discord_user_id", ASCENDING)]

INDEXES: dict[str, list[IndexModel]] = {
    STUDENTS: [IndexModel(_IDENTITY, unique=True, name="guild_user_unique")],
    SCHEDULES: [IndexModel(_IDENTITY, unique=True, name="guild_user_unique")],
    COMMUTE_PREFERENCES: [
        IndexModel(_IDENTITY, unique=True, name="guild_user_unique"),
        IndexModel(
            [("discord_guild_id", ASCENDING), ("ride_sharing_opt_in", ASCENDING)],
            name="guild_optin",
        ),
    ],
    RIDE_REQUESTS: [
        IndexModel([("request_id", ASCENDING)], unique=True, name="request_id_unique"),
        IndexModel(
            [("discord_guild_id", ASCENDING), ("status", ASCENDING)], name="guild_status"
        ),
    ],
}


async def ensure_indexes(database) -> None:
    for name, indexes in INDEXES.items():
        await database[name].create_indexes(indexes)
