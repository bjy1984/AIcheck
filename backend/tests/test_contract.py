from __future__ import annotations

import io
import json
import inspect
import zipfile

from fastapi.testclient import TestClient

from libs.db.indexes import MONGO_INDEXES, ensure_mongo_indexes
from libs.db.mongo import run_transaction_probe
from apps.api.main import app
from libs.db.repository import IDEMPOTENCY_COLLECTION, SINGLETON_COLLECTIONS, STATE_COLLECTIONS, repo


client = TestClient(app)


def setup_function() -> None:
    repo.reset()
    repo.mongo = None
    repo.sync_mongo = None


def assert_ok(response):
    assert response.status_code == 200
    payload = response.json()
    assert payload["code"] == 0
    assert "operationId" in payload
    assert "serverTime" in payload
    return payload["data"]


def assert_error(response, reason: str):
    assert response.status_code == 200
    payload = response.json()
    assert payload["code"] != 0
    assert payload["data"]["reason"] == reason
    assert "operationId" in payload
    assert "serverTime" in payload
    return payload


def test_response_envelope_and_api_prefix_compatibility() -> None:
    data = assert_ok(client.get("/workbench/projects?role=inspection"))
    prefixed = assert_ok(client.get("/api/workbench/projects?role=inspection"))

    assert data[0]["id"] == "P-2026-HDCP-001"
    assert prefixed[0]["currentNodeId"] == 24
    assert prefixed[0]["riskLevel"] == "高"


def test_healthz_reports_runtime_flags(monkeypatch) -> None:
    monkeypatch.setenv("AICHECK_REQUIRE_AUTH", "true")
    monkeypatch.setenv("AICHECK_ENABLE_DEMO_USERS", "false")
    monkeypatch.setenv("AICHECK_MONGO_TRANSACTIONS", "true")

    health = assert_ok(client.get("/api/healthz"))

    assert health["service"] == "api-service"
    assert health["authRequired"] is True
    assert health["demoUsersEnabled"] is False
    assert health["mongoTransactions"] is True
    assert "objectStorageEnabled" in health


def test_mongo_transaction_probe_endpoint_is_admin_only_when_auth_enabled(monkeypatch) -> None:
    monkeypatch.setenv("AICHECK_REQUIRE_AUTH", "true")
    contractor = assert_ok(client.post("/api/auth/login", json={"username": "contractor", "password": "contractor"}))
    admin = assert_ok(client.post("/api/auth/login", json={"username": "admin", "password": "admin"}))

    assert_error(
        client.get(
            "/api/system/mongo-transaction-probe",
            headers={"Authorization": f"Bearer {contractor['token']}"},
        ),
        "FORBIDDEN",
    )
    result = assert_ok(
        client.get(
            "/api/system/mongo-transaction-probe",
            headers={"Authorization": f"Bearer {admin['token']}"},
        )
    )

    assert result["mongoEnabled"] is False
    assert result["transactionProbe"] == "skipped"


def test_ocr_healthz_reports_pipeline_flags(monkeypatch) -> None:
    from apps.ocr_service.main import app as ocr_app

    monkeypatch.setenv("AICHECK_OCR_ALLOW_PLACEHOLDER", "false")
    ocr_client = TestClient(ocr_app)
    health = assert_ok(ocr_client.get("/healthz"))

    assert health["service"] == "ocr-service"
    assert "pipelineAvailable" in health
    assert "pipelineBackend" in health
    assert health["placeholderAllowed"] is False


def test_ocr_parse_rejects_missing_storage_key() -> None:
    from apps.ocr_service.main import app as ocr_app

    ocr_client = TestClient(ocr_app)
    payload = ocr_client.post("/internal/ocr/parse", json={}).json()

    assert payload["code"] != 0
    assert payload["data"]["reason"] == "VALIDATION_ERROR"
    assert "operationId" in payload
    assert "serverTime" in payload


def test_litellm_client_rejects_default_key_when_production_flags_are_enabled(monkeypatch) -> None:
    from libs.integrations.litellm_client import LiteLLMClient

    monkeypatch.delenv("LITELLM_API_KEY", raising=False)
    monkeypatch.setenv("AICHECK_REQUIRE_AUTH", "true")

    try:
        LiteLLMClient()
    except RuntimeError as exc:
        assert "LITELLM_API_KEY" in str(exc)
    else:
        raise AssertionError("production LiteLLM client must require an explicit key")

    client_with_key = LiteLLMClient(api_key="sk-production-test")
    assert client_with_key.api_key == "sk-production-test"


def test_login_compatibility_paths() -> None:
    cases = {
        "inspection": "/workbench/inspection",
        "contractor": "/workbench/contractor",
        "ndt": "/workbench/ndt",
        "owner": "/workbench/owner",
        "admin": "/admin/overview",
    }

    for username, default_path in cases.items():
        mock_user = assert_ok(client.post("/mock/user/login", json={"username": username, "password": username}))
        real_login = assert_ok(client.post("/api/auth/login", json={"username": username, "password": username}))

        assert mock_user["username"] == username
        assert mock_user["role"] == username
        assert mock_user["defaultPath"] == default_path
        assert real_login["token"]
        assert real_login["user"]["role"] == username
        assert real_login["user"]["defaultPath"] == default_path

        me = assert_ok(client.get("/api/auth/me", headers={"Authorization": f"Bearer {real_login['token']}"}))
        assert me["username"] == username
        assert me["defaultRole"] == username


def test_persistent_user_login_when_demo_users_disabled(monkeypatch) -> None:
    monkeypatch.setenv("AICHECK_ENABLE_DEMO_USERS", "false")
    repo.state["users"].append(
        {
            "id": "USER-PERSISTENT-001",
            "username": "persistent",
            "passwordHash": "plain:secret",
            "role": "inspection",
            "roleId": "2",
            "roleLabel": "监检人员",
            "displayName": "真实用户",
            "orgUnitName": "省特检院一部",
            "permissions": ["review:save"],
            "status": "启用",
            "defaultPath": "/workbench/inspection",
        }
    )

    login = assert_ok(client.post("/api/auth/login", json={"username": "persistent", "password": "secret"}))
    assert login["user"]["username"] == "persistent"
    assert login["user"]["role"] == "inspection"
    assert_error(client.post("/api/auth/login", json={"username": "inspection", "password": "inspection"}), "AUTH_REQUIRED")


def test_frontend_route_groups_return_success() -> None:
    project_id = "P-2026-HDCP-001"
    route_cases = [
        ("GET", f"/projects/{project_id}/workbench/context?role=inspection", None),
        ("GET", f"/projects/{project_id}/workbench/summary?role=inspection", None),
        ("GET", f"/projects/{project_id}/tree", None),
        ("GET", f"/projects/{project_id}/nodes/24/package", None),
        ("GET", f"/projects/{project_id}/documents/DOC-20260625-001", None),
        ("GET", f"/projects/{project_id}/owner/reports", None),
        ("GET", f"/projects/{project_id}/archive", None),
        ("GET", f"/projects/{project_id}/ndt/films", None),
        ("GET", f"/projects/{project_id}/ndt/records", None),
        ("GET", f"/projects/{project_id}/ndt/reports", None),
        ("GET", "/knowledge/overview", None),
        ("GET", "/knowledge/sources", None),
        ("GET", "/knowledge/project-files", None),
        ("GET", "/knowledge/tasks", None),
        ("GET", "/rules/versions", None),
        ("GET", "/admin/config-overview", None),
        ("GET", "/admin/integration-contract", None),
        ("GET", "/admin/audit-logs", None),
        ("GET", "/todos", None),
        ("GET", "/messages", None),
        ("GET", "/search?keyword=焊工", None),
    ]

    for method, path, body in route_cases:
        response = client.request(method, path, json=body)
        assert_ok(response)


def test_submission_idempotency_replays_same_response() -> None:
    project_id = "P-2026-HDCP-001"
    payload = {
        "nodeId": 16,
        "nodeIds": [16],
        "bindingIds": ["BIND-16-001"],
        "submitterComment": "contract test",
    }
    headers = {"Idempotency-Key": "submit-once"}

    first = assert_ok(client.post(f"/projects/{project_id}/submissions", json=payload, headers=headers))
    second = assert_ok(client.post(f"/projects/{project_id}/submissions", json=payload, headers=headers))

    assert first["submissionId"] == second["submissionId"]
    assert first["snapshotId"] == second["snapshotId"]

    conflict_payload = {**payload, "submitterComment": "different body"}
    assert_error(
        client.post(f"/projects/{project_id}/submissions", json=conflict_payload, headers=headers),
        "IDEMPOTENCY_KEY_CONFLICT",
    )


def test_global_idempotency_covers_mutations_without_explicit_route_parameter() -> None:
    project_id = "P-2026-HDCP-001"
    document_id = "DOC-20260625-003"
    headers = {"Idempotency-Key": "append-version-once"}
    payload = {"fileSize": 1024, "mode": "append"}
    before_count = len(repo.versions_for_document(document_id))

    first = assert_ok(client.post(f"/projects/{project_id}/documents/{document_id}/versions", json=payload, headers=headers))
    second = assert_ok(client.post(f"/projects/{project_id}/documents/{document_id}/versions", json=payload, headers=headers))

    assert first["version"]["id"] == second["version"]["id"]
    assert len(repo.versions_for_document(document_id)) == before_count + 1
    assert_error(
        client.post(
            f"/projects/{project_id}/documents/{document_id}/versions",
            json={**payload, "fileSize": 2048},
            headers=headers,
        ),
        "IDEMPOTENCY_KEY_CONFLICT",
    )


