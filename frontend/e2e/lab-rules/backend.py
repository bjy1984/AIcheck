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
import base64
import tempfile
from pathlib import Path
from apps.api import routes
originals = tempfile.TemporaryDirectory(prefix="aicheck-version-browser-")
routes.WORKSPACE_ROOT = Path(originals.name)
(Path(originals.name) / "historical.png").write_bytes(base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j1ioAAAAASUVORK5CYII="))
import fitz
with fitz.open() as pdf:
    for page_number in (1, 2):
        page = pdf.new_page(width=420, height=300)
        page.insert_text((30, 70), f"HISTORICAL PDF - PAGE {page_number}", fontsize=20)
        page.insert_text((30, 115), "Version V-PDF: fixed review input", fontsize=14)
    pdf.save(Path(originals.name) / "historical.pdf")
repo.state["versions"].extend([
    {"id": "VER-PICK-1-PDF", "documentId": "DOC-PICK-1", "tenantId": "TENANT-DEFAULT", "versionNo": "V-PDF",
     "fileName": "historical.pdf", "fileType": "application/pdf", "hash": "historical-pdf-fixture", "isCurrent": False,
     "storageKey": "local://historical.pdf"},
    {"id": "VER-PICK-1-OLD", "documentId": "DOC-PICK-1", "tenantId": "TENANT-DEFAULT", "versionNo": "V0",
     "fileName": "historical.png", "fileType": "image/png", "hash": "historical-fixture", "isCurrent": False,
     "storageKey": "local://historical.png"},
    {"id": "VER-PICK-1-EMPTY", "documentId": "DOC-PICK-1", "tenantId": "TENANT-DEFAULT", "versionNo": "EMPTY",
     "hash": None, "isCurrent": False}])
from handoff_seed import control as handoff_control, seed as seed_handoffs
seed_handoffs(repo, Path(originals.name))
client = TestClient(app)


class Handler(BaseHTTPRequestHandler):
    def forward(self):
        if self.command == "POST" and self.path.startswith("/__lab/handoff/"):
            try:
                handoff_control(repo, self.path.rsplit("/", 1)[-1])
                self.send_response(200)
            except ValueError:
                self.send_response(400)
            self.end_headers()
            return
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        response = client.request(self.command, self.path, content=body,
            headers={"Content-Type": "application/json", "X-Role": "inspection", "X-User-Id": "USER-INSPECTION-001",
                     **{key: value for key, value in self.headers.items() if key.lower() in {"if-match", "idempotency-key"}}})
        self.send_response(response.status_code)
        self.send_header("Content-Type", response.headers.get("content-type", "application/json"))
        self.end_headers()
        self.wfile.write(response.content)

    do_GET = forward
    do_POST = forward
    do_PATCH = forward


HTTPServer(("127.0.0.1", 4174), Handler).serve_forever()
