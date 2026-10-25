"""Calls into Developer 2's DatabaseService, whether its methods are sync or async."""
import inspect
from typing import Any


class DatabaseUnavailable(RuntimeError):
    pass


async def call(db: Any, method: str, *args, default=None):
    if db is None:
        raise DatabaseUnavailable("database not connected")
    fn = getattr(db, method, None)
    if fn is None:
        return default
    out = fn(*args)
    if inspect.isawaitable(out):
        out = await out
    return out


def has(db: Any, method: str) -> bool:
    return db is not None and callable(getattr(db, method, None))