def test_global_audit_covers_mutations_without_explicit_audit_log() -> None:
    project_id = "P-2026-HDCP-001"
    before = len(repo.state["audit_logs"])

    run = assert_ok(client.post(f"/projects/{project_id}/inspection/nodes/24/ai-recheck"))

    assert "runId" in run
    assert len(repo.state["audit_logs"]) == before + 1
    audit = repo.state["audit_logs"][0]
    assert audit["objectType"] == "ApiMutation"
    assert audit["objectId"] == f"/projects/{project_id}/inspection/nodes/24/ai-recheck"
    assert audit["operationId"].startswith("OP-")


def test_global_audit_does_not_duplicate_explicit_audit_log() -> None:
    project_id = "P-2026-HDCP-001"
    before = len(repo.state["audit_logs"])

    result = assert_ok(client.patch(f"/projects/{project_id}", json={"name": "审计不重复"}))

    assert result["auditLogId"]
    assert len(repo.state["audit_logs"]) == before + 1


def test_withdraw_submission_items_enforces_batch_and_locked_state() -> None:
    project_id = "P-2026-HDCP-001"
    payload = {
        "nodeId": 16,
        "nodeIds": [16],
        "bindingIds": ["BIND-16-001"],
        "submitterComment": "withdraw state machine test",
    }
    submission = assert_ok(client.post(f"/projects/{project_id}/submissions", json=payload))
    submission_id = submission["submissionId"]

    assert_error(
        client.post(
            f"/projects/{project_id}/submissions/SUB-MISSING/withdraw-items",
            json={"bindingIds": ["BIND-16-001"]},
        ),
        "NOT_FOUND",
    )
    assert_error(
        client.post(
            f"/projects/{project_id}/submissions/{submission_id}/withdraw-items",
            json={"bindingIds": ["BIND-24-001"]},
        ),
        "CONFLICT",
    )

    binding = next(item for item in repo.state["bindings"] if item["id"] == "BIND-16-001")
    binding["bindingStatus"] = "已通过"
    assert_error(
        client.post(
            f"/projects/{project_id}/submissions/{submission_id}/withdraw-items",
            json={"bindingIds": ["BIND-16-001"]},
        ),
        "WITHDRAW_LOCKED",
    )

    binding["bindingStatus"] = "已提交"
    withdrawn = assert_ok(
        client.post(
            f"/projects/{project_id}/submissions/{submission_id}/withdraw-items",
            json={"bindingIds": ["BIND-16-001"], "reason": "资料版本修正"},
        )
    )
    stored_submission = next(item for item in repo.state["submissions"] if item["submissionId"] == submission_id)

    assert withdrawn["nextStatus"] == "部分提交"
    assert binding["bindingStatus"] == "草稿挂载"
    assert stored_submission["withdrawnBindingIds"] == ["BIND-16-001"]
    assert stored_submission["withdrawal"]["bindingCount"] == 1


def test_submit_rectification_updates_pending_item_and_enforces_scope() -> None:
    project_id = "P-2026-HDCP-001"
    assert_error(
        client.post(
            f"/projects/{project_id}/rectifications",
            json={"nodeId": 24, "bindingIds": ["BIND-24-001"], "comment": "没有待反馈单"},
        ),
        "CONFLICT",
    )
    assert_error(
        client.post(
            f"/projects/{project_id}/rectifications",
            json={"nodeId": 16, "bindingIds": ["BIND-24-001"], "comment": "跨节点资料"},
        ),
        "CONFLICT",
    )

    feedback = assert_ok(
        client.post(
            f"/projects/{project_id}/rectifications",
            json={"nodeId": 16, "bindingIds": ["BIND-16-001"], "comment": "已补充炉批号差异说明。"},
        )
    )
    rectification = repo.find_one("rectifications", "REC-16-001")
    node = repo.node(project_id, 16)

    assert feedback["rectification"]["id"] == "REC-16-001"
    assert feedback["nextStatus"] == "复审中"
    assert rectification["status"] == "已反馈"
    assert rectification["bindingIds"] == ["BIND-16-001"]
    assert node["status"] == "复审中"
    assert len([item for item in repo.state["rectifications"] if item["id"] == "REC-16-001"]) == 1
    assert_error(
        client.post(
            f"/projects/{project_id}/rectifications",
            json={"nodeId": 16, "bindingIds": ["BIND-16-001"], "comment": "重复反馈"},
        ),
        "CONFLICT",
    )


def test_generate_report_review_requires_existing_ready_node() -> None:
    project_id = "P-2026-HDCP-001"
    payload = {"includeEvidence": True, "reportScope": "currentNode"}

    assert_error(
        client.post(f"/projects/{project_id}/inspection/nodes/999/report-review", json=payload),
        "NOT_FOUND",
    )
    assert_error(
        client.post(f"/projects/{project_id}/inspection/nodes/16/report-review", json=payload),
        "CONFLICT",
    )

    generated = assert_ok(client.post(f"/projects/{project_id}/inspection/nodes/24/report-review", json=payload))
    assert generated["report"]["nodeIds"] == [24]
    assert generated["nextStatus"] == "报告生成/复核中"


def test_owner_write_forbidden_and_archived_readonly() -> None:
    project_id = "P-2026-HDCP-001"
    owner_write = client.post(
        f"/projects/{project_id}/inspection/nodes/24/ai-recheck",
        headers={"X-Role": "owner"},
    )
    assert_error(owner_write, "FORBIDDEN")
    assert_error(client.post("/todos/TODO-001/complete", headers={"X-Role": "owner"}), "FORBIDDEN")
    assert_error(client.post("/messages/MSG-001/read", headers={"X-Role": "owner"}), "FORBIDDEN")
    assert_error(client.post("/messages/read-all", headers={"X-Role": "owner"}), "FORBIDDEN")

    archived = client.post(
        "/projects/P-2025-CQARCH-007/documents/upload-session",
        json={"files": [{"fileName": "readonly.pdf", "fileSize": 1, "fileType": "application/pdf"}]},
    )
    assert_error(archived, "ARCHIVED_READONLY")
    assert_error(
        client.post("/projects/P-2025-CQARCH-007/documents/batch-classify", json={}),
        "ARCHIVED_READONLY",
    )
    assert_error(
        client.post("/projects/P-2025-CQARCH-007/inspection/nodes/24/attachments", json={}),
        "ARCHIVED_READONLY",
    )
    assert_error(
        client.post("/projects/P-2025-CQARCH-007/inspection/nodes/24/file-bindings", json={"documentIds": ["DOC-20260625-001"]}),
        "ARCHIVED_READONLY",
    )


def test_if_match_conflict_and_review_admin_guard() -> None:
    conflict = client.patch(
        "/projects/P-2026-HDCP-001",
        json={"name": "changed"},
        headers={"If-Match": "W/\"outdated\""},
    )
    assert_error(conflict, "ETAG_CONFLICT")

    admin_review = client.post(
        "/projects/P-2026-HDCP-001/inspection/nodes/24/review-opinions",
        headers={"X-Role": "admin"},
        json={"result": "满足要求", "opinion": "admin should not save", "evidenceLinkIds": []},
    )
    assert_error(admin_review, "FORBIDDEN")


def test_optional_jwt_action_and_node_scope_guards(monkeypatch) -> None:
    monkeypatch.setenv("AICHECK_REQUIRE_AUTH", "true")
    unauthenticated = client.get("/api/auth/me")
    assert_error(unauthenticated, "AUTH_REQUIRED")

    role_spoof = client.post(
        "/projects/P-2026-HDCP-001/inspection/nodes/24/ai-recheck",
        headers={"Authorization": "Bearer dev-token-contractor-contractor", "X-Role": "inspection"},
    )
    assert_error(role_spoof, "FORBIDDEN")

    action_forbidden = client.post(
        "/projects/P-2026-HDCP-001/inspection/nodes/24/ai-recheck",
        headers={"Authorization": "Bearer dev-token-admin-admin", "X-Role": "contractor", "X-Action-Code": "review:save"},
    )
    assert_error(action_forbidden, "FORBIDDEN")

    inferred_node_forbidden = client.post(
        "/projects/P-2026-HDCP-001/inspection/nodes/40/ai-recheck",
        headers={"Authorization": "Bearer dev-token-contractor-contractor", "X-Role": "contractor"},
    )
    assert_error(inferred_node_forbidden, "FORBIDDEN")

    node_forbidden = client.post(
        "/projects/P-2026-HDCP-001/inspection/nodes/40/ai-recheck",
        headers={
            "Authorization": "Bearer dev-token-admin-admin",
            "X-Role": "contractor",
            "X-User-Id": "USER-CONTRACTOR-001",
        },
    )
    assert_error(node_forbidden, "FORBIDDEN")


def test_required_action_inference_covers_core_mutations() -> None:
    from libs.security.actions import required_action_for_request

    cases = [
        ("POST", "/api/projects/P-2026-HDCP-001/submissions", "submission:submit"),
        ("POST", "/api/projects/P-2026-HDCP-001/documents/batch-classify", "file:bind"),
        ("POST", "/api/projects/P-2026-HDCP-001/inspection/nodes/24/report-review", "report:generate"),
        ("POST", "/api/projects/P-2026-HDCP-001/reports/RPT-001/archive", "report:archive"),
        ("POST", "/api/projects/P-2026-HDCP-001/ndt/submissions", "ndt:submit"),
        ("POST", "/api/todos/TODO-001/complete", "todo:update"),
        ("POST", "/api/messages/MSG-001/read", "message:update"),
        ("POST", "/api/knowledge/retrieval-test", "knowledge:view"),
        ("POST", "/api/admin/config-overview/publish", "admin:config"),
        ("PUT", "/api/admin/config-items/todo-rule/TR-001", "admin:config"),
        ("PATCH", "/api/knowledge/config", "knowledge:manage"),
        ("PUT", "/api/knowledge/config", "knowledge:manage"),
        ("POST", "/api/llm/compare", "llm:compare"),
    ]

    for method, path, expected in cases:
        assert required_action_for_request(method, path) == expected
    assert required_action_for_request("GET", "/api/admin/config-overview") is None


