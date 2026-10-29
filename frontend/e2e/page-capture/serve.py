"""Serve the production UI and real API with isolated, in-memory demo data.

Usage (from backend): .venv/bin/python ../frontend/e2e/page-capture/serve.py 4176
No .env file, database, worker, or production storage is loaded.
"""
import os
from pathlib import Path
import sys
import tempfile
import re

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))
# The screenshot process must not inherit external services or credentials.
for key in list(os.environ):
    if key.startswith(("AICHECK_", "OPENAI_", "ANTHROPIC_", "LITELLM_", "AWS_", "S3_", "MINIO_")) or key in {"DATABASE_URL", "REDIS_URL"}:
        os.environ.pop(key, None)
os.environ.update({
    "AICHECK_REQUIRE_AUTH": "true",
    "AICHECK_REQUIRE_IF_MATCH": "false",
    "AICHECK_ENABLE_DEMO_DATA": "true",
    "AICHECK_ENABLE_DEMO_USERS": "true",
    "AICHECK_ENABLE_COMPATIBILITY_MOCKS": "true",
    "AICHECK_SQLITE_DISABLE": "true",
    "AICHECK_EMBEDDING_FORCE_OFFLINE_HASH": "true",
    "AICHECK_OCR_PROVIDER_MODE": "local",
    "AICHECK_OCR_DEFAULT_PROVIDER": "local",
    "AICHECK_CERT_PLATFORM_VERIFY": "off",
    "AICHECK_WORKSTATIONS_ENABLED": "true",
    "AICHECK_OBJECT_STORAGE_ROOT": tempfile.mkdtemp(prefix="aicheck-page-capture-"),
})

from apps.api.main import app
from libs.db.repository import repo
from fastapi import Request
from fastapi.responses import FileResponse, JSONResponse
from starlette.staticfiles import StaticFiles
import uvicorn
from starlette.exceptions import HTTPException

assert not repo.postgres_dsn and not repo.sqlite_enabled
DIST = ROOT / "frontend" / (sys.argv[2] if len(sys.argv) > 2 else "dist-pro")
assert (DIST / "index.html").is_file(), "Build the current production UI first"

if "auth-extras" in sys.argv:
    # Explicit synthetic states for viewing auth forms; no credentials are changed.
    from libs.security.auth import user_record_by_username
    from apps.api.project_registration_routes import INVITES
    from datetime import datetime, timedelta, UTC
    user_record_by_username("admin")["mustChangePassword"] = True
    repo.state.setdefault(INVITES, []).append({
        "id": "PINV-PAGE-CAPTURE", "token": "page-capture-example",
        "projectId": repo.state["projects"][0]["id"],
        "expiresAt": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
        "maxUses": 1, "useCount": 0, "disabled": False,
    })

if "workflow-filter-extras" in sys.argv:
    # Isolated UI regression examples only. Reuse the existing finding's exact
    # tenant/project/node scope; do not add members or fabricate evidence links.
    from copy import deepcopy
    baseline = next(
        item for item in repo.state["review_findings"]
        if item.get("id") == "FND-CA-FIXTURE-001"
    )
    for finding_id, title, status, evidence_ids in [
        ("FND-CAPTURE-ACCEPTED", "【隔离截图示例】已采纳的发现", "accepted", baseline.get("evidenceLinkIds", [])),
        ("FND-CAPTURE-NO-EVIDENCE", "【隔离截图示例】尚未关联证据的发现", "draft", []),
    ]:
        example = deepcopy(baseline)
        example.update({
            "id": finding_id,
            "title": title,
            "description": "此记录仅用于隔离截图环境验证筛选与详情联动，不是业务审查结果。",
            "status": status,
            "humanStatus": "pending_human_review",
            "evidenceLinkIds": deepcopy(evidence_ids),
        })
        repo.state["review_findings"].append(example)

if "score-feedback-extras" in sys.argv:
    # Clearly labelled display-only copies for long-text/list layout checks.
    # Keep the original scope, classifications and decisions unchanged; no
    # triage records, evaluation cases or model calls are created.
    from copy import deepcopy
    baseline_feedback = next(
        item for item in repo.state["ai_feedback"]
        if item.get("id") == "AIFB-24-001"
    )
    for number in range(1, 21):
        example = deepcopy(baseline_feedback)
        comment = (
            "此记录仅用于隔离环境检查长文本完整阅读与键盘展开，不是新增业务结论。"
            "需要核对反馈对应的项目、节点和资料上下文，说明原文在展开后应完整可读。"
        )
        example.update({
            "id": f"AIFB-SCORE-DISPLAY-{number:02d}",
            "comment": f"【隔离显示测试 {number:02d}】" + (comment * 4 if number == 1 else comment),
        })
        repo.state["ai_feedback"].append(example)

if "role-content-extras" in sys.argv:
    # Explicit synthetic, undecided task for read-only presentation QA. Reuse a
    # real demo run's scope and snapshot; do not invent decisions or evidence.
    from datetime import datetime, UTC
    source_run = next(
        item for item in repo.state.get("ai_runs", [])
        if item.get("id") == "AIRUN-24-20260625-01"
    )
    repo.state.setdefault("blind_review_tasks", []).append({
        "id": "BRT-CAPTURE-ROLE-FOCUS",
        "batchId": "BRB-CAPTURE-ROLE-FOCUS",
        "title": "【隔离截图示例】未判盲审任务",
        "status": "open",
        "projectId": source_run["projectId"],
        "nodeId": source_run["nodeId"],
        "aiRunId": source_run["id"],
        "createdAt": datetime.now(UTC).isoformat(),
        "createdBy": "【隔离截图示例】角色内容验证",
        "sampleRatio": 0.1,
        "windowDays": None,
    })

@app.middleware("http")
async def capture_read_only(request: Request, call_next):
    # The AI panel automatically creates an empty local conversation on mount.
    # This endpoint only initializes in-memory context; it cannot invoke a model.
    initialize_session = request.method == "POST" and re.fullmatch(
        r"/api/projects/[^/]+/inspection/nodes/\d+/review-sessions", request.url.path
    )
    if request.method not in {"GET", "HEAD", "OPTIONS"} and not initialize_session and request.url.path not in {
        "/api/auth/login", "/api/auth/logout", "/api/auth/refresh"
    }:
        return JSONResponse({"code": 403, "message": "截图验证环境为只读，未执行此操作", "data": None}, status_code=403)
    return await call_next(request)

app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="capture-assets")

@app.get("/{path:path}", include_in_schema=False)
async def capture_ui(path: str):
    if path.startswith("api/"):
        return JSONResponse({"code": 404, "message": "API not found"}, status_code=404)
    requested = (DIST / path).resolve()
    if requested.is_relative_to(DIST) and requested.is_file():
        return FileResponse(requested)
    return FileResponse(DIST / "index.html")

static_ui = StaticFiles(directory=DIST, html=True)

async def capture_entry(scope, receive, send):
    if scope["type"] != "http" or scope.get("path", "").startswith(("/api/", "/healthz")):
        await app(scope, receive, send)
        return
    try:
        await static_ui(scope, receive, send)
    except HTTPException as exc:
        if exc.status_code != 404:
            raise
        await FileResponse(DIST / "index.html")(scope, receive, send)

if __name__ == "__main__":
    uvicorn.run(capture_entry, host="127.0.0.1", port=int(sys.argv[1]), lifespan="off", log_level="warning")
