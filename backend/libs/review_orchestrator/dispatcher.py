from __future__ import annotations

import asyncio
import os
from typing import Any

from libs.db.repository import repo

from .execution import create_review_run_from_ai_run, execute_review_run_inline


def review_orchestration_mode() -> str:
    return os.getenv("AICHECK_REVIEW_ORCHESTRATION", "legacy").strip().lower() or "legacy"


def dispatch_review_run(ai_run_id: str) -> dict[str, Any]:
    mode = review_orchestration_mode()
    ai_run = repo.find_one("ai_runs", ai_run_id)
    if not ai_run:
        return {"mode": mode, "status": "missing", "aiRunId": ai_run_id}
    review_run = create_review_run_from_ai_run(ai_run, mode=mode)
    if mode == "inline":
        result = execute_review_run_inline(review_run["reviewRunId"])
        return {"mode": mode, "reviewRunId": review_run["reviewRunId"], "result": result}
    if mode == "temporal":
        return start_temporal_workflow(review_run)
    return {"mode": mode, "reviewRunId": review_run["reviewRunId"], "taskId": None}


def start_temporal_workflow(review_run: dict[str, Any]) -> dict[str, Any]:
    try:
        return asyncio.run(_start_temporal_workflow(review_run))
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(_start_temporal_workflow(review_run))
        finally:
            loop.close()
    except Exception as exc:
        review_run["dispatchErrorCode"] = "TEMPORAL_START_FAILED"
        review_run["dispatchErrorMessage"] = str(exc)
        return {
            "mode": "temporal",
            "status": "failed_to_start",
            "reviewRunId": review_run["reviewRunId"],
            "workflowId": review_run["workflowId"],
            "taskQueue": review_run["taskQueues"]["workflow"],
            "errorCode": "TEMPORAL_START_FAILED",
            "message": str(exc),
        }


async def _start_temporal_workflow(review_run: dict[str, Any]) -> dict[str, Any]:
    from temporalio.client import Client

    address = os.getenv("TEMPORAL_ADDRESS", "localhost:7233")
    namespace = os.getenv("TEMPORAL_NAMESPACE", "default")
    client = await Client.connect(address, namespace=namespace)
    handle = await client.start_workflow(
        "ReviewRunWorkflow",
        review_run["reviewRunId"],
        id=review_run["workflowId"],
        task_queue=review_run["taskQueues"]["workflow"],
    )
    review_run["temporalRunId"] = handle.result_run_id
    return {
        "mode": "temporal",
        "status": "started",
        "reviewRunId": review_run["reviewRunId"],
        "workflowId": handle.id,
        "temporalRunId": handle.result_run_id,
        "taskQueue": review_run["taskQueues"]["workflow"],
    }