def test_all_non_public_mutating_routes_have_inferred_action_codes() -> None:
    from libs.security.actions import MUTATING_METHODS, required_action_for_request

    public_mutations = {
        ("POST", "/mock/user/login"),
        ("POST", "/api/mock/user/login"),
        ("POST", "/auth/login"),
        ("POST", "/api/auth/login"),
        ("POST", "/auth/logout"),
        ("POST", "/api/auth/logout"),
    }
    missing = []
    for route in app.routes:
        path = getattr(route, "path", "")
        methods = set(getattr(route, "methods", set()) or set()) & MUTATING_METHODS
        for method in methods:
            if (method, path) in public_mutations:
                continue
            if required_action_for_request(method, path) is None:
                missing.append(f"{method} {path}")

    assert missing == []


def test_project_mutating_routes_are_archived_readonly_guarded() -> None:
    from libs.security.actions import MUTATING_METHODS
    import apps.api.routes as route_module

    delegated_guard_routes = {
        ("POST", "/projects/{project_id}/inspection/nodes/{node_id}/attachments"),
        ("POST", "/projects/{project_id}/inspection/nodes/{node_id}/file-bindings"),
        ("POST", "/api/projects/{project_id}/inspection/nodes/{node_id}/attachments"),
        ("POST", "/api/projects/{project_id}/inspection/nodes/{node_id}/file-bindings"),
    }
    missing = []
    for route in app.routes:
        path = getattr(route, "path", "")
        if "{project_id}" not in path:
            continue
        methods = set(getattr(route, "methods", set()) or set()) & MUTATING_METHODS
        for method in methods:
            if (method, path) in delegated_guard_routes:
                continue
            endpoint = getattr(route, "endpoint", None)
            source = inspect.getsource(endpoint) if endpoint is not None else ""
            if "mutation_guard(" not in source:
                missing.append(f"{method} {path}")

    assert missing == []


def test_all_non_public_mutating_routes_are_audit_logged() -> None:
    from apps.api.main import audit_scope
    from libs.security.actions import MUTATING_METHODS

    unaudited_public_routes = {
        ("POST", "/mock/user/login"),
        ("POST", "/api/mock/user/login"),
        ("POST", "/auth/login"),
        ("POST", "/api/auth/login"),
        ("POST", "/auth/logout"),
        ("POST", "/api/auth/logout"),
    }
    missing = []
    for route in app.routes:
        path = getattr(route, "path", "")
        methods = set(getattr(route, "methods", set()) or set()) & MUTATING_METHODS
        for method in methods:
            if (method, path) in unaudited_public_routes:
                continue
            assert audit_scope(type("Req", (), {"method": method, "url": type("Url", (), {"path": path})()})()) is not None
            endpoint = getattr(route, "endpoint", None)
            source = inspect.getsource(endpoint) if endpoint is not None else ""
            has_explicit_audit = "mutation_result" in source or "add_audit" in source or "auditLogId" in source
            if not has_explicit_audit and audit_scope(type("Req", (), {"method": method, "url": type("Url", (), {"path": path})()})()) is None:
                missing.append(f"{method} {path}")

    assert missing == []


def test_inferred_action_codes_block_role_bypass_when_auth_required(monkeypatch) -> None:
    monkeypatch.setenv("AICHECK_REQUIRE_AUTH", "true")
    project_id = "P-2026-HDCP-001"
    contractor_headers = {"Authorization": "Bearer dev-token-contractor-contractor"}
    inspection_headers = {"Authorization": "Bearer dev-token-inspection-inspection"}
    ndt_headers = {"Authorization": "Bearer dev-token-ndt-ndt"}
    admin_headers = {"Authorization": "Bearer dev-token-admin-admin"}

    assert_error(
        client.post(
            f"/api/projects/{project_id}/inspection/nodes/24/report-review",
            json={"includeEvidence": True, "reportScope": "currentNode"},
            headers=contractor_headers,
        ),
        "FORBIDDEN",
    )
    assert_error(
        client.post(
            "/api/admin/config-overview/publish",
            json={"scope": "all"},
            headers=contractor_headers,
        ),
        "FORBIDDEN",
    )
    assert_error(
        client.post(
            f"/api/projects/{project_id}/submissions",
            json={"nodeIds": [16], "bindingIds": ["BIND-16-001"]},
            headers=inspection_headers,
        ),
        "FORBIDDEN",
    )

    ndt_submit = assert_ok(
        client.post(
            f"/api/projects/{project_id}/ndt/submissions",
            json={"nodeId": 40, "reportIds": ["NDT-RPT-001"], "filmIds": ["FILM-RT-001"]},
            headers=ndt_headers,
        )
    )
    admin_publish = assert_ok(
        client.post(
            "/api/admin/config-overview/publish",
            json={"scope": "all"},
            headers=admin_headers,
        )
    )

    assert ndt_submit["nextStatus"] == "待审查"
    assert admin_publish["status"] == "已发布"


def test_body_node_scope_is_enforced_for_project_mutations(monkeypatch) -> None:
    monkeypatch.setenv("AICHECK_REQUIRE_AUTH", "true")
    project_id = "P-2026-HDCP-001"
    contractor_headers = {"Authorization": "Bearer dev-token-contractor-contractor"}
    ndt_headers = {"Authorization": "Bearer dev-token-ndt-ndt"}

    assert_error(
        client.post(
            f"/api/projects/{project_id}/submissions",
            json={"nodeIds": [40], "bindingIds": ["BIND-40-001"]},
            headers=contractor_headers,
        ),
        "FORBIDDEN",
    )
    assert_error(
        client.post(
            f"/api/projects/{project_id}/documents/bindings",
            json={"nodeId": 40, "bindings": [{"documentId": "DOC-20260625-004"}]},
            headers=contractor_headers,
        ),
        "FORBIDDEN",
    )
    assert_error(
        client.post(
            f"/api/projects/{project_id}/ndt/records/import",
            json={"nodeId": 24, "rows": [{"recordNo": "OUT-OF-SCOPE", "weldNo": "W-24", "method": "RT"}]},
            headers=ndt_headers,
        ),
        "FORBIDDEN",
    )

    contractor_submit = assert_ok(
        client.post(
            f"/api/projects/{project_id}/submissions",
            json={"nodeIds": [16], "bindingIds": ["BIND-16-001"]},
            headers=contractor_headers,
        )
    )
    ndt_import = assert_ok(
        client.post(
            f"/api/projects/{project_id}/ndt/records/import",
            json={"nodeId": 40, "rows": [{"recordNo": "IN-SCOPE", "weldNo": "W-40", "method": "RT"}]},
            headers=ndt_headers,
        )
    )

    assert contractor_submit["nextStatus"] == "AI 预审中"
    assert ndt_import["records"][0]["nodeId"] == 40


def test_resource_id_node_scope_is_enforced_for_project_mutations(monkeypatch) -> None:
    monkeypatch.setenv("AICHECK_REQUIRE_AUTH", "true")
    project_id = "P-2026-HDCP-001"
    contractor_headers = {"Authorization": "Bearer dev-token-contractor-contractor"}
    inspection_headers = {"Authorization": "Bearer dev-token-inspection-inspection"}

    assert_error(
        client.post(
            f"/api/projects/{project_id}/documents/DOC-20260625-004/withdraw",
            headers=contractor_headers,
        ),
        "FORBIDDEN",
    )
    assert_error(
        client.patch(
            f"/api/projects/{project_id}/documents/bindings/BIND-40-001",
            json={"usage": "越权修改"},
            headers=contractor_headers,
        ),
        "FORBIDDEN",
    )

    own_document = assert_ok(
        client.post(
            f"/api/projects/{project_id}/documents/DOC-20260625-003/withdraw",
            headers=contractor_headers,
        )
    )
    assert own_document["nextStatus"] == "已撤回"

    inspection_member = next(item for item in repo.state["project_members"] if item["userId"] == "USER-INSPECTION-001")
    inspection_member["nodeScope"] = [24]
    assert_error(
        client.post(
            f"/api/projects/{project_id}/reports/RPT-20260625-001/export",
            json={"format": "pdf"},
            headers=inspection_headers,
        ),
        "FORBIDDEN",
    )
    assert_error(
        client.post(
            f"/api/projects/{project_id}/reports/RPT-20250618-007/export",
            json={"format": "pdf"},
            headers=inspection_headers,
        ),
        "NOT_FOUND",
    )


