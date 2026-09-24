"""MongoDB persistence for the single ClauseGuide collection.

Every record has a ``kind`` discriminator and a stable string ``_id``.  The
collection is deliberately separate from the other applications in the csi
database.  File bytes are stored as bounded ``file_chunk`` records in it.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from collections.abc import AsyncGenerator
from enum import Enum
from typing import Any

from bson import Binary
from pymongo import ASCENDING, AsyncMongoClient, ReturnDocument
from sqlalchemy import inspect
from sqlalchemy.sql.sqltypes import Enum as SqlEnum

from app.core.settings import get_settings

settings = get_settings()
_client: AsyncMongoClient | None = None


def _collection():
    global _client
    if not settings.mongodb_uri:
        raise RuntimeError("MONGODB_URI is required for MongoDB persistence")
    if settings.mongodb_database != "csi" or settings.mongodb_collection != "clauseguide_ai":
        raise RuntimeError("ClauseGuide must use csi.clauseguide_ai")
    if _client is None:
        _client = AsyncMongoClient(
            settings.mongodb_uri,
            serverSelectionTimeoutMS=10000,
            tz_aware=True,
            maxPoolSize=20,
        )
    return _client[settings.mongodb_database][settings.mongodb_collection]


async def init_mongo() -> None:
    collection = _collection()
    await collection.database.client.admin.command("ping")
    await collection.create_index(
        [("kind", ASCENDING), ("email", ASCENDING)],
        unique=True,
        partialFilterExpression={"kind": "users", "email": {"$exists": True}},
    )
    await collection.create_index(
        [("kind", ASCENDING), ("google_sub", ASCENDING)],
        unique=True,
        partialFilterExpression={"kind": "users", "google_sub": {"$type": "string"}},
    )
    await collection.create_index([("kind", ASCENDING), ("document_id", ASCENDING)])
    await collection.create_index([("kind", ASCENDING), ("owner_user_id", ASCENDING)])
    await collection.create_index([("kind", ASCENDING), ("workspace_id", ASCENDING)])
    await collection.create_index([("kind", ASCENDING), ("file_id", ASCENDING), ("index", ASCENDING)])
    await collection.create_index("expires_at", expireAfterSeconds=0)


async def mongo_ping() -> None:
    await _collection().database.client.admin.command("ping")


def _serialize(model: Any) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for column in inspect(type(model)).columns:
        value = getattr(model, column.key)
        values[column.key] = value.value if isinstance(value, Enum) else value
    return values


def _materialize(model_type: type, record: dict[str, Any]) -> Any:
    values = {}
    for column in inspect(model_type).columns:
        value = record.get(column.key)
        if value is not None and isinstance(column.type, SqlEnum):
            value = column.type.enum_class(value)
        values[column.key] = value
    return model_type(**values)


def _fingerprint(values: dict[str, Any]) -> str:
    return json.dumps(values, default=str, sort_keys=True)


class MongoStore:
    """Small unit-of-work adapter used by the existing domain model classes."""

    def __init__(self) -> None:
        self.collection = _collection()
        self._loaded: dict[tuple[str, str | int], tuple[Any, int, str]] = {}
        self._pending: list[Any] = []
        self._deleted: list[Any] = []

    async def get(self, model_type: type, record_id: str | int) -> Any | None:
        key = (model_type.__tablename__, record_id)
        if key in self._loaded:
            return self._loaded[key][0]
        record = await self.collection.find_one({"_id": f"{key[0]}:{record_id}"})
        return self._track(model_type, record) if record else None

    async def find(
        self,
        model_type: type,
        filters: dict[str, Any] | None = None,
        *,
        sort: list[tuple[str, int]] | None = None,
        limit: int | None = None,
    ) -> list[Any]:
        query = {"kind": model_type.__tablename__, **(filters or {})}
        cursor = self.collection.find(query)
        if sort:
            cursor = cursor.sort(sort)
        if limit is not None:
            cursor = cursor.limit(limit)
        return [self._track(model_type, record) for record in await cursor.to_list(None)]

    async def one(self, model_type: type, filters: dict[str, Any]) -> Any | None:
        items = await self.find(model_type, filters, limit=1)
        return items[0] if items else None

    async def count(self, model_type: type, filters: dict[str, Any] | None = None) -> int:
        return await self.collection.count_documents(
            {"kind": model_type.__tablename__, **(filters or {})}
        )

    def add(self, model: Any) -> None:
        if model not in self._pending:
            self._pending.append(model)

    async def delete(self, model: Any) -> None:
        self._deleted.append(model)

    async def delete_many(self, model_type: type, filters: dict[str, Any]) -> None:
        await self.collection.delete_many({"kind": model_type.__tablename__, **filters})
        self._loaded = {
            key: value for key, value in self._loaded.items() if key[0] != model_type.__tablename__
        }

    async def flush(self) -> None:
        for model in self._pending:
            for column in inspect(type(model)).columns:
                if getattr(model, column.key) is not None:
                    continue
                if column.primary_key and column.key == "id" and column.type.python_type is int:
                    counter = await self.collection.find_one_and_update(
                        {"_id": f"_counter:{type(model).__tablename__}"},
                        {"$inc": {"value": 1}},
                        upsert=True,
                        return_document=ReturnDocument.AFTER,
                    )
                    setattr(model, column.key, counter["value"])
                elif column.default is not None:
                    default = column.default.arg
                    if callable(default):
                        try:
                            value = default()
                        except TypeError:
                            value = default(None)
                    else:
                        value = default
                    setattr(model, column.key, value)

    async def commit(self) -> None:
        await self.flush()
        client = self.collection.database.client
        refreshed: dict[tuple[str, str | int], tuple[Any, int, str]] = {}
        async with client.start_session() as transaction:
            async with await transaction.start_transaction():
                for model in self._pending:
                    kind = type(model).__tablename__
                    values = _serialize(model)
                    await self.collection.insert_one(
                        {"_id": f"{kind}:{model.id}", "kind": kind, "version": 1, **values},
                        session=transaction,
                    )
                    refreshed[(kind, model.id)] = (model, 1, _fingerprint(values))
                for key, (model, version, old_fingerprint) in self._loaded.items():
                    if model in self._deleted or model in self._pending:
                        continue
                    values = _serialize(model)
                    if _fingerprint(values) == old_fingerprint:
                        refreshed[key] = (model, version, old_fingerprint)
                        continue
                    result = await self.collection.replace_one(
                        {"_id": f"{key[0]}:{key[1]}", "version": version},
                        {"_id": f"{key[0]}:{key[1]}", "kind": key[0], "version": version + 1, **values},
                        session=transaction,
                    )
                    if result.matched_count != 1:
                        raise RuntimeError("Concurrent update conflict")
                    refreshed[key] = (model, version + 1, _fingerprint(values))
                for model in self._deleted:
                    await self.collection.delete_one(
                        {"_id": f"{type(model).__tablename__}:{model.id}"},
                        session=transaction,
                    )
        self._pending.clear()
        self._deleted.clear()
        self._loaded = refreshed

    async def refresh(self, model: Any) -> None:
        # IDs and Python-side defaults are assigned during flush.
        return None

    def _track(self, model_type: type, record: dict[str, Any]) -> Any:
        key = (model_type.__tablename__, record["id"])
        if key in self._loaded:
            return self._loaded[key][0]
        model = _materialize(model_type, record)
        self._loaded[key] = (model, record.get("version", 1), _fingerprint(_serialize(model)))
        return model


async def get_mongo_store() -> AsyncGenerator[MongoStore, None]:
    yield MongoStore()


async def put_file_chunk(
    file_id: str, index: int, data: bytes, *, expires_at: datetime | None = None
) -> None:
    if not data or len(data) > 2 * 1024 * 1024:
        raise ValueError("File chunks must contain 1 byte to 2 MB")
    await _collection().replace_one(
        {"_id": f"file_chunk:{file_id}:{index:06d}"},
        {
            "_id": f"file_chunk:{file_id}:{index:06d}",
            "kind": "file_chunk",
            "file_id": file_id,
            "index": index,
            "data": Binary(data),
            **({"expires_at": expires_at} if expires_at else {}),
        },
        upsert=True,
    )


async def file_chunks(file_id: str) -> AsyncGenerator[bytes, None]:
    cursor = _collection().find({"kind": "file_chunk", "file_id": file_id}).sort("index", ASCENDING)
    async for record in cursor:
        yield bytes(record["data"])


async def read_file_bytes(file_id: str) -> bytes:
    return b"".join([chunk async for chunk in file_chunks(file_id)])


async def has_file_chunk(file_id: str, index: int) -> bool:
    record = await _collection().find_one(
        {"_id": f"file_chunk:{file_id}:{index:06d}"}, {"_id": 1}
    )
    return record is not None


async def create_upload(owner_user_id: str, file_name: str, size: int) -> str:
    file_id = uuid.uuid4().hex
    await _collection().insert_one({
        "_id": f"file_upload:{file_id}",
        "kind": "file_upload",
        "file_id": file_id,
        "owner_user_id": owner_user_id,
        "file_name": file_name,
        "size": size,
        "complete": False,
        "expires_at": datetime.now(UTC) + timedelta(hours=24),
    })
    return file_id


async def get_upload(file_id: str, owner_user_id: str) -> dict[str, Any] | None:
    return await _collection().find_one({
        "_id": f"file_upload:{file_id}",
        "owner_user_id": owner_user_id,
    })


async def finish_upload(file_id: str, owner_user_id: str) -> None:
    await _collection().update_many(
        {"kind": "file_chunk", "file_id": file_id},
        {"$unset": {"expires_at": ""}},
    )
    await _collection().update_one(
        {"_id": f"file_upload:{file_id}", "owner_user_id": owner_user_id},
        {"$set": {"complete": True}, "$unset": {"expires_at": ""}},
    )


async def delete_file_chunks(file_id: str) -> None:
    await _collection().delete_many({"kind": "file_chunk", "file_id": file_id})
