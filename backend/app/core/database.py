"""Application persistence dependency backed by the ClauseGuide MongoDB collection."""

from collections.abc import AsyncGenerator

from app.core.mongo import MongoStore, init_mongo


async def init_db() -> None:
    await init_mongo()


async def get_session() -> AsyncGenerator[MongoStore, None]:
    yield MongoStore()