def test_read_project_scope_enforces_url_query_and_resource_nodes(monkeypatch) -> None:
    monkeypatch.setenv("AICHECK_REQUIRE_AUTH", "true")
    project_id = "P-2026-HDCP-001"
    contractor_headers = {"Authorization": "Bearer dev-token-contractor-contractor"}
    owner_headers = {"Authorization": "Bearer dev-token-owner-owner"}
    ndt_headers = {"Authorization": "Bearer dev-token-ndt-ndt"}
    admin_headers = {"Authorization": "Bearer dev-token-admin-admin"}
    repo.state["todos"].extend(
        [
            {
                "id": "TODO-SCOPE-40",
                "title": "节点 40 越权待办",
                "projectId": project_id,
                "nodeId": 40,
                "targetType": "node",
                "targetId": "40",
                "status": "待处理",
                "priority": "高",
                "actions": ["review:save"],
            },
            {
                "id": "TODO-SCOPE-RPT",
                "title": "跨节点报告待办",
                "projectId": project_id,
                "targetType": "report",
                "targetId": "RPT-20260625-001",
                "status": "待处理",
                "priority": "中",
                "actions": ["report:review"],
            },
        ]
    )
    repo.state["messages"].append(
        {
            "id": "MSG-SCOPE-40",
            "title": "节点 40 越权消息",
            "content": "节点 40 有新状态。",
            "projectId": project_id,
            "targetType": "node",
            "targetId": "40",
            "read": False,
            "createdAt": "2026-06-27 09:00:00",
        }
    )
    repo.state["ai_runs"].append(
        {
            "id": "AIRUN-SCOPE-40",
            "projectId": project_id,
            "nodeId": 40,
            "subject": "无损检测资料",
            "model": "review-chat",
            "status": "完成",
            "startedAt": "2026-06-27 09:00:00",
            "steps": [],
        }
    )
    repo.state["llm_compare_runs"].append(
        {
            "runId": "CMP-SCOPE-40",
            "question": "节点 40 对比",
            "modelCodes": ["default-chat"],
            "createdAt": "2026-06-27 09:00:00",
            "projectId": project_id,
            "nodeId": 40,
            "status": "完成",
            "results": [],
        }
    )

    assert_error(
        client.get(f"/api/projects/{project_id}/nodes/40/package", headers=contractor_headers),
        "FORBIDDEN",
    )
    assert_error(
        client.get(f"/api/projects/{project_id}/documents?nodeId=40", headers=contractor_headers),
        "FORBIDDEN",
    )
    assert_error(
        client.get(f"/api/projects/{project_id}/documents/DOC-20260625-004", headers=contractor_headers),
        "FORBIDDEN",
    )
    assert_error(
        client.get(f"/api/projects/{project_id}/reports/RPT-20260625-001", headers=contractor_headers),
        "FORBIDDEN",
    )
    assert_error(
        client.get(f"/api/projects/{project_id}/workbench/context?role=inspection", headers=contractor_headers),
        "FORBIDDEN",
    )
    assert_error(
        client.get("/api/todos/TODO-SCOPE-40", headers=contractor_headers),
        "FORBIDDEN",
    )
    assert_error(
        client.post("/api/messages/MSG-SCOPE-40/read", headers=contractor_headers),
        "FORBIDDEN",
    )
    assert_error(
        client.get("/api/knowledge/files/KF-DOC-20260625-004", headers=contractor_headers),
        "FORBIDDEN",
    )
    assert_error(
        client.get("/api/knowledge/tasks/KT-20260626-001", headers=contractor_headers),
        "FORBIDDEN",
    )
    assert_error(
        client.get("/api/reasoning/logs/AIRUN-SCOPE-40", headers=contractor_headers),
        "FORBIDDEN",
    )
    assert_error(
        client.get("/api/llm/compare-runs/CMP-SCOPE-40", headers=contractor_headers),
        "FORBIDDEN",
    )
    assert_error(
        client.get(f"/api/projects/{project_id}/ndt/films/FILM-RT-001", headers=contractor_headers),
        "FORBIDDEN",
    )
    assert_error(
        client.get(f"/api/projects/{project_id}/ndt/reports/NDT-RPT-001", headers=contractor_headers),
        "FORBIDDEN",
    )
    assert_error(
        client.get(f"/api/projects/{project_id}/ndt/inspection-feedback/NDT-FB-001", headers=contractor_headers),
        "FORBIDDEN",
    )
    assert_error(
        client.get(f"/api/projects/{project_id}/export-tasks/EXP-RPT-20260625-001", headers=contractor_headers),
        "FORBIDDEN",
    )
    assert_error(
        client.get("/api/exports/EXP-RPT-20260625-001", headers=contractor_headers),
        "FORBIDDEN",
    )
    assert_error(
        client.get("/api/exports/EXP-RPT-20260625-001/download-url", headers=contractor_headers),
        "FORBIDDEN",
    )
    assert_error(
        client.post(
            "/api/exports",
            json={"projectId": project_id, "exportType": "report", "reportId": "RPT-20260625-001"},
            headers=contractor_headers,
        ),
        "FORBIDDEN",
    )
    assert_error(
        client.get(f"/api/projects/{project_id}/archive/evidence-package?nodeId=40", headers=contractor_headers),
        "FORBIDDEN",
    )
    assert_error(
        client.get("/api/admin/config-overview", headers=contractor_headers),
        "FORBIDDEN",
    )
    assert_error(
        client.get("/api/knowledge/sources", headers=contractor_headers),
        "FORBIDDEN",
    )
    assert_error(
        client.get("/api/rules/versions", headers=contractor_headers),
        "FORBIDDEN",
    )

    own_node = assert_ok(client.get(f"/api/projects/{project_id}/nodes/16/package", headers=contractor_headers))
    own_document = assert_ok(client.get(f"/api/projects/{project_id}/documents/DOC-20260625-003", headers=contractor_headers))
    admin_overview = assert_ok(client.get("/api/admin/config-overview", headers=admin_headers))
    me = assert_ok(client.get("/api/auth/me", headers=contractor_headers))
    workbench_projects = assert_ok(client.get("/api/workbench/projects?role=contractor", headers=contractor_headers))
    project_page = assert_ok(client.get("/api/projects", headers=contractor_headers))
    summary = assert_ok(client.get(f"/api/projects/{project_id}/workbench/summary?role=contractor", headers=contractor_headers))
    tree = assert_ok(client.get(f"/api/projects/{project_id}/tree", headers=contractor_headers))
    documents = assert_ok(client.get(f"/api/projects/{project_id}/documents", headers=contractor_headers))
    bindings = assert_ok(client.get(f"/api/projects/{project_id}/documents/bindings", headers=contractor_headers))
    reports = assert_ok(client.get(f"/api/projects/{project_id}/reports", headers=contractor_headers))
    todos = assert_ok(client.get(f"/api/todos?projectId={project_id}", headers=contractor_headers))
    messages = assert_ok(client.get(f"/api/messages?projectId={project_id}", headers=contractor_headers))
    search_results = assert_ok(client.get(f"/api/search?projectId={project_id}&keyword=RT", headers=contractor_headers))
    knowledge_files = assert_ok(client.get(f"/api/knowledge/project-files?projectId={project_id}", headers=contractor_headers))
    knowledge_tasks = assert_ok(client.get("/api/knowledge/tasks", headers=contractor_headers))
    reasoning = assert_ok(client.get(f"/api/reasoning/logs?projectId={project_id}", headers=contractor_headers))
    compare_runs = assert_ok(client.get(f"/api/llm/compare-runs?projectId={project_id}", headers=contractor_headers))
    ndt_summary = assert_ok(client.get(f"/api/projects/{project_id}/ndt/summary", headers=contractor_headers))
    ndt_films = assert_ok(client.get(f"/api/projects/{project_id}/ndt/films", headers=contractor_headers))
    ndt_records = assert_ok(client.get(f"/api/projects/{project_id}/ndt/records", headers=contractor_headers))
    ndt_reports = assert_ok(client.get(f"/api/projects/{project_id}/ndt/reports", headers=contractor_headers))
    ndt_feedback = assert_ok(client.get(f"/api/projects/{project_id}/ndt/inspection-feedback", headers=contractor_headers))
    ndt_visible_records = assert_ok(client.get(f"/api/projects/{project_id}/ndt/records", headers=ndt_headers))
    archive_package = assert_ok(client.get(f"/api/projects/{project_id}/archive/package", headers=contractor_headers))
    owner_reports = assert_ok(client.get(f"/api/projects/{project_id}/owner/reports", headers=owner_headers))

    assert own_node["node"]["nodeId"] == 16
    assert own_document["document"]["id"] == "DOC-20260625-003"
    assert "metrics" in admin_overview
    assert {item["userId"] for item in me["projectAuthorizations"]} == {"USER-CONTRACTOR-001"}
    assert {item["id"] for item in workbench_projects} == {project_id}
    assert {item["id"] for item in project_page["items"]} == {project_id}
    assert not any(item["id"] in {"TODO-SCOPE-40", "TODO-SCOPE-RPT"} for item in summary["todos"])
    visible_node_ids = {node["nodeId"] for group in tree["groups"] for node in group["nodes"]}
    assert visible_node_ids.issubset({16, 24, 25})
    assert "DOC-20260625-004" not in {item["id"] for item in documents["items"]}
    assert "BIND-40-001" not in {item["id"] for item in bindings}
    assert all(set(report.get("nodeIds") or []).issubset({16, 24, 25}) for report in reports)
    assert "TODO-SCOPE-40" not in {item["id"] for item in todos["items"]}
    assert "TODO-SCOPE-RPT" not in {item["id"] for item in todos["items"]}
    assert "MSG-SCOPE-40" not in {item["id"] for item in messages["items"]}
    assert "DOC-20260625-004" not in {item["id"] for item in search_results["items"]}
    assert "KF-DOC-20260625-004" not in {item["id"] for item in knowledge_files["items"]}
    assert "KT-20260626-001" not in {item["id"] for item in knowledge_tasks["items"]}
    assert "AIRUN-SCOPE-40" not in {item["id"] for item in reasoning["items"]}
    assert "CMP-SCOPE-40" not in {item["runId"] for item in compare_runs["items"]}
    assert ndt_summary == {"filmCount": 0, "recordCount": 0, "reportCount": 0, "feedbackCount": 0}
    assert ndt_films["items"] == []
    assert ndt_records["items"] == []
    assert ndt_reports["items"] == []
    assert ndt_feedback["items"] == []
    assert any(item["id"] == "NDT-REC-001" for item in ndt_visible_records["items"])
    assert archive_package["itemCount"] == 2
    assert any(report["id"] == "RPT-20260625-001" for report in owner_reports)


