from __future__ import annotations

import os
from uuid import uuid4
from typing import Any

from libs.integrations.storage import object_storage

from .indexes import ensure_mongo_indexes
from .repository import mongo_transactions_enabled, repo


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


async def run_transaction_probe(database: Any | None) -> dict[str, Any]:
    configured = mongo_transactions_enabled()
    payload: dict[str, Any] = {
        "mongoEnabled": database is not None,
        "transactionsConfigured": configured,
        "transactionProbe": "skipped",
    }
    if database is None:
        payload["reason"] = "mongo_not_configured"
        return payload
    if not configured:
        payload["reason"] = "transactions_disabled"
        return payload
    client = getattr(database, "client", None)
    if client is None:
        payload.update({"transactionProbe": "failed", "reason": "mongo_client_unavailable"})
        return payload

    probe_id = f"mongo-transaction-probe-{uuid4().hex}"
    try:
        collection = database["_deployment_probes"]
        async with await client.start_session() as session:
            async with session.start_transaction():
                await collection.insert_many([{"id": probe_id, "purpose": "deployment-transaction-probe"}], session=session)
                await collection.delete_many({"id": probe_id}, session=session)
    except Exception as exc:
        payload.update(
            {
                "transactionProbe": "failed",
                "reason": "transaction_probe_failed",
                "errorType": type(exc).__name__,
            }
        )
        return payload

    payload["transactionProbe"] = "pass"
    return payload
