from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from apps.api.main import app, idempotency_scope
from libs.business_pack import load_business_pack
from libs.db.repository import repo
from libs.review_orchestrator.execution import (
    human_decision_for_review_run,
    review_run_view,
)
from libs.review_tools import compile_node_tool_plan
from libs.security import auth
from libs.security.auth import decode_token
from libs.security.tenant import reset_request_tenant_id, set_request_tenant_id


client = TestClient(app)


def setup_function() -> None:
    repo.reset()
    repo.postgres_enabled = False
    repo.sync_postgres = None
    repo.postgres_dsn = None
    repo.sqlite_enabled = False
    repo.sqlite_path = None


def seeded_review_run(*, tenant_id: str = "TENANT-DEFAULT") -> dict:
    run = {
        "id": "RRUN-AUDIT-001",
        "reviewRunId": "RRUN-AUDIT-001",
        "aiRunId": "AIRUN-AUDIT-001",
        "tenantId": tenant_id,
        "projectId": "P-2026-HDCP-001",
        "nodeId": 24,
        "status": "waiting_human_review",
        "revision": 3,
        "findingDrafts": [],
        "rawPrompt": "private prompt",
        "rawOcrText": "private OCR",
        "promptAudit": {"promptHash": "sha256:prompt", "messages": ["private"]},
        "llmMetadata": {"resultText": "private"},
    }
    repo.state["review_runs"].insert(0, run)
    return run


def test_review_run_is_tenant_scoped_and_sensitive_fields_are_redacted() -> None:
    other_tenant_run = seeded_review_run(tenant_id="TENANT-OTHER")

    response = client.get(
        f"/api/review-runs/{other_tenant_run['reviewRunId']}",
        headers={"X-Role": "inspection"},
    )

    assert response.json()["data"]["reason"] == "NOT_FOUND"
    view = review_run_view(other_tenant_run)
    assert view["promptSummary"] == {"promptHash": "sha256:prompt"}
    assert "rawPrompt" not in view
    assert "rawOcrText" not in view
    assert "promptAudit" not in view
    assert "llmMetadata" not in view


def test_persistence_boundary_adds_tenant_and_rejects_cross_tenant_rows() -> None:
    local = {"id": "TENANT-ROW-LOCAL"}
    scoped = repo.persistence_tenant_document(local)
    assert local["tenantId"] == "TENANT-DEFAULT"
    assert scoped["tenantId"] == "TENANT-DEFAULT"

    with pytest.raises(RuntimeError, match="Cross-tenant persistence"):
        repo.persistence_tenant_document({"id": "TENANT-ROW-OTHER", "tenantId": "TENANT-OTHER"})


def test_cold_tenant_login_loads_persistent_state_and_writes_tenant_audit(monkeypatch) -> None:
    tenant_id = "TENANT-COLD-LOGIN"
    calls: list[str] = []

    def load_cold_tenant() -> None:
        calls.append(tenant_id)
        repo.state["users"] = [
            {
                "id": "USER-COLD-001",
                "username": "cold-user",
                "passwordHash": auth.hash_password("ColdUser!2026"),
                "role": "inspection",
                "status": "启用",
                "authVersion": 0,
                "mustChangePassword": False,
                "displayName": "冷租户用户",
                "tenantId": tenant_id,
            }
        ]

    monkeypatch.setattr("apps.api.routes.postgres_persistence_configured", lambda: True)
    monkeypatch.setattr("apps.api.routes.load_state", load_cold_tenant)
    response = client.post(
        "/api/auth/login",
        json={"tenantId": tenant_id, "username": "cold-user", "password": "ColdUser!2026"},
    )

    assert response.status_code == 200
    assert calls == [tenant_id]
    claims = decode_token(response.json()["data"]["token"])
    assert claims and claims["tid"] == tenant_id
    token = set_request_tenant_id(tenant_id)
    try:
        login_audit = next(item for item in repo.state["audit_logs"] if item.get("action") == "登录成功")
        assert login_audit["tenantId"] == tenant_id
        assert login_audit["actorId"] == "USER-COLD-001"
    finally:
        reset_request_tenant_id(token)


def test_isolated_mode_rejects_foreign_tenant_login(monkeypatch) -> None:
    monkeypatch.setenv("AICHECK_TENANT_MODE", "isolated")
    monkeypatch.setenv("AICHECK_TENANT_ID", "TENANT-ISOLATED")

    response = client.post(
        "/api/auth/login",
        json={"tenantId": "TENANT-FOREIGN", "username": "inspection", "password": "inspection"},
    )

    assert response.status_code == 403
    assert response.json()["data"]["reason"] == "FORBIDDEN"