def test_upload_creates_knowledge_task_and_retrieval_works() -> None:
    upload = assert_ok(
        client.post(
            "/projects/P-2026-HDCP-001/documents/upload-session",
            json={"files": [{"fileName": "E2E.pdf", "fileSize": 1024, "fileType": "application/pdf"}]},
        )
    )
    assert upload["uploadUrls"][0]["method"] == "PUT"

    tasks = assert_ok(client.get("/knowledge/tasks"))
    assert any(task["targetName"] == "E2E.pdf" for task in tasks["items"])

    retrieval = assert_ok(
        client.post(
            "/knowledge/retrieval-test",
            json={"question": "焊工资格证有效期如何校验？", "scope": ["standard"], "topK": 5},
        )
    )
    assert retrieval["hits"]


def test_upload_and_ndt_validation_errors_match_contract() -> None:
    project_id = "P-2026-HDCP-001"

    assert_error(
        client.post(
            f"/projects/{project_id}/documents/upload-session",
            json={"files": [{"fileName": "empty.pdf", "fileSize": 0, "fileType": "application/pdf"}]},
        ),
        "VALIDATION_ERROR",
    )
    assert_error(
        client.post(
            f"/projects/{project_id}/documents/upload-session",
            json={"files": [{"fileName": "tool.exe", "fileSize": 1024, "fileType": "application/x-msdownload"}]},
        ),
        "UNSUPPORTED_FILE_TYPE",
    )
    assert_error(
        client.post(
            f"/projects/{project_id}/documents/upload-session",
            json={"files": [{"fileName": "huge.pdf", "fileSize": 500 * 1024 * 1024 + 1, "fileType": "application/pdf"}]},
        ),
        "FILE_TOO_LARGE",
    )

    upload = assert_ok(
        client.post(
            f"/projects/{project_id}/documents/upload-session",
            json={"files": [{"fileName": "match.pdf", "fileSize": 1024, "fileType": "application/pdf"}]},
        )
    )
    assert_error(
        client.post(f"/projects/NOT-A-PROJECT/documents/upload-session/{upload['uploadSessionId']}/complete"),
        "NOT_FOUND",
    )

    assert_error(
        client.post(f"/projects/{project_id}/ndt/films", json={"nodeId": 40, "filmNo": "F-1", "weldNo": "W-1"}),
        "NDT_FILM_REQUIRED",
    )
    assert_error(
        client.post(
            f"/projects/{project_id}/ndt/records/import",
            json={"nodeId": 40, "rows": [{"recordNo": "R-1", "weldNo": "W-1"}]},
        ),
        "NDT_RECORD_REQUIRED",
    )
    assert_error(
        client.post(f"/projects/{project_id}/ndt/reports/upload-session", json={"nodeId": 40, "files": []}),
        "NDT_REPORT_REQUIRED",
    )
    assert_error(
        client.post(
            f"/projects/{project_id}/ndt/reports/upload-session",
            json={"nodeId": 40, "files": [{"fileName": "scan.exe", "fileSize": 1024, "fileType": "application/x-msdownload"}]},
        ),
        "UNSUPPORTED_NDT_FILE_TYPE",
    )
    assert_error(
        client.post(
            f"/projects/{project_id}/ndt/reports/upload-session",
            json={"nodeId": 40, "files": [{"fileName": "scan.dcm", "fileSize": 500 * 1024 * 1024 + 1, "fileType": "application/dicom"}]},
        ),
        "NDT_FILE_TOO_LARGE",
    )
    assert_error(
        client.post(f"/projects/{project_id}/ndt/submissions", json={"nodeId": 40, "reportIds": []}),
        "NDT_REPORT_REQUIRED",
    )
    assert_error(
        client.post(f"/projects/{project_id}/ndt/rectifications", json={"nodeId": 40, "reportIds": ["NDT-RPT-001"]}),
        "NDT_RECTIFICATION_REQUIRED",
    )


def test_cross_node_submission_scope_expands_empty_binding_ids() -> None:
    project_id = "P-2026-HDCP-001"
    draft = assert_ok(
        client.post(
            f"/projects/{project_id}/submissions/drafts",
            json={"nodeIds": [16, 25], "bindingIds": [], "batchName": "scope draft"},
        )
    )
    assert draft["bindingIds"]

    submission = assert_ok(
        client.post(
            f"/projects/{project_id}/submissions",
            json={"nodeIds": [16, 25], "bindingIds": [], "batchName": "scope submit"},
        )
    )
    assert submission["nextStatus"] == "AI 预审中"


def test_ndt_submit_preserves_pending_report_and_rectification_updates_feedback() -> None:
    project_id = "P-2026-HDCP-001"
    submit = assert_ok(
        client.post(
            f"/projects/{project_id}/ndt/submissions",
            json={"nodeId": 40, "reportIds": ["NDT-RPT-001"], "filmIds": ["FILM-RT-001"]},
        )
    )
    assert submit["nextStatus"] == "待审查"

    reports = assert_ok(client.get(f"/projects/{project_id}/ndt/reports"))
    assert any(report["id"] == "NDT-RPT-001" and report["status"] == "待审查" for report in reports["items"])
    assert not any(str(report["reportNo"]).startswith("RT-FOLLOW") for report in reports["items"])

    rectification = assert_ok(
        client.post(
            f"/projects/{project_id}/ndt/rectifications",
            json={"rectificationId": "NDT-FB-001", "description": "已补充底片索引。"},
        )
    )
    assert rectification["rectification"]["status"] == "已反馈"
    feedback = assert_ok(client.get(f"/projects/{project_id}/ndt/inspection-feedback"))
    assert feedback["items"][0]["status"] == "已反馈"


def test_admin_config_diff_export_publish_and_project_members() -> None:
    project_id = "P-2026-HDCP-001"
    create_diff = assert_ok(
        client.post(
            "/admin/config-items/todo-rule",
            json={"target": "todo-rule", "values": {"name": "E2E 待办规则", "triggerStatus": "E2E 待处理"}},
        )
    )
    assert any(row["after"] == "E2E 待办规则" for row in create_diff["diff"]["changed"])

    export = assert_ok(client.post("/admin/config-export", json={"scope": "all"}))
    assert export["task"]["fileName"] == "后台配置包-all-20260626.zip"

    publish = assert_ok(client.post("/admin/config-overview/publish", json={"scope": "all"}))
    assert publish["version"].startswith("config-v")
    assert any("权限矩阵已同步到工作台动作权限" in impact["trace"] for impact in publish["impacts"])

    messages = assert_ok(client.get(f"/messages?projectId={project_id}"))
    todos = assert_ok(client.get(f"/todos?projectId={project_id}"))
    assert any("后台配置已发布：config-v" in item["title"] for item in messages["items"])
    assert any(item["title"] == "字段映射配置发布影响" for item in todos["items"])

    member = assert_ok(
        client.post(
            f"/projects/{project_id}/members",
            json={"userId": "USER-ADMIN-001", "role": "admin", "nodeScope": [16, 24, 40, 59]},
            headers={"X-Role": "admin", "X-User-Id": "USER-ADMIN-001"},
        )
    )
    assert member["member"]["name"] == "系统管理员"
    detail = assert_ok(client.get(f"/projects/{project_id}"))
    assert len(detail["members"]) == 5

    updated_member = assert_ok(
        client.post(
            f"/projects/{project_id}/members",
            json={"userId": "USER-INSPECTION-001", "role": "inspection", "nodeScope": [2, 3, 4]},
            headers={"X-Role": "admin", "X-User-Id": "USER-ADMIN-001"},
        )
    )
    assert updated_member["member"]["id"] == "PM-INSPECTION-001"
    assert {2, 3, 4, 24}.issubset(set(updated_member["member"]["nodeScope"]))
    detail = assert_ok(client.get(f"/projects/{project_id}"))
    assert len(detail["members"]) == 5


def test_admin_project_creation_returns_four_initial_members_and_no_backend_integration_gaps() -> None:
    created = assert_ok(
        client.post(
            "/admin/projects",
            json={
                "code": "P-E2E-001",
                "name": "E2E 立项项目",
                "memberUserIds": {
                    "owner": "USER-OWNER-001",
                    "contractor": "USER-CONTRACTOR-001",
                    "ndt": "USER-NDT-001",
                    "inspection": "USER-INSPECTION-001",
                },
            },
        )
    )
    assert len(created["detail"]["members"]) == 4

    gaps = assert_ok(client.get("/admin/integration-contract?status=后端缺失"))
    assert gaps["fields"] == []
    all_contracts = assert_ok(client.get("/admin/integration-contract"))
    assert all_contracts["summary"]["blockers"] == 0
    assert all_contracts["summary"]["pending"] == 0
    assert all_contracts["summary"]["aligned"] == all_contracts["summary"]["total"]


def test_upload_complete_inline_ocr_writes_fields_and_slice_task(monkeypatch) -> None:
    from apps.worker import tasks

    monkeypatch.setenv("AICHECK_TASK_DISPATCH", "inline")

    def fake_parse(storage_key: str, *, file_name: str | None = None):
        return {
            "storageKey": storage_key,
            "fileName": file_name,
            "status": "success",
            "fragments": [{"pageNo": 1, "text": "证书编号 TS6J-2026-0001", "confidence": 0.91}],
            "fields": [{"fieldName": "证书编号", "fieldValue": "TS6J-2026-0001", "confidence": 0.94}],
            "seals": [],
            "diagnostics": [],
        }

    monkeypatch.setattr(tasks.ocr_service, "parse_document", fake_parse)
    upload = assert_ok(
        client.post(
            "/projects/P-2026-HDCP-001/documents/upload-session",
            json={"files": [{"fileName": "OCR-inline.pdf", "fileSize": 1024, "fileType": "application/pdf"}]},
        )
    )
    created = upload["uploadUrls"][0]
    complete = assert_ok(
        client.post(f"/projects/P-2026-HDCP-001/documents/upload-session/{upload['uploadSessionId']}/complete")
    )

    assert complete["queuedTasks"][0]["mode"] == "inline"
    fields = assert_ok(client.get(f"/projects/P-2026-HDCP-001/documents/{created['documentId']}/ocr-fields"))
    assert any(field["fieldValue"] == "TS6J-2026-0001" for field in fields)

    knowledge_file_id = f"KF-{created['documentId']}"
    slice_task = next(
        item for item in repo.state["knowledge_tasks"] if item["taskType"] == "slice" and item["targetId"] == knowledge_file_id
    )
    assert slice_task["status"] == "排队中"

    sliced = tasks.slice_knowledge.run(knowledge_file_id)
    chunks = assert_ok(client.get(f"/knowledge/files/{knowledge_file_id}/chunks"))
    assert sliced["chunkCount"] == chunks["total"]
    assert chunks["items"][0]["text"].startswith("证书编号")


