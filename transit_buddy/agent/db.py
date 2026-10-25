"""Calls into Developer 2's DatabaseService (transit_buddy.shared.contracts).

The service takes and returns the shared Pydantic models. The agent works with plain dicts, so writes are
validated into the matching model here and results are dumped back to dicts. Sync methods work too.
"""
import inspect
from typing import Any

from pydantic import BaseModel

from ..shared.contracts import CommutePreferences, RideRequest, Student, StudentSchedule

WRITE_MODELS = {
    "upsert_student": Student,
    "save_schedule": StudentSchedule,
    "save_commute_preferences": CommutePreferences,
    "create_ride_request": RideRequest,
}


class DatabaseUnavailable(RuntimeError):
    pass


def plain(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump()
    if isinstance(value, list):
        return [plain(v) for v in value]
    return value


async def call(db: Any, method: str, *args, default=None):
    if db is None:
        raise DatabaseUnavailable("database not connected")
    fn = getattr(db, method, None)
    if fn is None:
        return default
    model = WRITE_MODELS.get(method)
    if model and args and isinstance(args[0], dict):
        args = (model.model_validate(args[0]), *args[1:])  # raises pydantic.ValidationError on bad data
    out = fn(*args)
    if inspect.isawaitable(out):
        out = await out
    return plain(out)


def has(db: Any, method: str) -> bool:
    return db is not None and callable(getattr(db, method, None))
