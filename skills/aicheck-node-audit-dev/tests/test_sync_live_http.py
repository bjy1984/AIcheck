"""`node_audit.py sync` end to end over real HTTP against a locally started backend (auth on, fixture data only).

Starts the real FastAPI app with uvicorn on 127.0.0.1, logs in with a test token, previews and confirms a sync through
the command line exactly as a user would, then reads the findings back through the review workbench API.
Needs the backend's virtualenv (FastAPI, uvicorn); skipped otherwise. Never talks to a real server.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
BACKEND = REPO / "backend"
SCRIPT = REPO / "skills/aicheck-node-audit/scripts/node_audit.py"
PROJECT, NODE, VERSION, LINK = "P-2026-HDCP-001", 24, "DV-20260625-001-V2", "NEL-SYNC-LIVE-24"
TOKEN = "dev-token-inspection"

for key, value in {"AICHECK_REQUIRE_AUTH": "true", "AICHECK_ALLOW_DEV_TOKENS": "true", "AICHECK_ENABLE_DEMO_USERS": "true",
                   "AICHECK_REQUIRE_IF_MATCH": "false", "AICHECK_ENABLE_DEMO_DATA": "true", "AICHECK_ENABLE_COMPATIBILITY_MOCKS": "true",
                   "AICHECK_EMBEDDING_FORCE_OFFLINE_HASH": "true", "AICHECK_OCR_PROVIDER_MODE": "local",
                   "AICHECK_OCR_DEFAULT_PROVIDER": "local", "AICHECK_CERT_PLATFORM_VERIFY": "off"}.items():
    os.environ.setdefault(key, value)
# 只用内存：不写本机开发库 backend/data/aicheck.sqlite3，也不连任何数据库。
os.environ["AICHECK_SQLITE_DISABLE"] = "true"
for key in ("AICHECK_SQLITE_PATH", "AICHECK_DATABASE_URL", "DATABASE_URL"):
    os.environ.pop(key, None)
try:
    sys.path.insert(0, str(BACKEND))
    cwd = os.getcwd()
    os.chdir(BACKEND)
    import uvicorn  # noqa: E402
    from apps.api.main import app  # noqa: E402
    from libs.db.repository import repo  # noqa: E402
    BACKEND_OK = True
except Exception:  # noqa: BLE001
    BACKEND_OK = False
finally:
    os.chdir(cwd)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def cli(*argv: str, env: dict) -> dict:
    done = subprocess.run([sys.executable, str(SCRIPT), *argv], capture_output=True, text=True, env=env, timeout=120, check=False)
    return json.loads(done.stdout)


@unittest.skipUnless(BACKEND_OK, "backend virtualenv not available")
class SyncLiveHttpTest(unittest.TestCase):
    def setUp(self):
        repo.reset()
        repo.sqlite_enabled, repo.sqlite_path = False, None
        self.port = free_port()
        self.server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=self.port, log_level="warning"))
        threading.Thread(target=self.server.run, daemon=True).start()
        for _ in range(900):  # 后端启动要加载业务包和演示数据
            if self.server.started:
                break
            time.sleep(0.1)
        if not self.server.started:
            self.fail("local backend did not start within 90 s")
        # 启动时会重新载入演示数据，所以确认过的证据链接要在启动之后加。
        repo.state["node_evidence_links"].append({
            "id": LINK, "projectId": PROJECT, "nodeId": NODE, "documentId": "DOC-20260625-001", "documentVersionId": VERSION,
            "fileName": "焊工资格证.pdf", "pageNo": 1, "bbox": [10, 20, 180, 42], "quotedText": "证书编号",
            "supportStatus": "supported", "manualStatus": "confirmed", "confidence": 0.9, "createdAt": "2026-10-25 00:00:00"})
        self.base = f"http://127.0.0.1:{self.port}"
        self.tmp = tempfile.TemporaryDirectory()
        home = Path(self.tmp.name)
        self.env = {**os.environ, "AICHECK_AUDIT_HOME": str(home / "audits"), "AICHECK_SESSION_FILE": str(home / "session.json"),
                    "AICHECK_BASE_URL": self.base, "AICHECK_TOKEN": TOKEN, "PYTHONDONTWRITEBYTECODE": "1"}
        source = home / "焊工资格证.pdf"
        source.write_bytes(b"%PDF-1.4 fake\n")
        self.bundle = Path(cli("local-init", "--node", str(NODE), "--files", str(source), "--out", str(home / "b"), env=self.env)["data"]["bundle"])
        manifest = json.loads((self.bundle / "bundle.json").read_text(encoding="utf-8"))
        manifest.update(source="server", projectId=PROJECT, baseUrl=self.base)  # as if fetched from this server
        manifest["files"][0]["documentVersionId"] = VERSION
        (self.bundle / "bundle.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        cli("skeleton", "--bundle", str(self.bundle), env=self.env)
        report = json.loads((self.bundle / "audit.json").read_text(encoding="utf-8"))
        cert = manifest["files"][0]["path"]
        for check in report["checks"]:
            if check["atomicCheckId"] == "AC-R24-01":
                check.update(verdict="failed", reasoning="证书有效期早于施工期，已过期。",
                             facts=[{"name": "有效期至", "value": "2025-12", "source": {"file": cert, "page": 1, "excerpt": "证书编号"}}])
            else:
                check.update(verdict="evidence_insufficient", reason="缺施焊记录。")
        report["reviewedFiles"][0].update(method="read", pages="1")
        (self.bundle / "audit.json").write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")

    def tearDown(self):
        self.server.should_exit = True
        time.sleep(0.3)
        self.tmp.cleanup()
        repo.reset()

    def test_preview_then_confirm_over_http_then_read_back(self):
        report = cli("report", "--bundle", str(self.bundle), env=self.env)
        self.assertTrue(report["ok"], report)
        self.assertEqual((report["data"]["outcome"], report["data"]["syncAvailable"]), ("不通过", True))

        preview = cli("sync", "--bundle", str(self.bundle), env=self.env)
        self.assertTrue(preview["ok"], preview)
        self.assertTrue(preview["data"]["preview"])
        self.assertEqual([i["check"] for i in preview["data"]["willCreate"]], ["AC-R24-01"])  # 只有它引用了已确认证据
        before = [f for f in repo.state["review_findings"] if f.get("projectId") == PROJECT and f.get("source") == "ai"
                  and f.get("findingType") == "ai_node_audit"]
        self.assertEqual(before, [])  # 预览不写

        done = cli("sync", "--bundle", str(self.bundle), "--confirm", "--preview-hash", preview["data"]["previewHash"], env=self.env)
        self.assertTrue(done["ok"], done)
        self.assertEqual(done["data"]["synced"], 1, done)

        req = urllib.request.Request(f"{self.base}/api/projects/{PROJECT}/review-workbench?nodeId={NODE}",
                                     headers={"Authorization": f"Bearer {TOKEN}", "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            workbench = json.loads(resp.read())["data"]
        synced = [f for f in workbench["findings"] if f.get("findingType") == "ai_node_audit"]
        self.assertEqual(len(synced), 1)
        self.assertEqual((synced[0]["source"], synced[0]["status"], synced[0]["humanStatus"]), ("ai", "draft", "pending_human_review"))
        self.assertEqual(synced[0]["evidenceLinkIds"], [LINK])

        unauth = dict(self.env, AICHECK_TOKEN="dev-token-contractor")  # 施工方账号不能写审查发现
        refused = cli("sync", "--bundle", str(self.bundle), "--confirm", "--preview-hash", preview["data"]["previewHash"], env=unauth)
        self.assertTrue(not refused["ok"] or refused["data"]["failed"], refused)


if __name__ == "__main__":
    unittest.main()