def test_document_preview_and_download_use_current_version_signed_get(monkeypatch) -> None:
    captured: list[tuple[str, str | None]] = []

    def fake_presigned_get(url: str, *, file_name: str | None = None):
        captured.append((url, file_name))
        return f"https://minio.local/{url.removeprefix('minio://')}"

    monkeypatch.setattr("libs.db.repository.object_storage.presigned_get_url", fake_presigned_get)
    document, version = repo.create_document("P-2026-HDCP-001", "field-report.pdf", "application/pdf")

    preview = assert_ok(client.get(f"/projects/P-2026-HDCP-001/documents/{document['id']}/preview-url"))
    download = assert_ok(client.get(f"/projects/P-2026-HDCP-001/documents/{document['id']}/download-url"))
    detail = assert_ok(client.get(f"/projects/P-2026-HDCP-001/documents/{document['id']}"))

    expected_storage_url = f"minio://documents/{version['storageKey']}"
    assert preview["url"].startswith("https://minio.local/documents/")
    assert download["url"].startswith("https://minio.local/documents/")
    assert detail["preview"]["url"] == preview["url"]
    assert detail["download"]["url"] == download["url"]
    assert preview["previewType"] == "pdf"
    assert preview["contentType"] == "application/pdf"
    assert download["contentType"] == "application/pdf"
    assert (expected_storage_url, "field-report.pdf") in captured
    assert "mock://" not in preview["url"]
    assert "mock://" not in download["url"]
    assert_error(client.get(f"/projects/NOT-A-PROJECT/documents/{document['id']}/download-url"), "NOT_FOUND")


def test_worker_uses_ocr_http_client_when_configured(monkeypatch) -> None:
    from apps.worker import tasks

    class FakeOcrClient:
        enabled = True

        def parse_sync(self, storage_key: str, *, file_name: str | None = None):
            return {
                "storageKey": storage_key,
                "fileName": file_name,
                "status": "success",
                "fragments": [{"pageNo": 1, "text": "HTTP OCR 证书编号 TS-HTTP", "confidence": 0.93}],
                "fields": [{"fieldName": "证书编号", "fieldValue": "TS-HTTP", "confidence": 0.95}],
                "seals": [],
                "diagnostics": [],
            }

    monkeypatch.setattr(tasks, "OcrClient", lambda: FakeOcrClient())
    doc, version = repo.create_document("P-2026-HDCP-001", "HTTP-OCR.pdf", "pdf")
    result = tasks.parse_document.run(doc["id"], version["id"], version["storageKey"], doc["fileName"])

    assert result["applied"]["status"] == "success"
    fields = assert_ok(client.get(f"/projects/P-2026-HDCP-001/documents/{doc['id']}/ocr-fields"))
    assert any(field["fieldValue"] == "TS-HTTP" for field in fields)


def test_failed_knowledge_task_retry_dispatches_worker_and_is_idempotent(monkeypatch) -> None:
    from apps.worker import tasks

    monkeypatch.setenv("AICHECK_TASK_DISPATCH", "inline")
    monkeypatch.delenv("AICHECK_OCR_BASE_URL", raising=False)

    def fake_parse(storage_key: str, *, file_name: str | None = None):
        return {
            "storageKey": storage_key,
            "fileName": file_name,
            "status": "success",
            "fragments": [{"pageNo": 1, "text": "炉批号 H240315A07", "confidence": 0.92}],
            "fields": [{"fieldName": "炉批号", "fieldValue": "H240315A07", "confidence": 0.92}],
            "seals": [],
            "diagnostics": [],
        }

    monkeypatch.setattr(tasks.ocr_service, "parse_document", fake_parse)

    first = assert_ok(
        client.post(
            "/knowledge/tasks/KT-20260626-002/retry",
            headers={"Idempotency-Key": "retry-ocr-once"},
        )
    )
    second = assert_ok(
        client.post(
            "/knowledge/tasks/KT-20260626-002/retry",
            headers={"Idempotency-Key": "retry-ocr-once"},
        )
    )
    task = repo.find_one("knowledge_tasks", "KT-20260626-002")

    assert first["dispatches"][0]["mode"] == "inline"
    assert second["task"]["attempts"] == first["task"]["attempts"]
    assert task["attempts"] == 1
    assert task["status"] == "成功"
    assert task["progress"] == 100
    assert task["lastDispatch"]["mode"] == "inline"
    logs = assert_ok(client.get("/knowledge/tasks/KT-20260626-002/logs"))
    assert any("重试已投递" in item["message"] for item in logs)
    assert any("OCR 任务完成" in item["message"] for item in logs)


def test_cancelled_knowledge_task_is_not_processed_by_worker() -> None:
    from apps.worker import tasks

    cancelled = assert_ok(client.post("/knowledge/tasks/KT-20260626-001/cancel"))
    assert cancelled["task"]["status"] == "已取消"

    result = tasks.embed_knowledge.run("KF-DOC-20260625-004")
    task = repo.find_one("knowledge_tasks", "KT-20260626-001")

    assert result["status"] == "canceled"
    assert task["status"] == "已取消"
    logs = assert_ok(client.get("/knowledge/tasks/KT-20260626-001/logs"))
    assert any("任务已取消" in item["message"] for item in logs)


def test_ocr_service_reports_missing_source_before_running_pipeline() -> None:
    from apps.ocr_service.service import OcrService

    service = OcrService()
    service.pipeline = lambda source_path: {"text": f"unexpected {source_path}"}

    result = service.parse_document("missing-object.pdf", file_name="missing-object.pdf")

    assert result["status"] == "failed"
    assert "OCR source file is unavailable" in result["diagnostics"][0]


def test_worker_records_ocr_client_failure_without_leaking_provider_details(monkeypatch) -> None:
    from apps.worker import tasks

    class FailingOcrClient:
        enabled = True

        def parse_sync(self, storage_key: str, *, file_name: str | None = None):
            raise RuntimeError("provider failed with sk-secret-ocr")

    monkeypatch.setattr(tasks, "OcrClient", lambda: FailingOcrClient())
    doc, version = repo.create_document("P-2026-HDCP-001", "OCR-fail.pdf", "pdf")

    result = tasks.parse_document.run(doc["id"], version["id"], version["storageKey"], doc["fileName"])
    task = repo.ocr_task_for(doc["id"], version["id"], doc["fileName"])

    assert result["status"] == "failed"
    assert result["applied"]["status"] == "failed"
    assert task["status"] == "失败"
    assert "OCR 服务 调用失败" in task["errorMessage"]
    assert "sk-secret-ocr" not in task["errorMessage"]


def test_missing_knowledge_file_workers_mark_tasks_failed() -> None:
    from apps.worker import tasks

    slice_task = {
        "id": "KT-MISSING-SLICE",
        "taskType": "slice",
        "targetType": "file",
        "targetId": "KF-MISSING",
        "targetName": "missing.pdf",
        "status": "排队中",
        "progress": 0,
        "createdAt": "2026-06-27 00:00:00",
    }
    vector_task = {
        "id": "KT-MISSING-VECTOR",
        "taskType": "vector",
        "targetType": "file",
        "targetId": "KF-MISSING",
        "targetName": "missing.pdf",
        "status": "排队中",
        "progress": 0,
        "createdAt": "2026-06-27 00:00:00",
    }
    repo.state["knowledge_tasks"].extend([slice_task, vector_task])

    sliced = tasks.slice_knowledge.run("KF-MISSING")
    embedded = tasks.embed_knowledge.run("KF-MISSING")

    assert sliced["status"] == "missing"
    assert embedded["status"] == "missing"
    assert slice_task["status"] == "失败"
    assert vector_task["status"] == "失败"
    assert "找不到关联知识文件" in slice_task["errorMessage"]
    assert "找不到关联知识文件" in vector_task["errorMessage"]


def test_litellm_failure_maps_to_ai_run_failed(monkeypatch) -> None:
    from apps.worker import tasks

    run = assert_ok(client.post("/projects/P-2026-HDCP-001/inspection/nodes/24/ai-recheck"))

    class FailingLiteLLM:
        def chat_sync(self, *args, **kwargs):
            raise RuntimeError("provider unavailable sk-secret-litellm")

    monkeypatch.setattr(tasks, "LiteLLMClient", FailingLiteLLM)
    result = tasks.ai_recheck.run("P-2026-HDCP-001", 24, run["runId"])
    stored = repo.find_one("ai_runs", run["runId"])

    assert result["status"] == "失败"
    assert stored["status"] == "失败"
    assert stored["errorCode"] == "AI_RUN_FAILED"
    assert "LiteLLM AI 复核 调用失败" in stored["errorMessage"]
    assert "sk-secret-litellm" not in stored["errorMessage"]


