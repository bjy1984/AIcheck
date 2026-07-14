from __future__ import annotations

import asyncio
import hashlib
import json

from apps.review_worker.activities import apply_review_workflow_command_activity
from apps.review_worker.outbox import deliver_command, finalized_command_payload
from libs.db.repository import repo
from libs.security.tenant import reset_request_tenant_id, set_request_tenant_id


def setup_function() -> None:
    repo.reset()


class RecordingWorkflowHandle:
    def __init__(self) -> None:
        self.signals: list[tuple[str, dict]] = []

    async def signal(self, name: str, payload: dict) -> None:
        self.signals.append((name, payload))


class RecordingTemporalClient:
    def __init__(self) -> None:
        self.workflow_id: str | None = None
        self.handle = RecordingWorkflowHandle()

    def get_workflow_handle(self, workflow_id: str) -> RecordingWorkflowHandle:
        self.workflow_id = workflow_id
        return self.handle


def test_outbox_relay_delivers_idempotent_command_envelope() -> None:
    client = RecordingTemporalClient()
    command = {
        "tenantId": "TENANT-A",
        "objectId": "WFCMD-1",
        "commandId": "WFCMD-1",
        "commandType": "submit_human_decision",
        "reviewRunId": "RRUN-1",
        "workflowId": "review-run-RRUN-1",
        "payloadHash": "sha256-command-payload",
        "signalPayload": {
            "decision": "reject",
            "decisionPayload": {"decision": "reject", "comment": "证据不足"},
        },
    }

    asyncio.run(deliver_command(client, command))

    assert client.workflow_id == "review-run-RRUN-1"
    assert client.handle.signals == [
        (
            "submit_human_decision",
            {
                "commandId": "WFCMD-1",
                "commandType": "submit_human_decision",
                "tenantId": "TENANT-A",
                "reviewRunId": "RRUN-1",
                "payloadHash": "sha256-command-payload",
            },
        )
    ]


def test_outbox_relay_rejects_unknown_command_type() -> None:
    client = RecordingTemporalClient()

    try:
        asyncio.run(
            deliver_command(
                client,
                {
                    "tenantId": "TENANT-A",
                    "objectId": "WFCMD-UNKNOWN",
                    "commandType": "unknown",
                    "reviewRunId": "RRUN-1",
                },
            )
        )
    except ValueError as exc:
        assert "Unsupported ReviewRun workflow command" in str(exc)
    else:
        raise AssertionError("unknown outbox commands must fail closed")


def test_relay_finish_never_downgrades_an_applied_command() -> None:
    payload = finalized_command_payload(
        {
            "status": "applied",
            "attempts": 1,
            "leaseToken": "lease-1",
            "leaseUntil": "2026-07-13T00:00:00+00:00",
            "appliedAt": "2026-07-13T00:00:01+00:00",
        },
        lease_token="lease-1",
        delivered=True,
    )

    assert payload is not None
    assert payload["status"] == "applied"
    assert payload["attempts"] == 1
    assert "leaseToken" not in payload
    assert "leaseUntil" not in payload


def test_durable_inbox_wins_over_a_late_delivery_result() -> None:
    payload = finalized_command_payload(
        {"status": "delivering", "attempts": 0, "leaseToken": "lease-1"},
        lease_token="lease-1",
        delivered=True,
        inbox_exists=True,
    )

    assert payload is not None
    assert payload["status"] == "applied"
    assert payload["attempts"] == 0


def test_command_activity_resolves_sensitive_payload_from_durable_outbox(monkeypatch) -> None:
    tenant_id = "TENANT-COMMAND"
    review_run_id = "RRUN-COMMAND"
    command_id = "WFCMD-COMMAND"
    persisted_payload = {
        "tenantId": tenant_id,
        "reviewRunId": review_run_id,
        "reason": "敏感取消原因只保存在 PostgreSQL outbox",
        "reasonHash": "sha256:reason",
    }
    payload_hash = hashlib.sha256(
        json.dumps(
            persisted_payload,
            ensure_ascii=False,
            sort_keys=True,
            default=str,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    token = set_request_tenant_id(tenant_id)
    try:
        repo.reset()
        run = {
            "id": review_run_id,
            "reviewRunId": review_run_id,
            "tenantId": tenant_id,
            "status": "waiting_human_review",
            "advisoryOnly": True,
            "revision": 1,
        }
        outbox = {
            "id": command_id,
            "commandId": command_id,
            "tenantId": tenant_id,
            "reviewRunId": review_run_id,
            "commandType": "cancel_review",
            "payloadHash": payload_hash,
            "signalPayload": persisted_payload,
            "status": "delivering",
            "leaseToken": "lease-1",
            "leaseUntil": "2026-07-13T00:00:00+00:00",
        }
        repo.state["review_runs"].insert(0, run)
        repo.state["workflow_outbox"].insert(0, outbox)
    finally:
        reset_request_tenant_id(token)
    monkeypatch.setattr("apps.review_worker.activities.activity.heartbeat", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("apps.review_worker.activities.load_review_run_state", lambda _review_run_id: None)
    monkeypatch.setattr("apps.review_worker.activities.flush_state_records", lambda _records: None)

    result = asyncio.run(
        apply_review_workflow_command_activity(
            {
                "commandId": command_id,
                "commandType": "cancel_review",
                "tenantId": tenant_id,
                "reviewRunId": review_run_id,
                "payloadHash": payload_hash,
            }
        )
    )

    assert result["reviewRunStatus"] == "cancelled"
    token = set_request_tenant_id(tenant_id)
    try:
        assert run["cancelReason"] == persisted_payload["reason"]
        assert outbox["status"] == "applied"
        assert "leaseToken" not in outbox
        assert repo.find_one("workflow_inbox", command_id) is not None
    finally:
        reset_request_tenant_id(token)
