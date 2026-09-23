"""HTTP upload and important-node dispatch through the real review execution graph."""
from copy import deepcopy

import fitz
import pytest
from fastapi.testclient import TestClient

from apps.api import routes as api
from apps.api.main import app
from libs.db.repository import repo
from libs.db.seed import PROJECT_ID
from libs.review_orchestrator import execution as ex
from libs.review_orchestrator.dispatcher import prepare_review_run_for_async_dispatch

HEADERS = {"X-Role": "inspection", "X-User-Id": "USER-INSPECTION-001"}
BASE = f"/api/projects/{PROJECT_ID}"


def checked(response):
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["code"] == 0, payload
    return payload["data"]


@pytest.fixture
def uploaded(monkeypatch, tmp_path):
    repo.reset()
    for name, value in {"postgres_enabled": False, "sync_postgres": None, "postgres_dsn": None,
                        "sqlite_enabled": False, "sqlite_path": None}.items():
        monkeypatch.setattr(repo, name, value)
    for name, value in {"AICHECK_WORKSTATIONS_ENABLED": "true", "AICHECK_REVIEW_ORCHESTRATION": "inline",
                        "AICHECK_REVIEW_LLM_EXECUTION": "deterministic", "AICHECK_LANGGRAPH_CHECKPOINT_DISABLE": "true",
                        "AICHECK_CERT_PLATFORM_VERIFY": "off"}.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(api, "WORKSPACE_ROOT", tmp_path)
    monkeypatch.setattr(api, "DOCUMENT_UPLOAD_ROOT", tmp_path / "output/document_uploads")
    monkeypatch.setattr(api.task_dispatcher, "dispatch_parse_document", lambda *args, **kwargs: {"mode": "test", "taskId": "OCR-TEST"})
    monkeypatch.setattr(api.task_dispatcher, "ai_recheck_dispatch_readiness", lambda: {"ready": True})

    def enqueue(project_id, node_id, run_id, **kwargs):
        assert kwargs["force_async"] is True
        run = prepare_review_run_for_async_dispatch(run_id)
        return {"mode": "test", "status": "queued", "reviewRunId": run["reviewRunId"]}

    monkeypatch.setattr(api.task_dispatcher, "dispatch_ai_recheck", enqueue)
    client = TestClient(app)
    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_text((40, 60), "IMPORTANT REVIEW TEST ONLY - DESIGN DOCUMENT APPROVAL")
    pdf_bytes = pdf.tobytes()
    pdf.close()
    session = checked(client.post(BASE + "/documents/upload-session", headers={**HEADERS, "Idempotency-Key": "important-upload-live"},
        json={"requireSignedUrls": True, "files": [{"fileName": "专项审查-设计文件.pdf", "fileType": "pdf", "fileSize": len(pdf_bytes)}]}))
    target = session["uploadUrls"][0]
    checked(client.put(target["url"], headers={**HEADERS, **target["headers"]}, content=pdf_bytes))
    checked(client.post(BASE + f"/documents/upload-session/{session['uploadSessionId']}/complete",
        headers={**HEADERS, "Idempotency-Key": "important-upload-complete"},
        json={"completedFiles": [{"documentVersionId": target["documentVersionId"], "fileSize": len(pdf_bytes)}]}))
    version_id, document_id = target["documentVersionId"], target["documentId"]
    original = client.get(BASE + f"/documents/{document_id}/original", headers=HEADERS, params={"versionId": version_id})
    assert original.status_code == 200
    assert original.content == pdf_bytes
    parsed = {
        "status": "success", "outcomeStatus": "completed", "artifactHash": "sha256:important-review-test",
        "pageCount": 1, "fields": [], "tables": [], "seals": [],
        "fragments": [{"id": "FRAG-IMPORTANT", "pageNo": 1, "text": "专项测试设计文件：设计批准程序，缺少批准签章。", "bbox": [40, 40, 500, 80], "confidence": 0.99}],
    }
    job = repo.create_ocr_job_record(document_id=document_id, version_id=version_id,
        storage_key=repo.find_one("versions", version_id)["storageKey"], file_name="专项审查-设计文件.pdf")
    repo.finish_ocr_job_record(job, parsed)
    repo.apply_ocr_result(document_id, version_id, parsed)
    return client, document_id, version_id


@pytest.mark.parametrize("node_id", [4, 5, 6, 7, 8, 9, 12, 13, 16, 24, 25, 26])
def test_uploaded_unbound_document_reaches_real_review_graph(uploaded, monkeypatch, node_id):
    client, document_id, version_id = uploaded
    assert not any(row.get("documentId") == document_id for row in repo.state["bindings"])
    bindings = deepcopy(repo.state["bindings"])
    node_status = repo.node(PROJECT_ID, node_id)["status"]
    prompt_snapshots = []
    build_prompt = ex.build_review_prompt_parts

    def observe(run, context):
        parts = build_prompt(run, context)
        prompt_snapshots.append(parts["userPayload"].get("importantNodeReview"))
        return parts

    monkeypatch.setattr(ex, "build_review_prompt_parts", observe)
    created = checked(client.post(BASE + f"/inspection/important-review/nodes/{node_id}/runs",
        headers={**HEADERS, "Idempotency-Key": f"important-graph-{node_id}"}, json={"inputDocumentVersionIds": [version_id]}))
    source = repo.find_one("ai_runs", created["runId"])
    outcome = ex.execute_review_run_inline(source["reviewRunId"])
    assert outcome["status"] == "waiting_human_review", outcome
    assert prompt_snapshots and all(snapshot["nodeId"] == node_id for snapshot in prompt_snapshots)
    listed = checked(client.get(BASE + "/inspection/important-review/runs", headers=HEADERS))["items"]
    result = next(row for row in listed if row["id"] == created["runId"])
    assert result["status"] == "waiting_human_review"
    assert result["findingDrafts"] or result["atomicCheckOutcomes"]
    assert result["documents"] == [{"documentId": document_id, "versionId": version_id, "fileName": "专项审查-设计文件.pdf"}]
    assert repo.state["bindings"] == bindings
    assert repo.node(PROJECT_ID, node_id)["status"] == node_status