def test_failed_request_flush_restores_in_memory_tenant_state(monkeypatch) -> None:
    before = repo.clone(repo.state["audit_logs"])

    def fail_flush(_records: dict, _scopes: list[str]) -> None:
        raise RuntimeError("simulated persistence failure")

    monkeypatch.setattr("apps.api.main.flush_mutation_records", fail_flush)
    with pytest.raises(RuntimeError, match="simulated persistence failure"):
        client.post("/api/auth/login", json={"username": "inspection", "password": "inspection"})

    assert repo.state["audit_logs"] == before


def test_failed_persistent_request_discards_runtime_state_until_reload() -> None:
    repo.mark_tenant_loaded()
    snapshot = repo.snapshot_current_tenant_runtime(include_state=False)
    repo.state["audit_logs"].insert(0, {"id": "AUD-PHANTOM", "tenantId": "TENANT-DEFAULT"})

    repo.restore_tenant_runtime(snapshot, invalidate=True)

    assert repo.find_one("audit_logs", "AUD-PHANTOM") is None
    assert repo.tenant_is_loaded() is False


def test_review_run_terminal_mutation_requires_exact_etag_and_is_one_shot() -> None:
    run = seeded_review_run()
    url = f"/api/review-runs/{run['reviewRunId']}/human-decision"

    missing_precondition = client.post(
        url,
        json={"decision": "reject", "comment": "证据不足，驳回。"},
        headers={"X-Role": "inspection", "Idempotency-Key": "audit-decision-no-etag"},
    )
    assert missing_precondition.status_code == 428
    assert missing_precondition.json()["data"]["reason"] == "PRECONDITION_REQUIRED"

    etag = review_run_view(run)["etag"]
    accepted = client.post(
        url,
        json={"decision": "reject", "comment": "证据不足，驳回。"},
        headers={
            "X-Role": "inspection",
            "Idempotency-Key": "audit-decision-with-etag",
            "If-Match": etag,
        },
    )
    assert accepted.status_code == 200
    assert accepted.json()["data"]["reviewRun"]["status"] == "rejected_by_human"

    repeated = client.post(
        url,
        json={"decision": "accept", "comment": "尝试翻转终态。"},
        headers={
            "X-Role": "inspection",
            "Idempotency-Key": "audit-decision-repeat",
            "If-Match": accepted.json()["data"]["reviewRun"]["etag"],
        },
    )
    assert repeated.status_code == 409
    assert repeated.json()["data"]["reason"] == "CONFLICT"


