"""Loopback-only real API harness; in-memory data, temporary files, optional live providers.

Run from repository root: PYTHONPATH=backend backend/.venv/bin/python frontend/e2e/important-review/backend.py
Only --live-providers reads the model/MinerU credential subset from backend/.env.
It never loads database, storage or production authentication configuration.
"""
import argparse
import json
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--live-providers", action="store_true")
args = parser.parse_args()
root = Path(__file__).resolve().parents[3]
for name in list(os.environ):
    if name.startswith(("AICHECK_", "QWEN_", "LITELLM_", "MINIO_", "REDIS_", "CELERY_", "TEMPORAL_")) or name == "DATABASE_URL":
        del os.environ[name]
if args.live_providers:
    for line in (root / "backend/.env").read_text().splitlines():
        name, sep, value = line.partition("=")
        if sep and name.startswith(("AICHECK_LLM_", "AICHECK_MINERU_", "QWEN_")):
            os.environ[name] = value
os.environ.update({
    "AICHECK_REQUIRE_AUTH": "true", "AICHECK_REQUIRE_IF_MATCH": "false",
    "AICHECK_ENABLE_DEMO_DATA": "true", "AICHECK_ENABLE_DEMO_USERS": "true",
    "AICHECK_ENABLE_COMPATIBILITY_MOCKS": "true", "AICHECK_ALLOW_DEV_TOKENS": "true",
    "AICHECK_WORKSTATIONS_ENABLED": "true", "AICHECK_REVIEW_ORCHESTRATION": "inline",
    "AICHECK_REVIEW_LLM_EXECUTION": "litellm" if args.live_providers else "deterministic",
    "AICHECK_QWEN_CALL_MODE": "official_api", "AICHECK_CERT_PLATFORM_VERIFY": "off",
    "AICHECK_EMBEDDING_FORCE_OFFLINE_HASH": "true", "AICHECK_LANGGRAPH_CHECKPOINT_DISABLE": "true",
    "AICHECK_MINERU_JOB_TIMEOUT_SECONDS": "240", "AICHECK_MINERU_TIMEOUT_SECONDS": "45",
})

import fitz
from fastapi.testclient import TestClient

from apps.api import routes as api
from apps.api.main import app
from libs.db.repository import repo
from libs.review_orchestrator import execution as execution
from libs.review_orchestrator.dispatcher import prepare_review_run_for_async_dispatch

repo.reset()
repo.postgres_enabled = repo.sqlite_enabled = False
repo.postgres_dsn = repo.sqlite_path = repo.sync_postgres = None
temporary = tempfile.TemporaryDirectory(prefix="important-review-api-")
workspace = Path(temporary.name)
api.WORKSPACE_ROOT = workspace
api.DOCUMENT_UPLOAD_ROOT = workspace / "output/document_uploads"
pool = ThreadPoolExecutor(max_workers=1)
report = {"liveProviders": args.live_providers, "ocr": [], "reviews": [], "errors": []}
sample = workspace / "专项审查联调样本.pdf"
with fitz.open() as pdf:
    for title, body in [
        ("专项审查联调样本（非真实工程）", "设计文件批准程序\n工程：联调测试工程\n设计单位：联调测试设计单位\n文件编号：TEST-DESIGN-001\n版本：A\n编制：测试人员\n审核栏：空白\n批准栏：空白\n本页未提供签字或设计专用章。"),
        ("专项审查联调样本 第2页", "本资料仅用于软件联调。\n本文件不包含施工图审查证明、计算书和设计变更记录。\n资料缺失时应提示补充，不可默认符合。"),
    ]:
        page = pdf.new_page(width=595, height=842)
        page.insert_text((45, 65), title, fontname="china-s", fontsize=18)
        page.insert_text((45, 115), body, fontname="china-s", fontsize=14)
    pdf.save(sample)


def parse_document(document_id, version_id, storage_key, file_name=None):
    def work():
        try:
            path = api.local_upload_artifact_path(storage_key)
            if args.live_providers:
                from libs.integrations.mineru_client import MinerUClient
                from libs.mineru_ocr import normalize_mineru_zip
                provider = MinerUClient()
                submission = provider.submit_file(path, data_id=version_id, options={})
                status = provider.wait_for_result(submission)
                bundle = normalize_mineru_zip(provider.download_result(status["full_zip_url"]),
                    storage_key=storage_key, file_name=file_name, profile_id=None,
                    document_type=None, provider_task_id=submission["providerTaskId"])
                result = bundle.result
                provider.client.close()
            else:
                with fitz.open(path) as pdf:
                    result = {"status": "success", "outcomeStatus": "completed", "pageCount": len(pdf),
                        "fields": [], "tables": [], "seals": [],
                        "fragments": [{"pageNo": index + 1, "text": page.get_text(), "bbox": [0, 0, 595, 842], "confidence": 1}
                                      for index, page in enumerate(pdf)]}
            job = repo.create_ocr_job_record(document_id=document_id, version_id=version_id,
                storage_key=storage_key, file_name=file_name)
            repo.finish_ocr_job_record(job, result)
            repo.apply_ocr_result(document_id, version_id, result)
            report["ocr"].append({"versionId": version_id, "status": result["status"], "fragments": len(result.get("fragments") or [])})
        except Exception as error:
            report["errors"].append({"stage": "ocr", "type": type(error).__name__, "code": getattr(error, "code", "")})
            repo.find_one("documents", document_id)["currentOcrStatus"] = "识别失败"
    pool.submit(work)
    return {"mode": "isolated-thread", "taskId": f"OCR-{version_id}"}


def dispatch_review(project_id, node_id, run_id, **kwargs):
    assert kwargs.get("force_async") is True
    run = prepare_review_run_for_async_dispatch(run_id)
    def work():
        try:
            outcome = execution.execute_review_run_inline(run["reviewRunId"])
            report["reviews"].append({"nodeId": node_id, "status": outcome.get("status"),
                "errorCode": run.get("errorCode"), "llmCalled": bool((run.get("llmMetadata") or {}).get("llmCalled")),
                "skillFrozen": bool(run.get("importantReviewSnapshot")),
                "findingCount": len(run.get("findingDrafts") or [])})
        except Exception as error:
            report["errors"].append({"stage": "review", "type": type(error).__name__})
    pool.submit(work)
    return {"mode": "isolated-thread", "status": "queued", "reviewRunId": run["reviewRunId"]}


api.task_dispatcher.dispatch_parse_document = parse_document
api.task_dispatcher.ai_recheck_dispatch_readiness = lambda: {"ready": True, "mode": "isolated-thread"}
api.task_dispatcher.dispatch_ai_recheck = dispatch_review
client = TestClient(app)


class Handler(BaseHTTPRequestHandler):
    def forward(self):
        path = urlparse(self.path).path
        if path == "/__important_test/report":
            content, status, content_type = json.dumps(report).encode(), 200, "application/json"
        elif path == "/__important_test/sample.pdf":
            content, status, content_type = sample.read_bytes(), 200, "application/pdf"
        else:
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            response = client.request(self.command, self.path, content=body,
                headers={key: value for key, value in self.headers.items() if key.lower() not in {"host", "content-length", "connection", "accept-encoding"}})
            content, status = response.content, response.status_code
            content_type = response.headers.get("content-type", "application/json")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = forward

    def log_message(self, format, *args):
        pass  # Do not log signed upload URLs or credentials.


print("Isolated real API ready at 127.0.0.1:4410", flush=True)
ThreadingHTTPServer(("127.0.0.1", 4410), Handler).serve_forever()