def test_embed_and_compare_failures_do_not_leak_provider_details(monkeypatch) -> None:
    from apps.worker import tasks

    class FailingLiteLLM:
        def chat_sync(self, *args, **kwargs):
            raise RuntimeError("chat failed sk-secret-chat")

        def embed_sync(self, *args, **kwargs):
            raise RuntimeError("embed failed sk-secret-embed")

    repo.state.setdefault("knowledge_chunks", []).append(
        {
            "id": "CHK-FAIL-1",
            "fileId": "KF-DOC-20260625-004",
            "documentId": "DOC-20260625-004",
            "documentVersionId": "DV-20260625-004-V1",
            "chunkNo": 1,
            "text": "待向量化文本",
            "pageNo": 1,
            "tokenCount": 6,
            "createdAt": "2026-06-27 00:00:00",
        }
    )
    monkeypatch.setattr(tasks, "LiteLLMClient", FailingLiteLLM)

    embedded = tasks.embed_knowledge.run("KF-DOC-20260625-004")
    vector_task = repo.find_one("knowledge_tasks", "KT-20260626-001")
    compare = assert_ok(
        client.post(
            "/llm/compare",
            json={"question": "材料证明是否一致？", "modelCodes": ["default-chat", "compare-fast"]},
        )
    )
    compared = tasks.llm_compare.run(compare["runId"])
    compare_run = repo.find_one("llm_compare_runs", compare["runId"], id_field="runId")

    assert embedded["status"] == "failed"
    assert vector_task["status"] == "失败"
    assert "EXTERNAL_TOOL_FAILED" in vector_task["errorMessage"]
    assert "sk-secret-embed" not in vector_task["errorMessage"]
    assert compared["status"] == "失败"
    assert compare_run["errorCode"] == "EXTERNAL_TOOL_FAILED"
    assert "LiteLLM 模型对比 调用失败" in compare_run["errorMessage"]
    assert "sk-secret-chat" not in compare_run["errorMessage"]


def test_llm_compare_dispatches_to_worker_inline(monkeypatch) -> None:
    from apps.worker import tasks

    monkeypatch.setenv("AICHECK_TASK_DISPATCH", "inline")

    class FakeLiteLLM:
        def chat_sync(self, *args, **kwargs):
            return {"choices": [{"message": {"content": f"{kwargs.get('model')} 完成对比"}}]}

        @staticmethod
        def first_message_text(response):
            return response["choices"][0]["message"]["content"]

    monkeypatch.setattr(tasks, "LiteLLMClient", FakeLiteLLM)
    compare = assert_ok(
        client.post(
            "/llm/compare",
            json={"question": "材料证明是否一致？", "modelCodes": ["default-chat", "compare-fast"]},
        )
    )
    stored = repo.find_one("llm_compare_runs", compare["runId"], id_field="runId")

    assert compare["dispatch"]["mode"] == "inline"
    assert stored["status"] == "完成"
    assert len(stored["results"]) == 2


def test_completed_ocr_worker_is_idempotent(monkeypatch) -> None:
    from apps.worker import tasks

    calls = {"ocr": 0}

    def fake_parse(storage_key: str, *, file_name: str | None = None):
        calls["ocr"] += 1
        return {
            "storageKey": storage_key,
            "fileName": file_name,
            "status": "success",
            "fragments": [{"pageNo": 1, "text": "证书编号 OCR-IDEMPOTENT", "confidence": 0.94}],
            "fields": [{"fieldName": "证书编号", "fieldValue": "OCR-IDEMPOTENT", "confidence": 0.94}],
            "seals": [],
            "diagnostics": [],
        }

    monkeypatch.setattr(tasks.ocr_service, "parse_document", fake_parse)
    doc, version = repo.create_document("P-2026-HDCP-001", "OCR-idempotent.pdf", "application/pdf")

    first = tasks.parse_document.run(doc["id"], version["id"], version["storageKey"], doc["fileName"])
    task = repo.ocr_task_for(doc["id"], version["id"], doc["fileName"])
    logs_after_first = list(task.get("logs", []))
    field_count_after_first = len(
        [item for item in repo.state["extracted_fields"] if item.get("documentVersionId") == version["id"]]
    )
    second = tasks.parse_document.run(doc["id"], version["id"], version["storageKey"], doc["fileName"])

    assert first["applied"]["status"] == "success"
    assert second["alreadyCompleted"] is True
    assert calls["ocr"] == 1
    assert task.get("logs") == logs_after_first
    assert len([item for item in repo.state["extracted_fields"] if item.get("documentVersionId") == version["id"]]) == field_count_after_first


def test_completed_slice_and_embed_workers_are_idempotent(monkeypatch) -> None:
    from apps.worker import tasks

    def fake_parse(storage_key: str, *, file_name: str | None = None):
        return {
            "storageKey": storage_key,
            "fileName": file_name,
            "status": "success",
            "fragments": [{"pageNo": 1, "text": "炉批号 SLICE-EMBED-IDEMPOTENT", "confidence": 0.92}],
            "fields": [{"fieldName": "炉批号", "fieldValue": "SLICE-EMBED-IDEMPOTENT", "confidence": 0.92}],
            "seals": [],
            "diagnostics": [],
        }

    class FakeLiteLLM:
        calls = 0

        def embed_sync(self, *args, **kwargs):
            FakeLiteLLM.calls += 1
            return {"data": [{"embedding": [0.1, 0.2, 0.3]}]}

    monkeypatch.setattr(tasks.ocr_service, "parse_document", fake_parse)
    monkeypatch.setattr(tasks, "LiteLLMClient", FakeLiteLLM)
    doc, version = repo.create_document("P-2026-HDCP-001", "slice-embed-idempotent.pdf", "application/pdf")
    tasks.parse_document.run(doc["id"], version["id"], version["storageKey"], doc["fileName"])
    file_id = f"KF-{doc['id']}"

    first_slice = tasks.slice_knowledge.run(file_id)
    slice_task = next(item for item in repo.state["knowledge_tasks"] if item["taskType"] == "slice" and item["targetId"] == file_id)
    slice_logs_after_first = list(slice_task.get("logs", []))
    chunk_count_after_first = len([item for item in repo.state["knowledge_chunks"] if item.get("fileId") == file_id])
    second_slice = tasks.slice_knowledge.run(file_id)

    first_embed = tasks.embed_knowledge.run(file_id)
    vector_task = next(item for item in repo.state["knowledge_tasks"] if item["taskType"] == "vector" and item["targetId"] == file_id)
    vector_logs_after_first = list(vector_task.get("logs", []))
    second_embed = tasks.embed_knowledge.run(file_id)

    assert first_slice["status"] == "success"
    assert second_slice["alreadyCompleted"] is True
    assert slice_task.get("logs") == slice_logs_after_first
    assert len([item for item in repo.state["knowledge_chunks"] if item.get("fileId") == file_id]) == chunk_count_after_first
    assert first_embed["status"] == "success"
    assert second_embed["alreadyCompleted"] is True
    assert FakeLiteLLM.calls == 1
    assert vector_task.get("logs") == vector_logs_after_first


def test_completed_ai_and_compare_workers_are_idempotent(monkeypatch) -> None:
    from apps.worker import tasks

    class FakeLiteLLM:
        chat_calls = 0

        def chat_sync(self, *args, **kwargs):
            FakeLiteLLM.chat_calls += 1
            return {"choices": [{"message": {"content": f"{kwargs.get('model')} completed"}}]}

        @staticmethod
        def first_message_text(response):
            return response["choices"][0]["message"]["content"]

    monkeypatch.setattr(tasks, "LiteLLMClient", FakeLiteLLM)

    ai_run = assert_ok(client.post("/projects/P-2026-HDCP-001/inspection/nodes/24/ai-recheck"))
    first_ai = tasks.ai_recheck.run("P-2026-HDCP-001", 24, ai_run["runId"])
    second_ai = tasks.ai_recheck.run("P-2026-HDCP-001", 24, ai_run["runId"])

    compare = assert_ok(
        client.post(
            "/llm/compare",
            json={"question": "材料证明是否一致？", "modelCodes": ["default-chat", "compare-fast"]},
        )
    )
    first_compare = tasks.llm_compare.run(compare["runId"])
    calls_after_first_compare = FakeLiteLLM.chat_calls
    second_compare = tasks.llm_compare.run(compare["runId"])

    assert first_ai["status"] == "完成"
    assert second_ai["alreadyCompleted"] is True
    assert first_compare["status"] == "完成"
    assert second_compare["alreadyCompleted"] is True
    assert calls_after_first_compare == 3
    assert FakeLiteLLM.chat_calls == calls_after_first_compare


def test_completed_export_worker_is_idempotent(monkeypatch) -> None:
    from apps.worker import tasks

    stored: list[tuple[str, str, int]] = []

    def fake_put(bucket: str, object_name: str, data: bytes, *, content_type: str):
        stored.append((bucket, object_name, len(data)))
        return f"minio://{bucket}/{object_name}"

    monkeypatch.setattr("libs.db.repository.object_storage.put_bytes", fake_put)
    task = {
        "id": "EXP-IDEMPOTENT-001",
        "projectId": "P-2026-HDCP-001",
        "nodeIds": [24],
        "exportType": "config-package",
        "status": "排队中",
        "progress": 0,
        "fileName": "idempotent-export.zip",
        "fileSize": 0,
        "createdAt": "2026-06-27 00:00:00",
    }
    repo.state["export_tasks"].insert(0, task)

    first = tasks.export_package.run(task["id"])
    logs_after_first = list(task.get("logs", []))
    second = tasks.export_package.run(task["id"])

    assert first["status"] == "可下载"
    assert second["alreadyCompleted"] is True
    assert len(stored) == 1
    assert stored[0][0] == "exports"
    assert task.get("logs") == logs_after_first


