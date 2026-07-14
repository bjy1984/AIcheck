from __future__ import annotations

import hashlib
import json

from temporalio import activity
from temporalio.exceptions import ApplicationError

from libs.contracts.responses import server_time
from libs.db.repository import flush_state_records, load_review_run_state, repo
from libs.review_orchestrator.execution import (
    append_review_event,
    bump_review_run_revision,
    execute_review_run_inline,
    human_decision_for_review_run,
    mark_review_run_retry_exhausted,
    review_run_state_records,
)
from libs.security.tenant import current_tenant_id, reset_request_tenant_id, set_request_tenant_id


@activity.defn(name="run_review_graph_activity")
async def run_review_graph_activity(execution: dict | str) -> dict:
    if isinstance(execution, dict):
        tenant_id = str(execution.get("tenantId") or "")
        review_run_id = str(execution.get("reviewRunId") or "")
    else:
        tenant_id = current_tenant_id()
        review_run_id = str(execution or "")
    if not tenant_id or not review_run_id:
        raise ApplicationError(
            "ReviewRun activity input is missing tenantId or reviewRunId.",
            type="REVIEW_WORKFLOW_INPUT_INVALID",
            non_retryable=True,
        )
    tenant_token = set_request_tenant_id(tenant_id)
    try:
        activity.heartbeat({"tenantId": tenant_id, "reviewRunId": review_run_id, "stage": "loading_state"})
        load_review_run_state(review_run_id)
        activity.heartbeat({"tenantId": tenant_id, "reviewRunId": review_run_id, "stage": "executing_graph"})
        result = execute_review_run_inline(review_run_id)
        flush_state_records(review_run_state_records(review_run_id))
        if result.get("status") == "retry_pending":
            attempt = int(activity.info().attempt)
            if attempt >= 3:
                mark_review_run_retry_exhausted(review_run_id)
                flush_state_records(review_run_state_records(review_run_id))
                raise ApplicationError(
                    "ReviewRun transient failure exhausted retries.",
                    type="REVIEW_RETRY_EXHAUSTED",
                    non_retryable=True,
                    details=[result],
                )
            raise ApplicationError(
                "ReviewRun transient failure; retrying activity.",
                type=str(result.get("errorCode") or "REVIEW_TRANSIENT_FAILURE"),
                non_retryable=False,
                details=[result],
            )
        if result.get("status") in {"failed", "failed_to_start", "missing"}:
            raise ApplicationError(
                "ReviewRun graph execution did not reach human review.",
                type=str(result.get("errorCode") or "REVIEW_GRAPH_EXECUTION_FAILED"),
                non_retryable=True,
                details=[result],
            )
        return result
    finally:
        reset_request_tenant_id(tenant_token)


