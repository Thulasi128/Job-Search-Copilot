"""Async MongoDB database connection and lifecycle management using Motor."""

import logging
from typing import Optional
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from backend.config import get_settings

logger = logging.getLogger(__name__)

_mongo_client: Optional[AsyncIOMotorClient] = None


def get_client() -> Optional[AsyncIOMotorClient]:
    """Return the global AsyncIOMotorClient instance."""
    return _mongo_client


def get_db() -> AsyncIOMotorDatabase:
    """Return the active MongoDB database instance.

    Raises:
        RuntimeError: If the database client has not been initialized.
    """
    if _mongo_client is None:
        raise RuntimeError("Database client is not initialized. Call connect_db() first.")
    settings = get_settings()
    return _mongo_client[settings.MONGO_DB_NAME]


async def connect_db() -> None:
    """Initialize the MongoDB client connection."""
    global _mongo_client
    settings = get_settings()
    if _mongo_client is None:
        logger.info("Connecting to MongoDB at %s", settings.MONGO_URI)
        _mongo_client = AsyncIOMotorClient(
            settings.MONGO_URI,
            serverSelectionTimeoutMS=2000,
        )


async def close_db() -> None:
    """Close the active MongoDB client connection."""
    global _mongo_client
    if _mongo_client is not None:
        logger.info("Closing MongoDB connection")
        _mongo_client.close()
        _mongo_client = None


async def ping_db() -> bool:
    """Check whether MongoDB is reachable by running a ping command.

    Returns:
        bool: True if database responds with ok, False otherwise.
    """
    if _mongo_client is None:
        return False
    try:
        settings = get_settings()
        db = _mongo_client[settings.MONGO_DB_NAME]
        res = await db.command("ping")
        return bool(res.get("ok") == 1.0)
    except Exception as exc:
        logger.warning("MongoDB ping failed: %s", exc)
        return False

