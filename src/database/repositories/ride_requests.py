import uuid

from pymongo import ReturnDocument

from ...shared.contracts import RideRequest
from ...shared.validators import is_valid_ride_request_status
from ..connection import get_database
from ..models import RIDE_REQUESTS
from .base import now_iso, require, strip_id


def _col():
    return get_database()[RIDE_REQUESTS]


async def create(request: RideRequest) -> RideRequest:
    require(discord_guild_id=request.discord_guild_id, discord_user_id=request.discord_user_id)
    data = request.model_dump()
    data["request_id"] = data["request_id"] or str(uuid.uuid4())
    data["created_at"] = now_iso()
    await _col().insert_one(data)
    return RideRequest.model_validate(strip_id(data))


async def find_open(discord_guild_id: str) -> list[RideRequest]:
    require(discord_guild_id=discord_guild_id)
    cursor = _col().find({"discord_guild_id": discord_guild_id, "status": "open"}).sort("created_at", 1)
    return [RideRequest.model_validate(strip_id(d)) async for d in cursor]


async def update_status(request_id: str, status: str) -> RideRequest | None:
    require(request_id=request_id, status=status)
    if not is_valid_ride_request_status(status):
        raise ValueError(f"Invalid ride request status: {status}")
    doc = await _col().find_one_and_update(
        {"request_id": request_id}, {"$set": {"status": status}}, return_document=ReturnDocument.AFTER
    )
    return RideRequest.model_validate(strip_id(doc)) if doc else None