@activity.defn(name="apply_review_workflow_command_activity")
async def apply_review_workflow_command_activity(command: dict) -> dict:
    command_id = str(command.get("commandId") or "")
    review_run_id = str(command.get("reviewRunId") or "")
    tenant_id = str(command.get("tenantId") or "")
    if not command_id or not review_run_id or not tenant_id:
        raise ApplicationError(
            "Workflow command is missing commandId, reviewRunId, or tenantId.",
            type="REVIEW_WORKFLOW_COMMAND_INVALID",
            non_retryable=True,
        )
    tenant_token = set_request_tenant_id(tenant_id)
    try:
        activity.heartbeat({"reviewRunId": review_run_id, "commandId": command_id, "stage": "loading_state"})
        load_review_run_state(review_run_id)
        existing_inbox = repo.find_one("workflow_inbox", command_id, id_field="commandId") or repo.find_one(
            "workflow_inbox", command_id
        )
        if existing_inbox:
            return {"status": "already_applied", "commandId": command_id, "reviewRunId": review_run_id}
        review_run = repo.find_one("review_runs", review_run_id, id_field="reviewRunId") or repo.find_one(
            "review_runs", review_run_id
        )
        if not review_run:
            raise ApplicationError(
                f"ReviewRun {review_run_id} does not exist.",
                type="REVIEW_RUN_NOT_FOUND",
                non_retryable=True,
            )

        outbox = repo.find_one("workflow_outbox", command_id, id_field="commandId") or repo.find_one(
            "workflow_outbox", command_id
        )
        if not outbox:
            raise ApplicationError(
                f"Workflow command {command_id} does not have a durable outbox record.",
                type="REVIEW_WORKFLOW_COMMAND_INVALID",
                non_retryable=True,
            )
        if (
            str(outbox.get("tenantId") or "") != tenant_id
            or str(outbox.get("reviewRunId") or "") != review_run_id
            or str(outbox.get("commandType") or "") != str(command.get("commandType") or "")
        ):
            raise ApplicationError(
                "Workflow command envelope does not match its durable outbox record.",
                type="REVIEW_WORKFLOW_COMMAND_SCOPE_MISMATCH",
                non_retryable=True,
            )
        persisted_payload = outbox.get("signalPayload")
        if not isinstance(persisted_payload, dict):
            raise ApplicationError(
                "Workflow command outbox payload is missing.",
                type="REVIEW_WORKFLOW_COMMAND_INVALID",
                non_retryable=True,
            )
        computed_payload_hash = hashlib.sha256(
            json.dumps(
                persisted_payload,
                ensure_ascii=False,
                sort_keys=True,
                default=str,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        expected_payload_hash = str(outbox.get("payloadHash") or "")
        envelope_payload_hash = str(command.get("payloadHash") or "")
        legacy_payload_matches = not envelope_payload_hash and all(
            command.get(key) == value for key, value in persisted_payload.items()
        )
        if (
            not expected_payload_hash
            or computed_payload_hash != expected_payload_hash
            or (envelope_payload_hash != expected_payload_hash and not legacy_payload_matches)
        ):
            raise ApplicationError(
                "Workflow command payload integrity check failed.",
                type="REVIEW_WORKFLOW_COMMAND_INVALID",
                non_retryable=True,
            )
        command = {
            **persisted_payload,
            "commandId": command_id,
            "commandType": outbox.get("commandType"),
            "tenantId": tenant_id,
            "reviewRunId": review_run_id,
            "payloadHash": expected_payload_hash,
        }

        command_type = str(command.get("commandType") or "")
        if command_type == "submit_human_decision":
            decision = str(command.get("decision") or "")
            decision_payload = command.get("decisionPayload")
            result = human_decision_for_review_run(
                review_run_id,
                decision,
                decision_payload if isinstance(decision_payload, dict) else {},
            )
            if result.get("status") in {
                "missing",
                "invalid_state",
                "invalid_decision",
                "invalid_corrected_output",
                "invalid_input",
            }:
                raise ApplicationError(
                    f"ReviewRun command could not be applied: {result.get('status')}",
                    type="REVIEW_WORKFLOW_COMMAND_REJECTED",
                    non_retryable=True,
                    details=[result],
                )
        elif command_type == "cancel_review":
            if review_run.get("status") not in {"queued", "running", "waiting_human_review"}:
                raise ApplicationError(
                    f"ReviewRun is already terminal: {review_run.get('status')}",
                    type="REVIEW_WORKFLOW_COMMAND_REJECTED",
                    non_retryable=True,
                )
            reason = str(command.get("reason") or "")
            review_run["status"] = "cancelled"
            review_run["cancelReason"] = reason
            if not review_run.get("advisoryOnly"):
                previous_status = str(review_run.get("previousNodeStatus") or "待人工确认")
                repo.set_node_status(
                    str(review_run.get("projectId")),
                    int(review_run.get("nodeId") or 0),
                    previous_status,
                )
                review_run["stateTransition"] = {
                    "from": "业务核验中",
                    "to": previous_status,
                    "reason": "formal_review_cancelled_restored_previous_status",
                }
            ai_run = repo.find_one("ai_runs", str(review_run.get("aiRunId") or ""))
            if ai_run:
                ai_run["status"] = "已取消"
                ai_run["stateTransition"] = repo.clone(review_run.get("stateTransition") or {})
            bump_review_run_revision(review_run)
            append_review_event(
                review_run_id,
                event_type="review_run.cancelled",
                title="ReviewRun 已取消",
                status="cancelled",
                details={"commandId": command_id, "reasonHash": command.get("reasonHash")},
            )
            result = {"status": "cancelled", "reviewRun": review_run}
        else:
            raise ApplicationError(
                f"Unsupported workflow command type: {command_type}",
                type="REVIEW_WORKFLOW_COMMAND_INVALID",
                non_retryable=True,
            )

        review_run.pop("pendingWorkflowCommand", None)
        if outbox:
            outbox["status"] = "applied"
            outbox["appliedAt"] = server_time()
            outbox["updatedAt"] = outbox["appliedAt"]
            outbox.pop("leaseToken", None)
            outbox.pop("leaseUntil", None)
        inbox = {
            "id": command_id,
            "commandId": command_id,
            "tenantId": tenant_id,
            "projectId": review_run.get("projectId"),
            "nodeId": review_run.get("nodeId"),
            "reviewRunId": review_run_id,
            "commandType": command_type,
            "status": "applied",
            "appliedStatus": result.get("status"),
            "createdAt": server_time(),
        }
        repo.state.setdefault("workflow_inbox", []).insert(0, inbox)
        audit_id = repo.add_audit("应用 ReviewRun 工作流命令", "ReviewRun", review_run_id)
        records = review_run_state_records(review_run_id)
        audit_record = repo.find_one("audit_logs", audit_id)
        if audit_record:
            records.setdefault("audit_logs", []).append(audit_record)
        flush_state_records(records)
        return {
            "status": "applied",
            "commandId": command_id,
            "reviewRunId": review_run_id,
            "reviewRunStatus": review_run.get("status"),
        }
    finally:
        reset_request_tenant_id(tenant_token)
