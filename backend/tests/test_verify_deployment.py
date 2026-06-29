from __future__ import annotations

import json
from argparse import Namespace

import httpx
import pytest

from scripts.verify_deployment import (
    DeploymentVerifier,
    VerifyConfig,
    config_from_args,
    deployment_probe_pdf,
    print_results,
    role_login_password,
)


probe_state = {
    "fileName": "deployment-verify-test.pdf",
    "signedPut": "",
    "signedGets": [],
    "reviewRunId": "RRUN-VERIFY",
    "replayReviewRunId": "RRUN-REPLAY-VERIFY",
}
UPLOADED_STORAGE_KEY = "documents/P-2026-HDCP-001/DV-VERIFY-V1"


def envelope(data=None, *, code: int = 0, reason: str | None = None):
    payload = {
        "code": code,
        "data": data if reason is None else {"reason": reason},
        "operationId": "OP-TEST",
        "serverTime": "2026-06-27 00:00:00",
    }
    return httpx.Response(200, json=payload)


def api_transport(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path == "/api/healthz":
        return envelope(
            {
                "service": "api-service",
                "authRequired": True,
                "demoUsersEnabled": False,
                "mongoEnabled": True,
                "mongoTransactions": True,
                "objectStorageEnabled": True,
            }
        )
    if path == "/api/auth/me":
        auth = request.headers.get("authorization", "")
        if not auth:
            return envelope(code=401, reason="AUTH_REQUIRED")
        role = auth.rsplit("-", 1)[-1]
        return envelope({"username": role, "defaultRole": role})
    if path == "/api/auth/login":
        role = json.loads(request.read().decode("utf-8"))["username"]
        default_path = "/admin/overview" if role == "admin" else "/fde/dashboard" if role == "fde" else f"/workbench/{role}"
        return envelope(
            {
                "token": f"token-{role}",
                "user": {"username": role, "role": role, "defaultPath": default_path},
            }
        )
    if path == "/api/system/mongo-transaction-probe":
        return envelope({"mongoEnabled": True, "transactionsConfigured": True, "transactionProbe": "pass"})
    if path == "/api/workbench/projects":
        return envelope({"items": [], "total": 0})
    if path == "/api/knowledge/tasks":
        return envelope({"items": [{"id": "KT-VERIFY", "targetName": probe_state["fileName"]}], "total": 1})
    if path.endswith("/documents/upload-session"):
        body = json.loads(request.read().decode("utf-8"))
        probe_state["fileName"] = body["files"][0]["fileName"]
        return envelope(
            {
                "uploadSessionId": "UPS-VERIFY",
                "uploadUrls": [
                    {
                        "fileName": probe_state["fileName"],
                        "documentId": "DOC-VERIFY",
                        "documentVersionId": "DV-VERIFY-V1",
                        "url": "http://storage/upload/UPS-VERIFY/DOC-VERIFY",
                        "method": "PUT",
                        "headers": {"Content-Type": "application/pdf"},
                    }
                ],
            }
        )
    if path.endswith("/documents/upload-session/UPS-VERIFY/complete"):
        return envelope({"fileCount": 1, "queuedTasks": [{"mode": "celery", "taskId": "celery-verify"}]})
    if path.endswith("/documents/DOC-VERIFY/preview-url"):
        return envelope(
            {
                "url": "http://storage/download/DOC-VERIFY/preview",
                "method": "GET",
                "expiresAt": "2026-06-27 00:30:00",
                "fileName": probe_state["fileName"],
                "contentType": "application/pdf",
                "previewType": "pdf",
                "readonly": True,
            }
        )
    if path.endswith("/documents/DOC-VERIFY/download-url"):
        return envelope(
            {
                "url": "http://storage/download/DOC-VERIFY/download",
                "method": "GET",
                "expiresAt": "2026-06-27 00:30:00",
                "fileName": probe_state["fileName"],
                "contentType": "application/pdf",
            }
        )
    if path.endswith("/documents/DOC-VERIFY"):
        return envelope(
            {
                "document": {"id": "DOC-VERIFY", "fileName": probe_state["fileName"], "projectId": "P-2026-HDCP-001"},
                "currentVersion": {
                    "id": "DV-VERIFY-V1",
                    "documentId": "DOC-VERIFY",
                    "storageBucket": "documents",
                    "storageKey": UPLOADED_STORAGE_KEY,
                    "isCurrent": True,
                },
                "versions": [],
                "bindings": [],
                "extractedFields": [],
                "evidenceLinks": [],
            }
        )
    if path == "/api/exports" and request.method == "POST":
        assert request.headers.get("authorization") == "Bearer token-admin"
        return envelope({"exportId": "EXP-VERIFY", "task": {"id": "EXP-VERIFY", "status": "排队中", "progress": 0}})
    if path == "/api/exports/EXP-VERIFY":
        return envelope({"task": {"id": "EXP-VERIFY", "status": "排队中", "progress": 0}})
    if path == "/api/admin/config-overview":
        auth = request.headers.get("authorization", "")
        if auth.endswith("token-admin"):
            return envelope({"metrics": []})
        return envelope(code=403, reason="FORBIDDEN")
    if path in {"/api/knowledge/sources", "/api/rules/versions"}:
        return envelope(code=403, reason="FORBIDDEN")
    if path in {"/api/search", "/api/knowledge/project-files"}:
        return envelope({"items": [], "total": 0})
    if path.endswith("/nodes/40/package"):
        return envelope(code=403, reason="FORBIDDEN")
    if path.endswith("/workbench/context"):
        return envelope(code=403, reason="FORBIDDEN")
    if path.endswith("/documents/DOC-20260625-004"):
        return envelope(code=403, reason="FORBIDDEN")
    if path == "/api/knowledge/files/KF-DOC-20260625-004":
        return envelope(code=403, reason="FORBIDDEN")
    if path.endswith("/inspection/nodes/24/ai-recheck"):
        auth = request.headers.get("authorization", "")
        if auth == "Bearer token-inspection":
            review_run_id = probe_state["reviewRunId"]
            return envelope(
                {
                    "runId": "AIRUN-VERIFY",
                    "status": "推理中",
                    "latestRun": {
                        "id": "AIRUN-VERIFY",
                        "reviewRunId": review_run_id,
                        "workflowId": f"review-run-{review_run_id}",
                        "workflowEngine": "temporal",
                        "graphEngine": "langgraph",
                        "modelGateway": "litellm",
                    },
                    "dispatch": {
                        "mode": "temporal",
                        "status": "started",
                        "reviewRunId": review_run_id,
                        "workflowId": f"review-run-{review_run_id}",
                        "temporalRunId": "temporal-run-verify",
                        "taskQueue": "review.workflow",
                    },
                }
            )
        return envelope(code=403, reason="FORBIDDEN")
    if path == "/api/review-runs/RRUN-VERIFY":
        return envelope(
            {
                "run": {
                    "reviewRunId": "RRUN-VERIFY",
                    "aiRunId": "AIRUN-VERIFY",
                    "projectId": "P-2026-HDCP-001",
                    "nodeId": 24,
                    "status": "waiting_human_review",
                    "workflowEngine": "temporal",
                    "workflowType": "ReviewRunWorkflow",
                    "workflowId": "review-run-RRUN-VERIFY",
                    "graphEngine": "langgraph",
                    "modelGateway": "litellm",
                    "modelAlias": "review-chat",
                    "graphSummary": {"total": 3, "statusCounts": {"succeeded": 3}},
                }
            }
        )
    if path == "/api/review-runs/RRUN-VERIFY/graph":
        return envelope(
            {
                "reviewRunId": "RRUN-VERIFY",
                "nodes": [
                    {"nodeKey": "load_context", "status": "succeeded"},
                    {"nodeKey": "run_rule_engine", "status": "succeeded"},
                    {"nodeKey": "quality_gate", "status": "succeeded"},
                ],
                "edges": [
                    {"source": "load_context", "target": "run_rule_engine"},
                    {"source": "run_rule_engine", "target": "quality_gate"},
                ],
                "timeline": [{"eventType": "review_run.created", "status": "queued"}],
            }
        )
    if path == "/api/review-runs/RRUN-VERIFY/timeline":
        return envelope(
            {
                "reviewRunId": "RRUN-VERIFY",
                "events": [{"eventType": "review_run.created", "status": "queued"}],
            }
        )
    if path == "/api/review-runs/RRUN-VERIFY/human-decision":
        return envelope(
            {
                "reviewRun": {"reviewRunId": "RRUN-VERIFY", "status": "accepted_by_human"},
                "temporalSignal": {
                    "status": "sent",
                    "workflowId": "review-run-RRUN-VERIFY",
                    "signalName": "submit_human_decision",
                },
                "auditLogId": "AUD-VERIFY",
            }
        )
    if path == "/api/fde/review-runs/RRUN-VERIFY":
        assert request.headers.get("authorization") == "Bearer token-fde"
        return envelope(
            {
                "run": {
                    "reviewRunId": "RRUN-VERIFY",
                    "workflowEngine": "temporal",
                    "graphEngine": "langgraph",
                    "modelGateway": "litellm",
                },
                "graph": {
                    "nodes": [{"nodeKey": "load_context", "status": "succeeded"}],
                    "edges": [],
                    "timeline": [{"eventType": "review_run.created", "status": "queued"}],
                },
                "timeline": [{"eventType": "review_run.created", "status": "queued"}],
                "temporal": {
                    "workflowEngine": "temporal",
                    "workflowType": "ReviewRunWorkflow",
                    "workflowId": "review-run-RRUN-VERIFY",
                    "historyPolicy": "ids_hashes_versions_only",
                },
                "scorecard": {
                    "schemaVersion": "aicheck-review-orchestration-scorecard-v1",
                    "targetScore": 100,
                    "score": 100,
                    "ok": True,
                    "sections": [
                        {"name": "workflow", "score": 25, "maxScore": 25, "status": "pass", "blockers": []},
                        {"name": "graph", "score": 25, "maxScore": 25, "status": "pass", "blockers": []},
                        {"name": "evidence", "score": 30, "maxScore": 30, "status": "pass", "blockers": []},
                        {"name": "governance", "score": 20, "maxScore": 20, "status": "pass", "blockers": []},
                    ],
                    "blockers": [],
                },
            }
        )
    if path == "/api/fde/review-runs/RRUN-VERIFY/replay":
        assert request.headers.get("authorization") == "Bearer token-fde"
        return envelope(
            {
                "reviewRun": {
                    "reviewRunId": probe_state["replayReviewRunId"],
                    "parentReviewRunId": "RRUN-VERIFY",
                    "runMode": "diagnostic_replay",
                    "status": "queued",
                },
                "auditLogId": "AUD-REPLAY",
            }
        )
    if path.endswith("/inspection/nodes/24/report-review"):
        return envelope(code=403, reason="FORBIDDEN")
    if path == "/api/admin/config-overview/publish":
        return envelope(code=403, reason="FORBIDDEN")
    return httpx.Response(404, json={"error": path})


def ocr_transport(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/internal/ocr/parse":
        body = json.loads(request.read().decode("utf-8") or "{}")
        if not body.get("storageKey"):
            return envelope(code=40001, reason="VALIDATION_ERROR")
        if body.get("storageKey") == UPLOADED_STORAGE_KEY:
            return envelope(
                {
                    "storageKey": UPLOADED_STORAGE_KEY,
                    "fileName": body.get("fileName"),
                    "status": "success",
                    "fragments": [{"pageNo": 1, "text": "AIcheck OCR verifier", "confidence": 0.91}],
                    "fields": [],
                    "diagnostics": [],
                }
            )
        return envelope(
            {
                "storageKey": body.get("storageKey"),
                "fileName": body.get("fileName"),
                "status": "failed",
                "fragments": [],
                "fields": [],
                "diagnostics": ["missing object"],
            }
        )
    if request.url.path == "/readyz":
        return envelope(
            {
                "service": "ocr-service",
                "pipelineAvailable": True,
                "pipelineBackend": "/opt/agentdesign/mvp-system/backend",
                "placeholderAllowed": False,
                "offlineOnly": True,
                "networkDisabled": True,
                "ready": True,
                "readinessFailures": [],
                "modelManifest": {
                    "modelDirs": {
                        "PADDLEOCR_MODEL_DIR": {"path": "/models/paddleocr", "exists": True},
                        "PADDLEX_MODEL_DIR": {"path": "/models/paddlex", "exists": True},
                    }
                },
            }
        )
    if request.url.path == "/internal/ocr/doctor":
        return envelope(
            {
                "schemaVersion": "aicheck-ocr-runtime-doctor-v1",
                "ok": True,
                "summary": {"pass": 6, "warn": 0, "fail": 0, "total": 6},
                "checks": [
                    {"name": "package.cv2", "status": "pass", "message": "opencv-python-headless is importable."},
                    {"name": "subprocess.python", "status": "pass", "message": "OCR subprocess Python is usable."},
                    {"name": "models.PADDLEOCR_MODEL_DIR", "status": "pass", "message": "PADDLEOCR_MODEL_DIR exists."},
                    {"name": "engine.paddle_ocr_subprocess", "status": "pass", "message": "paddle_ocr_subprocess is available."},
                    {"name": "engine.pp_structure_v3", "status": "pass", "message": "pp_structure_v3 is available."},
                    {"name": "preprocess.variants", "status": "pass", "message": "Preprocess variants can be generated."},
                ],
            }
        )
    return envelope(
        {
            "service": "ocr-service",
            "pipelineAvailable": True,
            "pipelineBackend": "/opt/agentdesign/mvp-system/backend",
            "placeholderAllowed": False,
            "offlineOnly": True,
            "networkDisabled": True,
        }
    )


def litellm_transport(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/health":
        assert request.headers.get("authorization") == "Bearer sk-test"
        return httpx.Response(200, json={"status": "ok"})
    if request.url.path == "/v1/models":
        assert request.headers.get("authorization") == "Bearer sk-test"
        return httpx.Response(
            200,
            json={
                "data": [
                    {"id": "default-chat"},
                    {"id": "review-chat"},
                    {"id": "deepseek-reasoner"},
                    {"id": "embedding-default"},
                    {"id": "compare-fast"},
                ]
            },
        )
    if request.url.path == "/v1/chat/completions":
        body = json.loads(request.read().decode("utf-8") or "{}")
        assert body["model"] == "default-chat"
        assert request.headers.get("authorization") == "Bearer sk-test"
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-verify",
                "choices": [{"message": {"role": "assistant", "content": "AIcheck verifier ok"}}],
            },
        )
    if request.url.path == "/v1/embeddings":
        body = json.loads(request.read().decode("utf-8") or "{}")
        assert body["model"] == "embedding-default"
        assert request.headers.get("authorization") == "Bearer sk-test"
        return httpx.Response(
            200,
            json={"data": [{"index": 0, "embedding": [0.01, 0.02, 0.03]}], "model": "embedding-default"},
        )
    if request.url.path == "/key/generate":
        body = json.loads(request.read().decode("utf-8") or "{}")
        assert request.headers.get("authorization") == "Bearer sk-test"
        assert body["models"] == ["default-chat", "embedding-default"]
        assert body["max_budget"] == 0.01
        assert body["rpm_limit"] == 1
        assert body["tpm_limit"] == 256
        return httpx.Response(
            200,
            json={
                "key": "sk-generated-secret",
                "key_alias": body["key_alias"],
                "models": body["models"],
                "max_budget": body["max_budget"],
                "rpm_limit": body["rpm_limit"],
                "tpm_limit": body["tpm_limit"],
            },
        )
    if request.url.path == "/key/delete":
        body = json.loads(request.read().decode("utf-8") or "{}")
        assert request.headers.get("authorization") == "Bearer sk-test"
        assert body["key_aliases"][0].startswith("aicheck-deploy-verify-")
        return httpx.Response(200, json={"deleted_keys": body["key_aliases"]})
    return httpx.Response(404)


def litellm_unhealthy_transport(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/health":
        assert request.headers.get("authorization") == "Bearer sk-test"
        return httpx.Response(
            200,
            json={
                "healthy_count": 0,
                "unhealthy_count": 1,
                "unhealthy_endpoints": [
                    {
                        "model": "openai/gpt-4o-mini",
                        "error": "AuthenticationError: Incorrect API key provided: sk-secret-test",
                    }
                ],
            },
        )
    return litellm_transport(request)


def storage_transport(request: httpx.Request) -> httpx.Response:
    if request.method == "PUT" and request.url.path == "/upload/UPS-VERIFY/DOC-VERIFY":
        assert request.headers.get("content-type") == "application/pdf"
        assert request.content.startswith(b"%PDF-1.4")
        probe_state["signedPut"] = "ok"
        return httpx.Response(200)
    if request.method == "GET" and request.url.path in {"/download/DOC-VERIFY/preview", "/download/DOC-VERIFY/download"}:
        probe_state["signedGets"].append(request.url.path)
        return httpx.Response(200, content=b"%PDF-1.4\n% AIcheck verifier object\n%%EOF\n")
    return httpx.Response(404)


def ocr_placeholder_transport(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/readyz":
        return envelope(
            {
                "service": "ocr-service",
                "pipelineAvailable": False,
                "pipelineBackend": "/opt/agentdesign/mvp-system/backend",
                "placeholderAllowed": True,
                "offlineOnly": False,
                "networkDisabled": False,
                "ready": False,
                "readinessFailures": ["placeholder enabled"],
                "modelManifest": {"modelDirs": {}},
            }
        )
    if request.url.path == "/healthz":
        return envelope(
            {
                "service": "ocr-service",
                "pipelineAvailable": False,
                "pipelineBackend": "/opt/agentdesign/mvp-system/backend",
                "placeholderAllowed": True,
                "offlineOnly": False,
                "networkDisabled": False,
            }
        )
    if request.url.path == "/internal/ocr/doctor":
        return envelope(
            {
                "schemaVersion": "aicheck-ocr-runtime-doctor-v1",
                "ok": False,
                "summary": {"pass": 0, "warn": 0, "fail": 2, "total": 2},
                "checks": [
                    {"name": "policy.placeholder-disabled", "status": "fail", "message": "Placeholder OCR is enabled."},
                    {"name": "preprocess.variants", "status": "fail", "message": "Only original images can be used."},
                ],
            }
        )
    return ocr_transport(request)


def api_failed_transaction_transport(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/api/system/mongo-transaction-probe":
        return envelope(
            {
                "mongoEnabled": True,
                "transactionsConfigured": True,
                "transactionProbe": "failed",
                "reason": "transaction_probe_failed",
            }
        )
    return api_transport(request)


def api_review_run_no_progress_transport(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/api/review-runs/RRUN-VERIFY":
        return envelope(
            {
                "run": {
                    "reviewRunId": "RRUN-VERIFY",
                    "aiRunId": "AIRUN-VERIFY",
                    "projectId": "P-2026-HDCP-001",
                    "nodeId": 24,
                    "status": "queued",
                    "workflowEngine": "temporal",
                    "workflowType": "ReviewRunWorkflow",
                    "workflowId": "review-run-RRUN-VERIFY",
                    "graphEngine": "langgraph",
                    "modelGateway": "litellm",
                    "modelAlias": "review-chat",
                    "graphSummary": {"total": 3, "statusCounts": {"pending": 3}},
                }
            }
        )
    if request.url.path == "/api/review-runs/RRUN-VERIFY/graph":
        return envelope(
            {
                "reviewRunId": "RRUN-VERIFY",
                "nodes": [
                    {"nodeKey": "load_context", "status": "pending"},
                    {"nodeKey": "run_rule_engine", "status": "pending"},
                    {"nodeKey": "quality_gate", "status": "pending"},
                ],
                "edges": [
                    {"source": "load_context", "target": "run_rule_engine"},
                    {"source": "run_rule_engine", "target": "quality_gate"},
                ],
                "timeline": [{"eventType": "review_run.created", "status": "queued"}],
            }
        )
    return api_transport(request)


def api_review_run_low_scorecard_transport(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/api/fde/review-runs/RRUN-VERIFY":
        return envelope(
            {
                "run": {
                    "reviewRunId": "RRUN-VERIFY",
                    "workflowEngine": "temporal",
                    "graphEngine": "langgraph",
                    "modelGateway": "litellm",
                },
                "graph": {
                    "nodes": [{"nodeKey": "load_context", "status": "succeeded"}],
                    "edges": [],
                    "timeline": [{"eventType": "review_run.created", "status": "queued"}],
                },
                "timeline": [{"eventType": "review_run.created", "status": "queued"}],
                "temporal": {
                    "workflowEngine": "temporal",
                    "workflowType": "ReviewRunWorkflow",
                    "workflowId": "review-run-RRUN-VERIFY",
                    "historyPolicy": "ids_hashes_versions_only",
                },
                "scorecard": {
                    "schemaVersion": "aicheck-review-orchestration-scorecard-v1",
                    "targetScore": 100,
                    "score": 75,
                    "ok": False,
                    "sections": [
                        {"name": "workflow", "score": 25, "maxScore": 25, "status": "pass", "blockers": []},
                        {
                            "name": "graph",
                            "score": 0,
                            "maxScore": 25,
                            "status": "fail",
                            "blockers": ["LangGraph Postgres checkpointer is not active"],
                        },
                        {"name": "evidence", "score": 30, "maxScore": 30, "status": "pass", "blockers": []},
                        {"name": "governance", "score": 20, "maxScore": 20, "status": "pass", "blockers": []},
                    ],
                    "blockers": ["LangGraph Postgres checkpointer is not active"],
                },
            }
        )
    return api_transport(request)


def verify_args(**overrides):
    values = {
        "api_base": "http://api",
        "ocr_base": "http://ocr",
        "litellm_base": "http://litellm",
        "litellm_api_key": "sk-test",
        "project_id": "P-2026-HDCP-001",
        "roles": "admin,inspection,contractor",
        "strict_production": True,
        "skip_ocr": False,
        "skip_litellm": False,
        "write_probes": False,
        "ocr_object_probe": False,
        "review_run_probe": False,
        "review_run_wait_seconds": 0.0,
        "litellm_management_probes": False,
        "litellm_provider_probes": False,
    }
    values.update(overrides)
    return Namespace(**values)


def litellm_provider_failure_transport(request: httpx.Request) -> httpx.Response:
    if request.url.path in {"/health", "/v1/models"}:
        return litellm_transport(request)
    if request.url.path == "/v1/chat/completions":
        return httpx.Response(502, json={"error": {"message": "provider unavailable sk-secret"}})
    if request.url.path == "/v1/embeddings":
        return httpx.Response(200, json={"data": [{"embedding": [0.1]}]})
    return httpx.Response(404)


def litellm_db_disconnected_transport(request: httpx.Request) -> httpx.Response:
    if request.url.path in {"/health", "/v1/models"}:
        return litellm_transport(request)
    if request.url.path == "/key/generate":
        return httpx.Response(
            500,
            json={"error": {"message": "DB not connected. See https://docs.litellm.ai/docs/proxy/virtual_keys"}},
        )
    return httpx.Response(404)


def test_verify_config_requires_write_probes_for_ocr_object_probe() -> None:
    with pytest.raises(SystemExit) as exc:
        config_from_args(verify_args(ocr_object_probe=True, write_probes=False))

    assert "--ocr-object-probe requires --write-probes" in str(exc.value)


def test_verify_config_rejects_ocr_object_probe_when_ocr_is_skipped() -> None:
    with pytest.raises(SystemExit) as exc:
        config_from_args(verify_args(ocr_object_probe=True, write_probes=True, skip_ocr=True))

    assert "--ocr-object-probe cannot be used with --skip-ocr" in str(exc.value)


def test_verify_config_requires_fde_and_inspection_for_review_run_probe() -> None:
    with pytest.raises(SystemExit) as exc:
        config_from_args(verify_args(review_run_probe=True, roles="admin,inspection,contractor"))

    assert "--review-run-probe requires --roles including inspection,fde" in str(exc.value)


def test_deployment_probe_pdf_contains_text_for_ocr() -> None:
    body = deployment_probe_pdf()

    assert body.startswith(b"%PDF-1.4")
    assert b"AIcheck OCR verifier" in body
    assert b"startxref" in body


def test_role_login_password_uses_verify_or_bootstrap_env(monkeypatch) -> None:
    assert role_login_password("inspection") == "inspection"

    monkeypatch.setenv("AICHECK_BOOTSTRAP_PASSWORD_INSPECTION", "Bootstrap!2026")
    assert role_login_password("inspection") == "Bootstrap!2026"

    monkeypatch.setenv("AICHECK_VERIFY_PASSWORD_INSPECTION", "Verify!2026")
    assert role_login_password("inspection") == "Verify!2026"


def test_deployment_verifier_redacts_sensitive_result_fields(capsys) -> None:
    config = VerifyConfig(
        api_base="http://api",
        ocr_base=None,
        litellm_base=None,
        litellm_api_key=None,
        project_id="P-2026-HDCP-001",
        roles=["admin"],
        strict_production=True,
        skip_ocr=True,
        skip_litellm=True,
        write_probes=False,
        ocr_object_probe=False,
        review_run_probe=False,
        review_run_wait_seconds=0.0,
        litellm_management_probes=False,
        litellm_provider_probes=False,
    )
    verifier = DeploymentVerifier(
        config,
        api_client=httpx.Client(base_url=config.api_base, transport=httpx.MockTransport(api_transport)),
    )

    verifier.add(
        "redaction",
        "fail",
        "Unexpected envelope: {'token': 'sk-secret-litellm', 'authorization': 'Bearer abcdefghijk'}",
        {
            "token": "plain-token-value",
            "storageKey": "documents/DV-VERIFY-V1",
            "nested": {
                "api_key": "sk-nested-secret",
                "diagnostic": "provider said sk-provider-secret",
            },
        },
    )
    result = verifier.results[0]

    assert "sk-secret-litellm" not in result.detail
    assert "Bearer abcdefghijk" not in result.detail
    assert "***" in result.detail
    assert result.data
    assert result.data["token"] == "***"
    assert result.data["storageKey"] == "documents/DV-VERIFY-V1"
    assert result.data["nested"]["api_key"] == "***"
    assert "sk-provider-secret" not in result.data["nested"]["diagnostic"]

    print_results(verifier.results, as_json=True)
    output = capsys.readouterr().out
    assert "plain-token-value" not in output
    assert "sk-secret-litellm" not in output
    assert "sk-nested-secret" not in output
    assert "sk-provider-secret" not in output


def test_deployment_verifier_passes_happy_path() -> None:
    probe_state["signedPut"] = ""
    probe_state["signedGets"] = []
    config = VerifyConfig(
        api_base="http://api",
        ocr_base="http://ocr",
        litellm_base="http://litellm",
        litellm_api_key="sk-test",
        project_id="P-2026-HDCP-001",
        roles=["admin", "inspection", "contractor", "fde"],
        strict_production=True,
        skip_ocr=False,
        skip_litellm=False,
        write_probes=True,
        ocr_object_probe=True,
        review_run_probe=True,
        review_run_wait_seconds=0.0,
        litellm_management_probes=True,
        litellm_provider_probes=True,
    )
    verifier = DeploymentVerifier(
        config,
        api_client=httpx.Client(base_url=config.api_base, transport=httpx.MockTransport(api_transport)),
        ocr_client=httpx.Client(base_url=config.ocr_base, transport=httpx.MockTransport(ocr_transport)),
        litellm_client=httpx.Client(base_url=config.litellm_base, transport=httpx.MockTransport(litellm_transport)),
        storage_client=httpx.Client(transport=httpx.MockTransport(storage_transport)),
    )

    results = verifier.run()

    assert results
    assert all(item.status in {"pass", "skip"} for item in results)
    assert any(item.name == "api.strict-production" and item.status == "pass" for item in results)
    assert any(item.name == "mongo.transaction-probe" and item.status == "pass" for item in results)
    assert any(item.name == "auth.admin-reads" and item.status == "pass" for item in results)
    assert any(item.name == "auth.identity-spoof" and item.status == "pass" for item in results)
    assert any(item.name == "auth.action-bypass" and item.status == "pass" for item in results)
    assert any(item.name == "auth.read-scope" and item.status == "pass" for item in results)
    assert any(item.name == "auth.aggregate-scope" and item.status == "pass" for item in results)
    assert any(item.name == "api.write-probes" and item.status == "pass" for item in results)
    assert any(item.name == "api.write-probes.signed-put" and item.status == "pass" for item in results)
    assert any(item.name == "api.write-probes.document-preview-get" and item.status == "pass" for item in results)
    assert any(item.name == "api.write-probes.document-download-get" and item.status == "pass" for item in results)
    assert any(item.name == "ocr.uploaded-object-parse" and item.status == "pass" for item in results)
    review_probe = next(item for item in results if item.name == "api.review-run-probe")
    assert review_probe.status == "pass"
    assert review_probe.data
    assert review_probe.data["dispatchMode"] == "temporal"
    assert review_probe.data["workflowEngine"] == "temporal"
    assert review_probe.data["graphEngine"] == "langgraph"
    assert review_probe.data["graphProgressed"] is True
    assert review_probe.data["scorecardScore"] == 100
    assert review_probe.data["scorecardOk"] is True
    assert review_probe.data["replayReviewRunId"] == "RRUN-REPLAY-VERIFY"
    assert probe_state["signedPut"] == "ok"
    assert set(probe_state["signedGets"]) == {"/download/DOC-VERIFY/preview", "/download/DOC-VERIFY/download"}
    assert any(item.name == "ocr.health" and item.status == "pass" for item in results)
    assert any(item.name == "ocr.runtime-doctor" and item.status == "pass" for item in results)
    assert any(item.name == "ocr.parse-contract" and item.status == "pass" for item in results)
    assert any(item.name == "ocr.bad-request" and item.status == "pass" for item in results)
    assert any(item.name == "litellm.models" and item.status == "pass" for item in results)
    assert any(item.name == "litellm.aliases" and item.status == "pass" for item in results)
    management_probe = next(item for item in results if item.name == "litellm.management-probes")
    assert management_probe.status == "pass"
    assert management_probe.data
    assert management_probe.data["keyCreated"] is True
    assert management_probe.data["keyDeleted"] is True
    assert "sk-generated-secret" not in json.dumps(management_probe.data)
    assert any(item.name == "litellm.chat-probe" and item.status == "pass" for item in results)
    assert any(item.name == "litellm.embedding-probe" and item.status == "pass" for item in results)


def test_deployment_verifier_fails_strict_production_when_ocr_uses_placeholder() -> None:
    config = VerifyConfig(
        api_base="http://api",
        ocr_base="http://ocr",
        litellm_base=None,
        litellm_api_key=None,
        project_id="P-2026-HDCP-001",
        roles=["admin", "inspection", "contractor"],
        strict_production=True,
        skip_ocr=False,
        skip_litellm=True,
        write_probes=False,
        ocr_object_probe=False,
        review_run_probe=False,
        review_run_wait_seconds=0.0,
        litellm_management_probes=False,
        litellm_provider_probes=False,
    )
    verifier = DeploymentVerifier(
        config,
        api_client=httpx.Client(base_url=config.api_base, transport=httpx.MockTransport(api_transport)),
        ocr_client=httpx.Client(base_url=config.ocr_base, transport=httpx.MockTransport(ocr_placeholder_transport)),
        litellm_client=None,
    )

    results = verifier.run()

    ocr_health = next(item for item in results if item.name == "ocr.health")
    ocr_doctor = next(item for item in results if item.name == "ocr.runtime-doctor")
    assert ocr_health.status == "fail"
    assert "pipelineAvailable must be true" in ocr_health.detail
    assert "placeholderAllowed must be false" in ocr_health.detail
    assert ocr_doctor.status == "fail"
    assert "runtime doctor has failed checks" in ocr_doctor.detail


def test_deployment_verifier_fails_strict_production_when_mongo_transaction_probe_fails() -> None:
    config = VerifyConfig(
        api_base="http://api",
        ocr_base=None,
        litellm_base=None,
        litellm_api_key=None,
        project_id="P-2026-HDCP-001",
        roles=["admin", "inspection", "contractor"],
        strict_production=True,
        skip_ocr=True,
        skip_litellm=True,
        write_probes=False,
        ocr_object_probe=False,
        review_run_probe=False,
        review_run_wait_seconds=0.0,
        litellm_management_probes=False,
        litellm_provider_probes=False,
    )
    verifier = DeploymentVerifier(
        config,
        api_client=httpx.Client(
            base_url=config.api_base,
            transport=httpx.MockTransport(api_failed_transaction_transport),
        ),
        ocr_client=None,
        litellm_client=None,
    )

    results = verifier.run()

    transaction_probe = next(item for item in results if item.name == "mongo.transaction-probe")
    assert transaction_probe.status == "fail"
    assert "transactionProbe must be pass" in transaction_probe.detail


def test_deployment_verifier_fails_review_run_probe_when_worker_does_not_progress() -> None:
    config = VerifyConfig(
        api_base="http://api",
        ocr_base=None,
        litellm_base=None,
        litellm_api_key=None,
        project_id="P-2026-HDCP-001",
        roles=["admin", "inspection", "contractor", "fde"],
        strict_production=True,
        skip_ocr=True,
        skip_litellm=True,
        write_probes=False,
        ocr_object_probe=False,
        review_run_probe=True,
        review_run_wait_seconds=0.0,
        litellm_management_probes=False,
        litellm_provider_probes=False,
    )
    verifier = DeploymentVerifier(
        config,
        api_client=httpx.Client(base_url=config.api_base, transport=httpx.MockTransport(api_review_run_no_progress_transport)),
        ocr_client=None,
        litellm_client=None,
    )

    results = verifier.run()

    review_probe = next(item for item in results if item.name == "api.review-run-probe")
    assert review_probe.status == "fail"
    assert "did not progress" in review_probe.detail
    assert review_probe.data
    assert review_probe.data["nodeStatuses"] == ["pending"]


def test_deployment_verifier_fails_review_run_probe_when_scorecard_is_not_100() -> None:
    config = VerifyConfig(
        api_base="http://api",
        ocr_base=None,
        litellm_base=None,
        litellm_api_key=None,
        project_id="P-2026-HDCP-001",
        roles=["admin", "inspection", "contractor", "fde"],
        strict_production=True,
        skip_ocr=True,
        skip_litellm=True,
        write_probes=False,
        ocr_object_probe=False,
        review_run_probe=True,
        review_run_wait_seconds=0.0,
        litellm_management_probes=False,
        litellm_provider_probes=False,
    )
    verifier = DeploymentVerifier(
        config,
        api_client=httpx.Client(
            base_url=config.api_base,
            transport=httpx.MockTransport(api_review_run_low_scorecard_transport),
        ),
        ocr_client=None,
        litellm_client=None,
    )

    results = verifier.run()

    review_probe = next(item for item in results if item.name == "api.review-run-probe")
    assert review_probe.status == "fail"
    assert "scorecard 100" in review_probe.detail
    assert review_probe.data
    assert review_probe.data["scorecard"]["score"] == 75


def test_deployment_verifier_fails_litellm_provider_probe_without_leaking_provider_body() -> None:
    config = VerifyConfig(
        api_base="http://api",
        ocr_base=None,
        litellm_base="http://litellm",
        litellm_api_key="sk-test",
        project_id="P-2026-HDCP-001",
        roles=["admin", "inspection", "contractor"],
        strict_production=True,
        skip_ocr=True,
        skip_litellm=False,
        write_probes=False,
        ocr_object_probe=False,
        review_run_probe=False,
        review_run_wait_seconds=0.0,
        litellm_management_probes=False,
        litellm_provider_probes=True,
    )
    verifier = DeploymentVerifier(
        config,
        api_client=httpx.Client(base_url=config.api_base, transport=httpx.MockTransport(api_transport)),
        ocr_client=None,
        litellm_client=httpx.Client(
            base_url=config.litellm_base,
            transport=httpx.MockTransport(litellm_provider_failure_transport),
        ),
    )

    results = verifier.run()

    chat_probe = next(item for item in results if item.name == "litellm.chat-probe")
    embedding_probe = next(item for item in results if item.name == "litellm.embedding-probe")
    assert chat_probe.status == "fail"
    assert chat_probe.detail == "HTTP 502"
    assert "sk-secret" not in chat_probe.detail
    assert embedding_probe.status == "pass"


def test_deployment_verifier_fails_litellm_management_probe_when_db_is_not_connected() -> None:
    config = VerifyConfig(
        api_base="http://api",
        ocr_base=None,
        litellm_base="http://litellm",
        litellm_api_key="sk-test",
        project_id="P-2026-HDCP-001",
        roles=["admin", "inspection", "contractor"],
        strict_production=True,
        skip_ocr=True,
        skip_litellm=False,
        write_probes=False,
        ocr_object_probe=False,
        review_run_probe=False,
        review_run_wait_seconds=0.0,
        litellm_management_probes=True,
        litellm_provider_probes=False,
    )
    verifier = DeploymentVerifier(
        config,
        api_client=httpx.Client(base_url=config.api_base, transport=httpx.MockTransport(api_transport)),
        ocr_client=None,
        litellm_client=httpx.Client(
            base_url=config.litellm_base,
            transport=httpx.MockTransport(litellm_db_disconnected_transport),
        ),
    )

    results = verifier.run()

    management_probe = next(item for item in results if item.name == "litellm.management-probes")
    assert management_probe.status == "fail"
    assert "/key/generate HTTP 500" in management_probe.detail
    assert management_probe.data
    assert "DB not connected" in management_probe.data["error"]["message"]


def test_deployment_verifier_fails_litellm_health_when_proxy_reports_unhealthy_models() -> None:
    config = VerifyConfig(
        api_base="http://api",
        ocr_base=None,
        litellm_base="http://litellm",
        litellm_api_key="sk-test",
        project_id="P-2026-HDCP-001",
        roles=["admin", "inspection", "contractor"],
        strict_production=True,
        skip_ocr=True,
        skip_litellm=False,
        write_probes=False,
        ocr_object_probe=False,
        review_run_probe=False,
        review_run_wait_seconds=0.0,
        litellm_management_probes=False,
        litellm_provider_probes=False,
    )
    verifier = DeploymentVerifier(
        config,
        api_client=httpx.Client(base_url=config.api_base, transport=httpx.MockTransport(api_transport)),
        ocr_client=None,
        litellm_client=httpx.Client(
            base_url=config.litellm_base,
            transport=httpx.MockTransport(litellm_unhealthy_transport),
        ),
    )

    results = verifier.run()

    health = next(item for item in results if item.name == "litellm.health")
    assert health.status == "fail"
    assert "unhealthy endpoint" in health.detail
    assert health.data == {
        "healthyCount": 0,
        "unhealthyCount": 1,
        "unhealthyModels": ["openai/gpt-4o-mini"],
    }
    assert "sk-secret" not in health.detail