def test_export_artifact_uses_object_storage_when_available(monkeypatch) -> None:
    stored = {}
    monkeypatch.setenv("AICHECK_TASK_DISPATCH", "inline")

    def fake_put(bucket: str, object_name: str, data: bytes, *, content_type: str):
        stored["bucket"] = bucket
        stored["objectName"] = object_name
        stored["contentType"] = content_type
        stored["size"] = len(data)
        stored["data"] = data
        return f"minio://{bucket}/{object_name}"

    def fake_get(url: str, *, file_name: str | None = None):
        return f"https://minio.local/{url.removeprefix('minio://')}"

    monkeypatch.setattr("libs.db.repository.object_storage.put_bytes", fake_put)
    monkeypatch.setattr("libs.db.repository.object_storage.presigned_get_url", fake_get)

    export = assert_ok(client.post("/exports", json={"projectId": "P-2026-HDCP-001", "fileName": "contract.zip"}))
    signed = assert_ok(client.get(f"/exports/{export['exportId']}/download-url"))

    assert export["task"]["downloadUrl"].startswith("minio://exports/")
    assert stored["bucket"] == "exports"
    assert stored["contentType"] == "application/zip"
    assert stored["size"] > 0
    assert signed["url"].startswith("https://minio.local/exports/")
    with zipfile.ZipFile(io.BytesIO(stored["data"])) as archive:
        names = set(archive.namelist())
        assert {"manifest.json", "task.json", "documents.json", "evidence_links.json", "README.txt"}.issubset(names)
        manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
        assert manifest["schemaVersion"] == "aicheck-export-v1"
        assert manifest["taskId"] == export["exportId"]
        assert manifest["projectId"] == "P-2026-HDCP-001"
        assert manifest["counts"]["documents"] >= 1
    task = repo.find_one("export_tasks", export["exportId"])
    assert task is not None
    assert [entry["message"] for entry in task["logs"]] == ["导出 worker 开始处理。", "导出任务完成。"]

    report_export = assert_ok(
        client.post(
            "/projects/P-2026-HDCP-001/reports/RPT-20260625-001/export",
            json={"format": "pdf"},
        )
    )
    assert report_export["exportId"].startswith("EXP-RPT-")
    assert stored["contentType"] == "application/pdf"
    assert stored["data"].startswith(b"%PDF-1.4")
    assert b"AIcheck Export Report" in stored["data"]


def test_archive_and_evidence_packages_write_queryable_audit_artifacts(monkeypatch) -> None:
    stored: dict[str, bytes | str | int] = {}

    def fake_put(bucket: str, object_name: str, data: bytes, *, content_type: str):
        stored[object_name] = data
        return f"minio://{bucket}/{object_name}"

    monkeypatch.setattr("libs.db.repository.object_storage.put_bytes", fake_put)

    archive = assert_ok(client.get("/projects/P-2026-HDCP-001/archive/package"))
    evidence = assert_ok(client.get("/projects/P-2026-HDCP-001/archive/evidence-package?nodeId=24"))
    archive_task = repo.find_one("export_tasks", archive["exportId"])
    evidence_task = repo.find_one("export_tasks", evidence["exportId"])

    assert archive_task["status"] == "可下载"
    assert archive_task["progress"] == 100
    assert archive_task["storageKey"] in stored
    assert evidence_task["status"] == "可下载"
    assert evidence_task["storageKey"] in stored
    with zipfile.ZipFile(io.BytesIO(stored[archive_task["storageKey"]])) as archive_zip:
        manifest = json.loads(archive_zip.read("manifest.json").decode("utf-8"))
        assert manifest["exportType"] == "archive-package"
        assert manifest["counts"]["archiveItems"] >= 1
    with zipfile.ZipFile(io.BytesIO(stored[evidence_task["storageKey"]])) as evidence_zip:
        manifest = json.loads(evidence_zip.read("manifest.json").decode("utf-8"))
        assert manifest["exportType"] == "evidence-package"
        assert manifest["counts"]["evidenceLinks"] >= 1


class FakeCursor:
    def __init__(self, docs):
        self.docs = docs

    async def to_list(self, length=None):
        return [dict(item) for item in self.docs]


class FakeCollection:
    def __init__(self):
        self.docs = []
        self.session_calls = 0

    async def count_documents(self, query):
        return len(self.docs)

    async def delete_many(self, query, session=None):
        if session is not None:
            self.session_calls += 1
        self.docs.clear()

    async def insert_many(self, docs, session=None):
        if session is not None:
            self.session_calls += 1
        self.docs.extend([dict(item) for item in docs])

    def find(self, query):
        return FakeCursor(self.docs)

    async def find_one(self, query):
        for doc in self.docs:
            if all(doc.get(key) == value for key, value in query.items()):
                return dict(doc)
        return None

    async def replace_one(self, query, replacement, upsert=False, session=None):
        if session is not None:
            self.session_calls += 1
        for index, doc in enumerate(self.docs):
            if all(doc.get(key) == value for key, value in query.items()):
                self.docs[index] = dict(replacement)
                return
        if upsert:
            self.docs.append(dict(replacement))


class FakeTransaction:
    def __init__(self, client):
        self.client = client

    async def __aenter__(self):
        self.client.transactions_started += 1
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self.client.transactions_closed += 1
        return False


class FakeSession:
    def __init__(self, client):
        self.client = client

    async def __aenter__(self):
        self.client.sessions_started += 1
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self.client.sessions_closed += 1
        return False

    def start_transaction(self):
        return FakeTransaction(self.client)


class FakeClient:
    def __init__(self):
        self.sessions_started = 0
        self.sessions_closed = 0
        self.transactions_started = 0
        self.transactions_closed = 0

    async def start_session(self):
        return FakeSession(self)


class FakeDatabase(dict):
    def __init__(self, *, with_client: bool = False):
        super().__init__()
        if with_client:
            self.client = FakeClient()

    def __getitem__(self, key):
        if key not in self:
            self[key] = FakeCollection()
        return dict.__getitem__(self, key)


class FakeIndexCollection:
    def __init__(self):
        self.indexes = []

    async def create_index(self, keys, **kwargs):
        self.indexes.append((list(keys), dict(kwargs)))


class FakeIndexDatabase(dict):
    def __getitem__(self, key):
        if key not in self:
            self[key] = FakeIndexCollection()
        return dict.__getitem__(self, key)


async def test_mongo_indexes_include_compound_and_unique_specs() -> None:
    database = FakeIndexDatabase()

    await ensure_mongo_indexes(database)

    assert ([("projectId", 1), ("nodeId", 1), ("status", 1)], {}) in database["project_nodes"].indexes
    assert ([("projectId", 1), ("userId", 1), ("role", 1)], {"unique": True}) in database["project_members"].indexes
    assert ([("documentVersionId", 1), ("fieldName", 1)], {}) in database["extracted_fields"].indexes
    assert ([("sourceType", 1), ("status", 1), ("updatedAt", -1)], {}) in database["knowledge_sources"].indexes
    assert ([("_singleton", 1)], {"unique": True}) in database["knowledge_configs"].indexes
    assert ([("objectType", 1), ("objectId", 1), ("createdAt", -1)], {}) in database["audit_logs"].indexes
    assert ([("scope", 1)], {"unique": True}) in database["idempotency_keys"].indexes
    assert ([("username", 1)], {"unique": True}) in database["users"].indexes


def test_mongo_indexes_cover_all_persisted_collections() -> None:
    persisted_collections = set(STATE_COLLECTIONS.values()) | set(SINGLETON_COLLECTIONS.values()) | {IDEMPOTENCY_COLLECTION}

    assert persisted_collections - set(MONGO_INDEXES) == set()


async def test_mongo_state_round_trip_persists_planned_collections() -> None:
    database = FakeDatabase()
    repo.state["projects"][0]["name"] = "Mongo round trip"
    await repo.flush_to_mongo(database)

    repo.reset()
    await repo.load_from_mongo(database)

    assert repo.require_project("P-2026-HDCP-001")["name"] == "Mongo round trip"
    assert database["project_nodes"].docs
    assert database["document_versions"].docs
    assert database["node_bindings"].docs
    assert database["admin_configs"].docs[0]["_singleton"] == "admin_config"


async def test_mongo_flush_uses_transaction_when_enabled(monkeypatch) -> None:
    monkeypatch.setenv("AICHECK_MONGO_TRANSACTIONS", "true")
    database = FakeDatabase(with_client=True)

    await repo.flush_to_mongo(database)

    assert database.client.sessions_started == 1
    assert database.client.sessions_closed == 1
    assert database.client.transactions_started == 1
    assert database.client.transactions_closed == 1
    assert database["projects"].session_calls > 0
    assert database["admin_configs"].session_calls > 0


async def test_mongo_transaction_probe_reports_skipped_without_mongo(monkeypatch) -> None:
    monkeypatch.setenv("AICHECK_MONGO_TRANSACTIONS", "true")

    result = await run_transaction_probe(None)

    assert result["mongoEnabled"] is False
    assert result["transactionsConfigured"] is True
    assert result["transactionProbe"] == "skipped"
    assert result["reason"] == "mongo_not_configured"


async def test_mongo_transaction_probe_runs_session_transaction(monkeypatch) -> None:
    monkeypatch.setenv("AICHECK_MONGO_TRANSACTIONS", "true")
    database = FakeDatabase(with_client=True)

    result = await run_transaction_probe(database)

    assert result["mongoEnabled"] is True
    assert result["transactionsConfigured"] is True
    assert result["transactionProbe"] == "pass"
    assert database.client.sessions_started == 1
    assert database.client.sessions_closed == 1
    assert database.client.transactions_started == 1
    assert database.client.transactions_closed == 1
    assert database["_deployment_probes"].session_calls == 2
