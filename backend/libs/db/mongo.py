from __future__ import annotations

import os
from typing import Any

from libs.integrations.storage import object_storage

from .indexes import ensure_mongo_indexes
from .repository import repo


async def init_mongo_if_configured(app: Any) -> None:
    mongo_url = os.getenv("AICHECK_MONGO_URL")
    if not mongo_url:
        app.state.mongo = None
        return
    try:
        from motor.motor_asyncio import AsyncIOMotorClient
    except Exception:
        app.state.mongo = None
        return
    client = AsyncIOMotorClient(mongo_url)
    db_name = os.getenv("AICHECK_MONGO_DB", "aicheck")
    database = client[db_name]
    await ensure_mongo_indexes(database)
    await repo.load_from_mongo(database)
    object_storage.ensure_buckets()
    app.state.mongo_client = client
    app.state.mongo = database


async def close_mongo(app: Any) -> None:
    client = getattr(app.state, "mongo_client", None)
    if client is not None:
        client.close()
