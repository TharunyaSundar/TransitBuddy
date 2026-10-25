from typing import Generic, TypeVar

from pydantic import BaseModel

from .base import now_iso, require, strip_id

M = TypeVar("M", bound=BaseModel)


class GuildScopedRepository(Generic[M]):
    """Repository for documents keyed by (discord_guild_id, discord_user_id).

    Every query filters by guild so results never cross guild boundaries.
    """

    def __init__(self, collection_getter, model: type[M], created_at: bool = False):
        self._collection = collection_getter
        self._model = model
        self._created_at = created_at

    async def upsert(self, item: M) -> M:
        require(discord_guild_id=item.discord_guild_id, discord_user_id=item.discord_user_id)
        data = item.model_dump()
        now = now_iso()
        data["updated_at"] = now

        on_insert = {}
        if self._created_at:
            data.pop("created_at", None)
            on_insert["created_at"] = now

        key = {
            "discord_guild_id": data.pop("discord_guild_id"),
            "discord_user_id": data.pop("discord_user_id"),
        }
        update = {"$set": data}
        if on_insert:
            update["$setOnInsert"] = on_insert

        from pymongo import ReturnDocument

        doc = await self._collection().find_one_and_update(
            key, update, upsert=True, return_document=ReturnDocument.AFTER
        )
        return self._model.model_validate(strip_id(doc))

    async def find(self, discord_guild_id: str, discord_user_id: str) -> M | None:
        require(discord_guild_id=discord_guild_id, discord_user_id=discord_user_id)
        doc = await self._collection().find_one(
            {"discord_guild_id": discord_guild_id, "discord_user_id": discord_user_id}
        )
        return self._model.model_validate(strip_id(doc)) if doc else None

    async def find_many(self, discord_guild_id: str, discord_user_ids: list[str]) -> list[M]:
        require(discord_guild_id=discord_guild_id)
        if not discord_user_ids:
            return []
        cursor = self._collection().find(
            {"discord_guild_id": discord_guild_id, "discord_user_id": {"$in": list(discord_user_ids)}}
        )
        return [self._model.model_validate(strip_id(d)) async for d in cursor]

    async def delete(self, discord_guild_id: str, discord_user_id: str) -> bool:
        require(discord_guild_id=discord_guild_id, discord_user_id=discord_user_id)
        result = await self._collection().delete_one(
            {"discord_guild_id": discord_guild_id, "discord_user_id": discord_user_id}
        )
        return result.deleted_count > 0
