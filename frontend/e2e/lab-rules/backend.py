"""Local-only HTTP bridge to real API routes with isolated in-memory seed data."""
import os
from http.server import BaseHTTPRequestHandler, HTTPServer

for key, value in {
    "AICHECK_REQUIRE_AUTH": "false", "AICHECK_REQUIRE_IF_MATCH": "false",
    "AICHECK_ENABLE_DEMO_DATA": "true", "AICHECK_ENABLE_COMPATIBILITY_MOCKS": "true",
    "AICHECK_ALLOW_DEV_TOKENS": "true", "AICHECK_WORKSTATIONS_ENABLED": "true",
}.items():
    os.environ[key] = value

from fastapi.testclient import TestClient

from apps.api.main import app
from libs.db.repository import repo

repo.reset()
repo.postgres_enabled = False
repo.sqlite_enabled = False
from libs.review_document_scope import freeze_document_scope

trial_run = {"reviewRunId": "RR-BROWSER-TRIAL", "projectId": "P-2026-HDCP-001", "nodeId": 24,
             "businessPackId": "engineering_inspection_v1", "inputDocumentVersionIds": ["D-BROWSER-TRIAL"]}
repo.state["ocr_parse_results"].append({"tenantId": "TENANT-DEFAULT", "documentVersionId": "D-BROWSER-TRIAL", "fields": [
    {"id": "F-BROWSER-TRIAL", "fieldName": "thickness", "value": 11, "unit": "mm", "pageNo": 1, "bbox": [0, 0, 10, 10]}]})
trial_run["documentScopeSnapshot"] = freeze_document_scope(trial_run, repo.state)
repo.state["review_runs"].append(trial_run)
for index in range(1, 24):
    document_id, version_id = f"DOC-PICK-{index}", f"VER-PICK-{index}"
    repo.state["documents"].append({"id": document_id, "projectId": "P-2026-HDCP-001",
        "tenantId": "TENANT-DEFAULT", "currentVersionId": version_id, "fileName": f"LAB-PICK-{index:02}.txt",
        "fileType": "txt", "fileStatus": "已上传", "currentOcrStatus": "待识别", "sourceOrgName": "本地测试",
        "uploaderName": "测试", "poolSubmissionStatus": "已提交"})
    repo.state["versions"].append({"id": version_id, "documentId": document_id, "tenantId": "TENANT-DEFAULT",
        "hash": f"fixture-{index}" if index != 23 else None, "versionNo": 1, "isCurrent": True, "ocrStatus": "待识别"})
client = TestClient(app)


class Handler(BaseHTTPRequestHandler):
    def forward(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        response = client.request(self.command, self.path, content=body,
            headers={"Content-Type": "application/json", "X-Role": "inspection", "X-User-Id": "USER-INSPECTION-001",
                     **{key: value for key, value in self.headers.items() if key.lower() in {"if-match", "idempotency-key"}}})
        self.send_response(response.status_code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(response.content)

    do_GET = forward
    do_POST = forward
    do_PATCH = forward


HTTPServer(("127.0.0.1", 4174), Handler).serve_forever()