def test_temporal_human_decision_is_persisted_to_outbox_before_delivery(monkeypatch) -> None:
    run = seeded_review_run()
    run["workflowEngine"] = "temporal"
    run["workflowId"] = "review-run-RRUN-AUDIT-001"
    called = False

    def fail_if_signalled(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("API request must not signal Temporal before the outbox transaction commits")

    monkeypatch.setattr("apps.api.routes.signal_review_run_human_decision", fail_if_signalled)
    response = client.post(
        f"/api/review-runs/{run['reviewRunId']}/human-decision",
        json={"decision": "reject", "comment": "证据不足，进入异步确认。"},
        headers={
            "X-Role": "inspection",
            "Idempotency-Key": "audit-temporal-outbox",
            "If-Match": review_run_view(run)["etag"],
        },
    )

    assert response.status_code == 200
    assert response.json()["data"]["commandStatus"] == "pending"
    assert run["status"] == "waiting_human_review"
    assert run["pendingWorkflowCommand"]["commandId"] == response.json()["data"]["commandId"]
    assert repo.state["workflow_outbox"][0]["status"] == "pending"
    assert called is False


def test_human_edit_revalidates_evidence_references_and_input_limits() -> None:
    run = seeded_review_run()
    run["findingDrafts"] = [
        {
            "id": "FND-DRAFT-AUDIT",
            "reviewRunId": run["reviewRunId"],
            "findingType": "ai_review_suggestion",
            "severity": "medium",
            "title": "待确认",
            "description": "原始发现",
            "evidenceRefs": [],
            "ruleRefs": [],
            "kbRefs": [],
            "confidence": 0.5,
            "suggestedAction": "human_confirm",
            "requiresHumanConfirmation": True,
            "groundingStatus": "insufficient_evidence",
            "unsupportedClaims": [],
        }
    ]

    invalid_refs = human_decision_for_review_run(
        run["reviewRunId"],
        "edit",
        {
            "comment": "人工修改引用。",
            "correctedOutput": [
                {
                    "sourceDraftId": "FND-DRAFT-AUDIT",
                    "evidenceRefs": [{"evidenceLinkId": "EV-NOT-EXIST"}],
                }
            ],
        },
    )
    assert invalid_refs["status"] == "invalid_corrected_output"
    assert invalid_refs["error"]["code"] == "CORRECTED_OUTPUT_EVIDENCE_REFS_INVALID"
    assert run["status"] == "waiting_human_review"

    run["findingDrafts"][0]["evidenceRefs"] = [{"evidenceLinkId": "EV-STALE-NOT-EXIST"}]
    stale_refs = human_decision_for_review_run(
        run["reviewRunId"],
        "edit",
        {
            "comment": "仅修改结论文本，但必须重新校验证据。",
            "correctedOutput": [
                {
                    "sourceDraftId": "FND-DRAFT-AUDIT",
                    "title": "人工修改后的新结论",
                }
            ],
        },
    )
    assert stale_refs["status"] == "invalid_corrected_output"
    assert stale_refs["error"]["code"] == "CORRECTED_OUTPUT_EVIDENCE_REFS_INVALID"
    assert run["status"] == "waiting_human_review"

    too_long = human_decision_for_review_run(
        run["reviewRunId"],
        "reject",
        {"comment": "x" * 2001},
    )
    assert too_long["status"] == "invalid_input"
    assert run["status"] == "waiting_human_review"


def test_jwt_missing_required_tenant_claim_is_rejected() -> None:
    now = datetime.now(timezone.utc)
    token = auth.jwt.encode(
        {
            "sub": "admin",
            "role": "admin",
            "ver": 0,
            "iss": auth.jwt_issuer(),
            "aud": auth.jwt_audience(),
            "iat": now,
            "exp": now + timedelta(minutes=5),
            "jti": "audit-missing-tenant",
        },
        auth.jwt_secret(),
        algorithm=auth.JWT_ALGORITHM,
    )

    assert auth.decode_token(str(token)) is None


def test_idempotency_scope_is_actor_and_tenant_bound() -> None:
    def request_for(user_id: str, tenant_id: str) -> Request:
        request = Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/review-runs/RRUN-AUDIT-001/cancel",
                "query_string": b"",
                "headers": [(b"idempotency-key", b"same-key")],
                "client": ("127.0.0.1", 1234),
                "server": ("testserver", 80),
                "scheme": "http",
            }
        )
        request.state.auth_user = {"id": user_id, "tenantId": tenant_id}
        request.state.auth = {"role": "inspection", "tid": tenant_id}
        return request

    assert idempotency_scope(request_for("USER-A", "TENANT-A")) != idempotency_scope(
        request_for("USER-B", "TENANT-A")
    )
    assert idempotency_scope(request_for("USER-A", "TENANT-A")) != idempotency_scope(
        request_for("USER-A", "TENANT-B")
    )


def test_audit_chain_detects_mutation() -> None:
    first_id = repo.add_audit("创建", "TestObject", "OBJ-1")
    second_id = repo.add_audit("更新", "TestObject", "OBJ-1")

    assert repo.verify_audit_chain("TENANT-DEFAULT")["status"] == "verified"
    repo.find_one("audit_logs", second_id)["action"] = "被篡改"
    integrity = repo.verify_audit_chain("TENANT-DEFAULT")
    assert integrity["status"] == "tampered"
    assert integrity["failures"]
    assert repo.find_one("audit_logs", first_id)["previousHash"] == "GENESIS"


def test_archived_project_recompute_and_knowledge_preview_are_guarded() -> None:
    project = repo.require_project("P-2026-HDCP-001")
    project["status"] = "已归档"

    archived = client.post(
        "/api/projects/P-2026-HDCP-001/material-targeting/recompute",
        headers={"X-Role": "inspection", "Idempotency-Key": "archived-recompute"},
    )
    assert archived.json()["data"]["reason"] == "ARCHIVED_READONLY"

    preview = client.post(
        "/api/knowledge/reindex-preview",
        json={"targetType": "all"},
        headers={"X-Role": "owner"},
    )
    assert preview.json()["data"]["reason"] == "FORBIDDEN"


def test_formal_review_rejects_draft_binding_set() -> None:
    pack = load_business_pack("engineering_inspection_v1")

    with pytest.raises(ValueError, match="requires published"):
        compile_node_tool_plan(
            pack,
            "R36",
            available_tools=set(),
            require_published=True,
        )


def test_admin_has_no_implicit_raw_ai_access_without_grant() -> None:
    response = client.get(
        "/api/fde/ai-runs/AIRUN-24-20260625-01",
        headers={"X-Role": "admin"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["run"]["rawAccess"] is False
    assert response.json()["data"]["llmAudit"]["visibility"] == "masked"


def test_fde_cannot_target_another_tenant_for_business_pack_install() -> None:
    response = client.post(
        "/api/fde/business-packs/engineering_inspection_v1/install",
        json={"tenantId": "TENANT-OTHER", "dryRun": True},
        headers={"X-Role": "fde", "Idempotency-Key": "cross-tenant-pack-install"},
    )

    assert response.json()["data"]["reason"] == "FORBIDDEN"
