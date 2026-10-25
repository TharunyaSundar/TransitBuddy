"""MongoDB connection management (PyMongo async client)."""
from pymongo import AsyncMongoClient
from pymongo.asynchronous.database import AsyncDatabase

from ..config import settings

_client: AsyncMongoClient | None = None
_database: AsyncDatabase | None = None


async def connect_database(uri: str | None = None, db_name: str | None = None) -> AsyncDatabase:
    """Connect to MongoDB and create indexes. Safe to call repeatedly."""
    global _client, _database

    if _database is not None:
        return _database

    uri = uri or settings.mongodb_uri
    if not uri:
        raise RuntimeError("MONGODB_URI is not configured.")

    from .models import ensure_indexes

    _client = AsyncMongoClient(uri, serverSelectionTimeoutMS=5000)
    _database = _client[db_name or settings.mongodb_database]
    await _client.admin.command("ping")
    await ensure_indexes(_database)
    return _database


def get_database() -> AsyncDatabase:
    if _database is None:
        raise RuntimeError("Database not connected. Call connect_database() first.")
    return _database


async def disconnect_database() -> None:
    global _client, _database
    if _client is not None:
        await _client.close()
    _client = None
    _database = None
