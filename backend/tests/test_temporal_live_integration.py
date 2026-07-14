from __future__ import annotations

import asyncio
import os
from uuid import uuid4

import pytest
from temporalio import activity
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from apps.review_worker.outbox import deliver_command
from apps.review_worker.workflows import ReviewRunWorkflow


pytestmark = pytest.mark.skipif(
    os.getenv("AICHECK_TEST_TEMPORAL_LIVE", "false").lower() != "true",
    reason="AICHECK_TEST_TEMPORAL_LIVE=true is required for the Temporal live test server",
)

graph_calls: list[dict] = []
applied_commands: list[dict] = []


@activity.defn(name="run_review_graph_activity")
async def transient_graph_activity(execution: dict) -> dict:
    graph_calls.append({"attempt": activity.info().attempt, "execution": dict(execution)})
    if activity.info().attempt == 1:
        raise ApplicationError("temporary dependency failure", type="TRANSIENT", non_retryable=False)
    return {
        "status": "waiting_human_review",
        "reviewRunId": execution["reviewRunId"],
    }


@activity.defn(name="apply_review_workflow_command_activity")
async def recording_command_activity(command: dict) -> dict:
    applied_commands.append(dict(command))
    return {
        "status": "applied",
        "reviewRunStatus": "accepted_by_human",
        "commandId": command["commandId"],
    }


async def wait_for_human_review(handle) -> dict:
    for _ in range(250):
        state = await handle.query(ReviewRunWorkflow.get_review_state)
        if state.get("status") == "waiting_human_review":
            return state
        await asyncio.sleep(0.1)
    raise AssertionError("Temporal workflow did not reach waiting_human_review")


@pytest.mark.asyncio
async def test_temporal_retries_and_recovers_signal_across_server_restart() -> None:
    graph_calls.clear()
    applied_commands.clear()
    database_path = os.path.abspath(
        os.path.join(os.getenv("TMPDIR", "/tmp"), f"aicheck-temporal-{uuid4().hex}.sqlite")
    )
    environment = await WorkflowEnvironment.start_local(
        ui=False,
        dev_server_database_filename=database_path,
    )
    task_queue = f"aicheck-live-{uuid4().hex}"
    tenant_id = "TENANT-TEMPORAL-LIVE"
    review_run_id = "RRUN-TEMPORAL-LIVE"
    workflow_id = f"review-run-live-{uuid4().hex}"
    activities = [transient_graph_activity, recording_command_activity]
    try:
        async with Worker(
            environment.client,
            task_queue=task_queue,
            workflows=[ReviewRunWorkflow],
            activities=activities,
        ):
            handle = await environment.client.start_workflow(
                ReviewRunWorkflow.run,
                {"tenantId": tenant_id, "reviewRunId": review_run_id},
                id=workflow_id,
                task_queue=task_queue,
            )
            state = await wait_for_human_review(handle)
            assert state["tenantId"] == tenant_id
            assert [call["attempt"] for call in graph_calls] == [1, 2]

        command = {
            "commandId": "WFCMD-TEMPORAL-LIVE",
            "commandType": "submit_human_decision",
            "tenantId": tenant_id,
            "reviewRunId": review_run_id,
            "workflowId": workflow_id,
            "payloadHash": "sha256:temporal-live",
            "signalPayload": {
                "decision": "accept",
                "comment": "SENSITIVE-COMMENT-MUST-NOT-ENTER-TEMPORAL-HISTORY",
            },
        }
        # Temporal persists the signal even though no worker is polling this queue.
        await deliver_command(environment.client, command)
        history_before_restart = await handle.fetch_history()
        assert "SENSITIVE-COMMENT-MUST-NOT-ENTER-TEMPORAL-HISTORY" not in history_before_restart.to_json()
    finally:
        await environment.shutdown()

    restarted_environment = await WorkflowEnvironment.start_local(
        ui=False,
        dev_server_database_filename=database_path,
    )
    try:
        restarted_handle = restarted_environment.client.get_workflow_handle(workflow_id)
        async with Worker(
            restarted_environment.client,
            task_queue=task_queue,
            workflows=[ReviewRunWorkflow],
            activities=activities,
        ):
            result = await restarted_handle.result()

        assert result["status"] == "accepted_by_human"
        assert applied_commands == [
            {
                "commandId": "WFCMD-TEMPORAL-LIVE",
                "commandType": "submit_human_decision",
                "tenantId": tenant_id,
                "reviewRunId": review_run_id,
                "payloadHash": "sha256:temporal-live",
            }
        ]
        assert "SENSITIVE-COMMENT" not in repr(applied_commands)
        history_after_restart = await restarted_handle.fetch_history()
        assert "SENSITIVE-COMMENT-MUST-NOT-ENTER-TEMPORAL-HISTORY" not in history_after_restart.to_json()
    finally:
        await restarted_environment.shutdown()
        for suffix in ("", "-shm", "-wal"):
            try:
                os.remove(database_path + suffix)
            except FileNotFoundError:
                pass
