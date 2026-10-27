"""The findings `sync` builds are accepted by the real backend handler (in-process FastAPI app, fixture data only).

Needs the backend's virtualenv (FastAPI and the app's dependencies); skipped otherwise. Never talks to a real server.
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[3]
BACKEND = REPO / "backend"
SPEC = importlib.util.spec_from_file_location("node_audit_contract", REPO / "skills/aicheck-node-audit/scripts/node_audit.py")
na = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(na)

# Same defaults as backend/tests/conftest.py: no login, demo fixtures, no outbound calls.
for key, value in {"AICHECK_REQUIRE_AUTH": "false", "AICHECK_REQUIRE_IF_MATCH": "false", "AICHECK_ENABLE_DEMO_DATA": "true",
                   "AICHECK_ENABLE_COMPATIBILITY_MOCKS": "true", "AICHECK_EMBEDDING_FORCE_OFFLINE_HASH": "true",
                   "AICHECK_OCR_PROVIDER_MODE": "local", "AICHECK_OCR_DEFAULT_PROVIDER": "local",
                   "AICHECK_CERT_PLATFORM_VERIFY": "off"}.items():
    os.environ.setdefault(key, value)
# 只用内存：不写本机开发库 backend/data/aicheck.sqlite3，也不连任何数据库。
os.environ["AICHECK_SQLITE_DISABLE"] = "true"
for key in ("AICHECK_SQLITE_PATH", "AICHECK_DATABASE_URL", "DATABASE_URL"):
    os.environ.pop(key, None)

try:
    sys.path.insert(0, str(BACKEND))
    cwd = os.getcwd()
    os.chdir(BACKEND)  # the app resolves fixtures relative to the backend directory
    from fastapi.testclient import TestClient  # noqa: E402
    from apps.api.main import app  # noqa: E402
    from libs.db.repository import repo  # noqa: E402
    BACKEND_OK = True
except Exception:  # noqa: BLE001 -- no backend environment here
    BACKEND_OK = False
finally:
    os.chdir(cwd)

PROJECT, NODE, VERSION, LINK = "P-2026-HDCP-001", 24, "DV-20260625-001-V2", "NEL-SYNC-CONTRACT-24"


@unittest.skipUnless(BACKEND_OK, "backend virtualenv not available")
class SyncBackendContractTest(unittest.TestCase):
    def setUp(self):
        repo.reset()
        repo.sqlite_enabled, repo.sqlite_path = False, None
        repo.state["node_evidence_links"].append({
            "id": LINK, "projectId": PROJECT, "nodeId": NODE, "documentId": "DOC-20260625-001", "documentVersionId": VERSION,
            "fileName": "焊工资格证.pdf", "pageNo": 1, "bbox": [10, 20, 180, 42], "quotedText": "证书编号",
            "supportStatus": "supported", "manualStatus": "confirmed", "confidence": 0.9, "createdAt": "2026-10-25 00:00:00"})
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"AICHECK_AUDIT_HOME": str(Path(self.tmp.name) / "audits")})
        self.env.start()
        source = Path(self.tmp.name) / "焊工资格证.pdf"
        source.write_bytes(b"%PDF-1.4 fake\n")
        with contextlib.redirect_stdout(io.StringIO()) as out:
            na.main(["local-init", "--node", str(NODE), "--files", str(source), "--out", str(Path(self.tmp.name) / "b")])
        self.bundle = Path(json.loads(out.getvalue())["data"]["bundle"])
        manifest = json.loads((self.bundle / "bundle.json").read_text(encoding="utf-8"))
        manifest.update(source="server", projectId=PROJECT, baseUrl="http://server.example")
        manifest["files"][0]["documentVersionId"] = VERSION
        (self.bundle / "bundle.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()):
            na.main(["skeleton", "--bundle", str(self.bundle)])
        report = json.loads((self.bundle / "audit.json").read_text(encoding="utf-8"))
        cert = manifest["files"][0]["path"]
        for check in report["checks"]:
            if check["atomicCheckId"] == "AC-R24-01":
                check.update(verdict="failed", reasoning="证书有效期早于施工期，已过期。",
                             facts=[{"name": "有效期至", "value": "2025-12", "source": {"file": cert, "page": 1, "excerpt": "证书编号"}}])
            elif check["atomicCheckId"] == "AC-R24-05":
                check.update(verdict="evidence_insufficient", reason="其余项证据不足。")
            else:
                check.update(verdict="evidence_insufficient", reason="缺施焊记录。",
                             facts=[{"name": "持证项目", "value": "GTAW", "source": {"file": cert, "page": 1, "excerpt": "证书编号"}}])
        report["reviewedFiles"][0].update(method="read", pages="1")
        (self.bundle / "audit.json").write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()
        repo.reset()

    def test_server_accepts_the_synced_findings_and_a_reviewer_can_accept_one(self):
        chain = {"links": [{"id": LINK, "documentVersionId": VERSION, "manualStatus": "confirmed", "pageNo": 1, "bbox": [10, 20, 180, 42],
                           "quotedText": "证书编号"}]}
        plan = na.sync_plan(self.bundle, chain)
        self.assertEqual({item["check"] for item in plan["create"]}, {"AC-R24-01", "AC-R24-02", "AC-R24-03", "AC-R24-04"})
        client = TestClient(app)
        created = []
        for item in plan["create"]:
            response = client.post("/api/review/findings", json=item["body"], headers={"Idempotency-Key": item["idempotencyKey"]})
            payload = response.json()
            self.assertEqual(payload.get("code"), 0, payload)
            finding = payload["data"]["finding"]
            self.assertEqual((finding["source"], finding["status"], finding["humanStatus"]), ("ai", "draft", "pending_human_review"))
            self.assertEqual(finding["evidenceLinkIds"], [LINK])
            created.append(finding)
        node = next(n for n in repo.state["tree_nodes"] if n.get("projectId") == PROJECT and int(n["nodeId"]) == NODE)
        status_before = node.get("status")
        again = client.post("/api/review/findings", json=plan["create"][0]["body"],
                            headers={"Idempotency-Key": plan["create"][0]["idempotencyKey"]}).json()
        self.assertEqual(again["data"]["finding"]["id"], created[0]["id"])  # 同一幂等键不重复建
        self.assertEqual(sum(1 for f in repo.state["review_findings"] if f["id"] in {c["id"] for c in created}), len(created))
        self.assertEqual(node.get("status"), status_before)  # 写 AI 发现不改节点状态
        accepted = client.post(f"/api/review/findings/{created[0]['id']}/accept", json={"result": "需补正"},
                               headers={"Idempotency-Key": "sync-contract-accept"}).json()
        self.assertEqual(accepted.get("code"), 0, accepted)
        self.assertEqual(accepted["data"]["finding"]["status"], "accepted")


if __name__ == "__main__":
    unittest.main()
