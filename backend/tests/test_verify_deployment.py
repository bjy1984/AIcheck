from __future__ import annotations

import json

import httpx

from scripts.verify_deployment import DeploymentVerifier, VerifyConfig


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
    if path in {"/api/workbench/projects", "/api/knowledge/tasks"}:
        return envelope({"items": [], "total": 0})
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
        return httpx.Response(200, json={"data": [{"id": "default-chat"}]})
    return httpx.Response(404)


def test_deployment_verifier_passes_happy_path() -> None:
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
    )
    verifier = DeploymentVerifier(
        config,
        api_client=httpx.Client(base_url=config.api_base, transport=httpx.MockTransport(api_transport)),
        ocr_client=httpx.Client(base_url=config.ocr_base, transport=httpx.MockTransport(ocr_transport)),
        litellm_client=httpx.Client(base_url=config.litellm_base, transport=httpx.MockTransport(litellm_transport)),
    )

    results = verifier.run()

    assert results
    assert all(item.status in {"pass", "skip"} for item in results)
    assert any(item.name == "api.strict-production" and item.status == "pass" for item in results)
    assert any(item.name == "auth.admin-reads" and item.status == "pass" for item in results)
    assert any(item.name == "auth.identity-spoof" and item.status == "pass" for item in results)
    assert any(item.name == "auth.action-bypass" and item.status == "pass" for item in results)
    assert any(item.name == "auth.read-scope" and item.status == "pass" for item in results)
    assert any(item.name == "auth.aggregate-scope" and item.status == "pass" for item in results)
    assert any(item.name == "ocr.health" and item.status == "pass" for item in results)
    assert any(item.name == "litellm.models" and item.status == "pass" for item in results)
