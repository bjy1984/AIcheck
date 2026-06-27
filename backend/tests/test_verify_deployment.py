from __future__ import annotations

import json
from argparse import Namespace

import httpx
import pytest

from scripts.verify_deployment import DeploymentVerifier, VerifyConfig, config_from_args, deployment_probe_pdf


probe_state = {"fileName": "deployment-verify-test.pdf", "signedPut": "", "signedGets": []}
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
        return envelope(
            {
                "token": f"token-{role}",
                "user": {"username": role, "role": role, "defaultPath": f"/workbench/{role}" if role != "admin" else "/admin/overview"},
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
        return envelope(code=403, reason="FORBIDDEN")
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
    return envelope(
        {
            "service": "ocr-service",
            "pipelineAvailable": True,
            "pipelineBackend": "/opt/agentdesign/mvp-system/backend",
            "placeholderAllowed": False,
        }
    )


def litellm_transport(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/health":
        return httpx.Response(200, json={"status": "ok"})
    if request.url.path == "/v1/models":
        return httpx.Response(
            200,
            json={
                "data": [
                    {"id": "default-chat"},
                    {"id": "review-chat"},
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
    return httpx.Response(404)


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
    if request.url.path == "/healthz":
        return envelope(
            {
                "service": "ocr-service",
                "pipelineAvailable": False,
                "pipelineBackend": "/opt/agentdesign/mvp-system/backend",
                "placeholderAllowed": True,
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


def test_verify_config_requires_write_probes_for_ocr_object_probe() -> None:
    with pytest.raises(SystemExit) as exc:
        config_from_args(verify_args(ocr_object_probe=True, write_probes=False))

    assert "--ocr-object-probe requires --write-probes" in str(exc.value)


def test_verify_config_rejects_ocr_object_probe_when_ocr_is_skipped() -> None:
    with pytest.raises(SystemExit) as exc:
        config_from_args(verify_args(ocr_object_probe=True, write_probes=True, skip_ocr=True))

    assert "--ocr-object-probe cannot be used with --skip-ocr" in str(exc.value)


def test_deployment_probe_pdf_contains_text_for_ocr() -> None:
    body = deployment_probe_pdf()

    assert body.startswith(b"%PDF-1.4")
    assert b"AIcheck OCR verifier" in body
    assert b"startxref" in body


def test_deployment_verifier_passes_happy_path() -> None:
    probe_state["signedPut"] = ""
    probe_state["signedGets"] = []
    config = VerifyConfig(
        api_base="http://api",
        ocr_base="http://ocr",
        litellm_base="http://litellm",
        litellm_api_key="sk-test",
        project_id="P-2026-HDCP-001",
        roles=["admin", "inspection", "contractor"],
        strict_production=True,
        skip_ocr=False,
        skip_litellm=False,
        write_probes=True,
        ocr_object_probe=True,
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
    assert probe_state["signedPut"] == "ok"
    assert set(probe_state["signedGets"]) == {"/download/DOC-VERIFY/preview", "/download/DOC-VERIFY/download"}
    assert any(item.name == "ocr.health" and item.status == "pass" for item in results)
    assert any(item.name == "ocr.parse-contract" and item.status == "pass" for item in results)
    assert any(item.name == "ocr.bad-request" and item.status == "pass" for item in results)
    assert any(item.name == "litellm.models" and item.status == "pass" for item in results)
    assert any(item.name == "litellm.aliases" and item.status == "pass" for item in results)
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
    assert ocr_health.status == "fail"
    assert "pipelineAvailable must be true" in ocr_health.detail
    assert "placeholderAllowed must be false" in ocr_health.detail


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
