from __future__ import annotations

import asyncio
import os
from typing import Any

from libs.db.repository import flush_state_records, repo

from .execution import (
    append_review_event,
    create_review_run_from_ai_run,
    execute_review_run_inline,
    review_run_state_records,
)


def review_orchestration_mode() -> str:
    return os.getenv("AICHECK_REVIEW_ORCHESTRATION", "legacy").strip().lower() or "legacy"


def dispatch_existing_review_run(review_run: dict[str, Any]) -> dict[str, Any]:
    mode = review_orchestration_mode()
    review_run["workflowEngine"] = "temporal" if mode == "temporal" else "inline_temporal_compatible"
    review_run["updatedAt"] = review_run.get("updatedAt") or review_run.get("createdAt")
    if mode == "inline":
        result = execute_review_run_inline(review_run["reviewRunId"])
        return {"mode": mode, "status": "completed", "reviewRunId": review_run["reviewRunId"], "result": result}
    if mode == "temporal":
        return start_temporal_workflow(review_run)
    review_run["status"] = "failed_to_start"
    review_run["dispatchErrorCode"] = "REVIEW_ORCHESTRATION_DISABLED"
    append_review_event(
        str(review_run["reviewRunId"]),
        event_type="review_run.dispatch_failed",
        title="ReviewRun 未启动",
        status="failed_to_start",
        details={"mode": mode, "errorCode": "REVIEW_ORCHESTRATION_DISABLED"},
    )
    flush_state_records(review_run_state_records(str(review_run["reviewRunId"])))
    return {
        "mode": mode,
        "status": "failed_to_start",
        "reviewRunId": review_run["reviewRunId"],
        "errorCode": "REVIEW_ORCHESTRATION_DISABLED",
    }


def dispatch_review_run(ai_run_id: str) -> dict[str, Any]:
    mode = review_orchestration_mode()
    ai_run = repo.find_one("ai_runs", ai_run_id)
    if not ai_run:
        return {"mode": mode, "status": "missing", "aiRunId": ai_run_id}
    review_run = create_review_run_from_ai_run(ai_run, mode=mode)
    return dispatch_existing_review_run(review_run)


def start_temporal_workflow(review_run: dict[str, Any]) -> dict[str, Any]:
    try:
        return asyncio.run(_start_temporal_workflow(review_run))
    except Exception as exc:
        review_run["status"] = "failed_to_start"
        review_run["dispatchErrorCode"] = "TEMPORAL_START_FAILED"
        review_run["dispatchErrorMessage"] = str(exc)
        append_review_event(
            str(review_run["reviewRunId"]),
            event_type="review_run.dispatch_failed",
            title="Temporal workflow 启动失败",
            status="failed_to_start",
            details={"errorCode": "TEMPORAL_START_FAILED", "message": str(exc)},
        )
        flush_state_records(review_run_state_records(str(review_run["reviewRunId"])))
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
    review_run["updatedAt"] = review_run.get("updatedAt") or review_run.get("createdAt")
    flush_state_records(review_run_state_records(str(review_run["reviewRunId"])))
    return {
        "mode": "temporal",
        "status": "started",
        "reviewRunId": review_run["reviewRunId"],
        "workflowId": handle.id,
        "temporalRunId": handle.result_run_id,
        "taskQueue": review_run["taskQueues"]["workflow"],
    }


def signal_review_run_human_decision(review_run: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
    if review_run.get("workflowEngine") != "temporal":
        return {"status": "skipped", "reason": "workflowEngine is not temporal"}
    return _run_temporal_signal(review_run, "submit_human_decision", decision)


def signal_review_run_cancel(review_run: dict[str, Any], reason: str | None = None) -> dict[str, Any]:
    if review_run.get("workflowEngine") != "temporal":
        return {"status": "skipped", "reason": "workflowEngine is not temporal"}
    return _run_temporal_signal(review_run, "cancel_review", reason)


def _run_temporal_signal(review_run: dict[str, Any], signal_name: str, payload: Any) -> dict[str, Any]:
    try:
        result = asyncio.run(_signal_temporal_workflow(review_run, signal_name, payload))
    except Exception as exc:
        review_run["temporalSignalErrorCode"] = "TEMPORAL_SIGNAL_FAILED"
        review_run["temporalSignalErrorMessage"] = str(exc)
        append_review_event(
            str(review_run.get("reviewRunId") or review_run.get("id")),
            event_type="temporal.signal_failed",
            title="Temporal signal 发送失败",
            status="warning",
            details={"signalName": signal_name, "message": str(exc)},
        )
        return {"status": "failed", "errorCode": "TEMPORAL_SIGNAL_FAILED", "message": str(exc)}
    append_review_event(
        str(review_run.get("reviewRunId") or review_run.get("id")),
        event_type="temporal.signal_sent",
        title="Temporal signal 已发送",
        status="succeeded",
        details={"signalName": signal_name},
    )
    return result


async def _signal_temporal_workflow(review_run: dict[str, Any], signal_name: str, payload: Any) -> dict[str, Any]:
    from temporalio.client import Client

    workflow_id = str(review_run.get("workflowId") or f"review-run-{review_run.get('reviewRunId')}")
    address = os.getenv("TEMPORAL_ADDRESS", "localhost:7233")
    namespace = os.getenv("TEMPORAL_NAMESPACE", "default")
    client = await Client.connect(address, namespace=namespace)
    handle = client.get_workflow_handle(workflow_id)
    await handle.signal(signal_name, payload)
    return {"status": "sent", "workflowId": workflow_id, "signalName": signal_name}
