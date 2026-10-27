"""Node audit helper against a fake AIcheck server; no real accounts or project data."""
from __future__ import annotations

import base64
import contextlib
import importlib.util
import io
import json
import os
import stat
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

SPEC = importlib.util.spec_from_file_location("node_audit_under_test", Path(__file__).resolve().parents[2] / "aicheck-node-audit/scripts/node_audit.py")
na = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(na)

TOKEN = "test-token-not-real"
# 1×1 的合法 PNG：服务器渲染接口的测试桩返回它
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
PDF = b"%PDF-1.4 fake certificate\n"
WORKSPACE_FLAT = {
    "node": {"nodeId": 24},
    "submission": {"documents": [{
        "id": "DOC-1", "fileName": "焊工证/张三.pdf", "currentVersionId": "V-2", "materialTypeCode": "welder_certificate",
        "ocrReadiness": {"status": "ready"},
        "bindings": [{"documentVersionId": "V-1", "requirementName": "焊工资格证", "bindingStatus": "已提交"}],
    }]},
    "ocr": {"extractedFields": [{"documentVersionId": "V-1", "fieldName": "证书编号", "fieldValue": "TS-1|2", "pageNo": 2, "confidence": 0.0}]},
    "evidence": {"readiness": {"readyForAiFormal": False, "missingCount": 1, "blockingReasons": [{"code": "X", "message": "缺施焊记录"}]}},
    "aiReview": {"reviewRuns": [{"reviewRunId": "RRUN-OLD", "updatedAt": "2026-09-01"},
                                {"reviewRunId": "RRUN-NEW", "updatedAt": "2026-10-01"}]},
}
# 服务器真实返回（2026-10 对生产只读核对）：外层是 schemaVersion/project/node/items 等，
# 资料、OCR、证据、AI 审查在 content 下；只有 include_content 的接口才有 content。
WORKSPACE = {
    "schemaVersion": "InspectionAuditWorkspace@1.0.0", "project": {"id": "P-T"}, "node": WORKSPACE_FLAT["node"],
    "items": [], "latestActivityAt": None, "dataAsOf": "2026-10-26T00:00:00+08:00", "businessBasis": {},
    "content": {k: v for k, v in WORKSPACE_FLAT.items() if k != "node"},
}


class FakeServer:
    def __init__(self):
        self.requests: list[tuple[str, str, dict]] = []
        self.server_rule = {"sourceRuleId": "R26", "nodeIds": [24]}
        self.gateway_failures = 0  # 下一次登记查询先回几次 502
        self.registry_unavailable = 0  # 下一次登记查询先回几次 503（公示平台暂不可查询）
        self.workspace = WORKSPACE
        # 服务器 OCR 接口的测试桩：上传、查状态、取结果（同 apps/api/mineru_ocr_routes）
        self.ocr_uploads: list[tuple[dict, bytes]] = []  # (请求头, 正文)
        self.ocr_jobs: dict[str, str] = {}  # Idempotency-Key → jobId
        self.ocr_running_polls = 0  # 状态查询先回几次 running
        self.ocr_final = {"status": "success", "provider": "mineru"}
        self.ocr_result: dict = {}
        self.image_mode = "png"  # png | missing（服务器没部署）| auth200（HTTP 200 里藏着没登录的 JSON）| garbled（页内容不是 PNG）
        self.image_pages = 1  # 服务器这次渲染出几页
        self.image_requests: list[dict] = []
        self.image_gateway_failures = 0
        self.ocr_status_failures = 0  # 查状态、取结果先回几次 502（API 重启中）
        self.ocr_upload_failures = 0  # 上传先回几次 502
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def send_json(self, data=None, status=200, code=0, message=None):
                raw = json.dumps({"code": code, "data": data, "message": message}).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def record(self, method):
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length)) if length else None
                outer.requests.append((method, self.path, {**dict(self.headers), "_body": body}))
                return urlsplit(self.path).path, body

            def authed(self):
                if self.headers.get("Authorization") != f"Bearer {TOKEN}":
                    self.send_json(None, status=401, code="UNAUTHORIZED", message="未登录")
                    return False
                return True

            def do_GET(self):
                path, _ = self.record("GET")
                node = "/api/projects/P-T/inspection/nodes/24"
                if path == "/storage/blob":
                    self.send_response(200)
                    self.send_header("Content-Type", "application/pdf")
                    self.end_headers()
                    self.wfile.write(PDF)
                    return
                if path == "/api/inspection-services/standards":
                    self.send_json({"items": [{"fileId": "KF-1", "text": "表" * 5000, "standardContentArguments": {"fileId": "KF-1"}}]})
                    return
                if not self.authed():
                    return
                if path.startswith("/api/internal/ocr/mineru/tasks/") and outer.ocr_status_failures > 0:
                    outer.ocr_status_failures -= 1
                    self.send_json(None, status=502, code="BAD_GATEWAY", message="Bad Gateway")
                    return
                if path.startswith("/api/internal/ocr/mineru/tasks/") and path.endswith("/result"):
                    self.send_json(outer.ocr_result)
                    return
                if path.startswith("/api/internal/ocr/mineru/tasks/"):
                    running = outer.ocr_running_polls > 0
                    outer.ocr_running_polls -= 1 if running else 0
                    self.send_json({"jobId": path.rsplit("/", 1)[-1], "recommendedPollSeconds": 0,
                                    **({"status": "running", "provider": "mineru", "statusMessage": "MinerU 正在处理文件。"}
                                       if running else outer.ocr_final)})
                    return
                if path == f"{node}/audit-workspace":
                    self.send_json(outer.workspace)
                elif path == f"{node}/rules/current-version":
                    self.send_json({"rule": outer.server_rule})
                elif path == f"{node}/standards":
                    self.send_json([{"standardName": "TSG D7006", "clauseNo": "D2.6.1"}])
                elif path == f"{node}/evidence-chain":
                    self.send_json(None, status=403, code="FORBIDDEN", message="无权")
                elif path == "/api/review-runs/RRUN-NEW":
                    self.send_json({"run": {"reviewRunId": "RRUN-NEW", "atomicCheckOutcomes": [
                        {"atomicCheckId": "AC-R24-01", "result": "evidence_insufficient", "decisionSource": "rule_engine"},
                        {"atomicCheckId": "AC-R24-05", "result": "passed", "decisionSource": "rule_engine"}]}})
                elif path == "/api/projects/P-T/documents/DOC-1/original":
                    self.send_response(302)
                    self.send_header("Location", "/storage/blob")
                    self.end_headers()
                else:
                    self.send_json(None, status=404, code="NOT_FOUND", message="无此接口")

            def do_POST(self):
                if urlsplit(self.path).path == "/api/inspection-services/audit-result-image":
                    _, image_body = self.record("POST")
                    if outer.image_gateway_failures > 0:
                        outer.image_gateway_failures -= 1
                        self.send_json(None, status=502, code="BAD_GATEWAY", message="Bad Gateway")
                    elif outer.image_mode == "auth200":
                        self.send_json({"reason": "AUTH_REQUIRED"}, status=200, code=401, message="请先登录。")
                    elif not self.authed():
                        pass
                    elif outer.image_mode == "missing":
                        self.send_json(None, status=404, code="NOT_FOUND", message="无此接口")
                    else:
                        outer.image_requests.append(image_body)
                        content = b"not a png" if outer.image_mode == "garbled" else PNG
                        pages = [{"pageNo": n, "imageBase64": base64.b64encode(content + bytes([n])).decode()}
                                 for n in range(1, outer.image_pages + 1)]
                        self.send_json({"pageCount": len(pages), "contentType": "image/png", "pages": pages})
                    return
                if urlsplit(self.path).path == "/api/internal/ocr/mineru/tasks/upload":
                    length = int(self.headers.get("Content-Length") or 0)
                    raw = self.rfile.read(length)
                    outer.requests.append(("POST", self.path, dict(self.headers)))
                    if not self.authed():
                        return
                    if outer.ocr_upload_failures > 0:
                        outer.ocr_upload_failures -= 1
                        self.send_json(None, status=502, code="BAD_GATEWAY", message="Bad Gateway")
                        return
                    key = self.headers.get("Idempotency-Key")
                    outer.ocr_uploads.append((dict(self.headers), raw))
                    job = outer.ocr_jobs.setdefault(key, f"OCRJ-{len(outer.ocr_jobs) + 1}")
                    self.send_json({"jobId": job, "status": "queued", "recommendedPollSeconds": 0})
                    return
                path, body = self.record("POST")
                if path == "/api/inspection-services/certificate-registry" and outer.gateway_failures:
                    outer.gateway_failures -= 1
                    self.send_json(None, status=502, code="BAD_GATEWAY", message="Bad Gateway")
                elif path == "/api/inspection-services/certificate-registry" and outer.registry_unavailable:
                    outer.registry_unavailable -= 1
                    self.send_json(None, status=503, code="REGISTRY_UNAVAILABLE", message="登记平台暂不可查询")
                elif path == "/api/inspection-services/certificate-registry" and body.get("identifier") == "TS9999999-2030":
                    self.send_json(None, status=503, code="REGISTRY_UNAVAILABLE", message="登记平台暂不可查询")
                elif path == "/api/inspection-services/certificate-registry" and body["kind"] == "person":
                    self.send_json({"kind": "person", "records": {"person": {"xm": "张三", "sfzh": body["identifier"]},
                                                                  "licenses": [{"zsbh": body["identifier"], "khdw": "某考核机构"}]}})
                elif path == "/api/inspection-services/certificate-registry":
                    self.send_json({"kind": body["kind"], "records": [], "authenticityConclusion": "manual_confirmation_required"})
                else:
                    self.send_json(None, status=404, code="NOT_FOUND")

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def run(*argv: str) -> tuple[int, dict]:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = na.main(list(argv))
    return code, json.loads(out.getvalue())


class NodeAuditTest(unittest.TestCase):
    def setUp(self):
        self.server = FakeServer()
        self.tmp = tempfile.TemporaryDirectory()
        home = Path(self.tmp.name)
        self.session = home / "session.json"
        self.env = patch.dict(os.environ, {"AICHECK_AUDIT_HOME": str(home / "audits"), "AICHECK_SESSION_FILE": str(self.session),
                                           "AICHECK_BASE_URL": self.server.url}, clear=False)
        self.env.start()
        for key in ("AICHECK_TOKEN", "AICHECK_ALLOW_HTTP"):
            os.environ.pop(key, None)

    def tearDown(self):
        self.env.stop()
        self.server.close()
        self.tmp.cleanup()

    def login(self):
        na.write_private(self.session, json.dumps({"baseUrl": self.server.url, "token": TOKEN}))

    def test_rules_cover_all_69_nodes(self):
        total = sum(len(na.rule_catalog(node)["atomicChecks"]) for node in range(1, 70))
        self.assertEqual(total, 194)
        catalog = na.rule_catalog(24)
        self.assertEqual(catalog["ruleId"], "R24")
        self.assertIn("verify_welder_on_platform", catalog["atomicChecks"][0]["serverTools"])

    def test_fetch_requires_login(self):
        code, out = run("fetch", "--project", "P-T", "--node", "24")
        self.assertEqual(code, 1)
        self.assertEqual(out["error"]["code"], "loginRequired")
        self.assertFalse(any(path.startswith("/api/projects") for _, path, _ in self.server.requests))

    def test_fetch_builds_bundle(self):
        self.login()
        out_dir = Path(self.tmp.name) / "bundle"
        code, out = run("fetch", "--project", "P-T", "--node", "24", "--out", str(out_dir))
        self.assertEqual(code, 0, out)
        manifest = json.loads((out_dir / "bundle.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["source"], "server")
        self.assertEqual(manifest["atomicChecks"], [f"AC-R24-0{i}" for i in range(1, 6)])
        self.assertEqual(manifest["serverOutcomes"]["AC-R24-01"]["result"], "evidence_insufficient")
        self.assertEqual(manifest["serverOutcomes"]["AC-R24-01"]["reviewRunId"], "RRUN-NEW")
        [file] = manifest["files"]
        self.assertEqual(file["path"], "files/01-焊工证_张三.pdf")
        self.assertEqual((out_dir / file["path"]).read_bytes(), PDF)
        self.assertEqual(file["documentVersionId"], "V-1")
        warnings = " ".join(manifest["warnings"])
        self.assertIn("服务器规则与节点不一致", warnings)
        self.assertIn("evidenceChain", warnings)
        self.assertEqual(stat.S_IMODE((out_dir / "bundle.json").stat().st_mode), 0o600)
        digest = (out_dir / "digest.md").read_text(encoding="utf-8")
        self.assertIn("AC-R24-05", digest)
        self.assertIn("TS-1\\|2", digest)
        # 服务器把内容放在 content 下：包里的 workspace.json 已摊平，文件、OCR 字段、服务器结论都读得到。
        stored = json.loads((out_dir / "workspace.json").read_text(encoding="utf-8"))
        self.assertNotIn("content", stored)
        self.assertEqual({"submission", "ocr", "evidence", "aiReview"} - set(stored), set())
        self.assertNotIn("接口结构可能变了", warnings)
        # 挂载版本而不是当前版本；令牌不跟着跳转去对象存储。
        original = next(r for r in self.server.requests if r[1].startswith("/api/projects/P-T/documents/DOC-1/original"))
        self.assertEqual(parse_qs(urlsplit(original[1]).query)["versionId"], ["V-1"])
        blob = next(r for r in self.server.requests if r[1] == "/storage/blob")
        self.assertNotIn("Authorization", blob[2])

    def test_flatten_workspace_accepts_nested_and_flat(self):
        flat = na.flatten_workspace(WORKSPACE)
        self.assertNotIn("content", flat)
        self.assertEqual(flat["submission"]["documents"][0]["id"], "DOC-1")
        self.assertEqual(flat["project"], {"id": "P-T"})  # 外层的键保留
        self.assertIs(na.flatten_workspace(WORKSPACE_FLAT), WORKSPACE_FLAT)  # 本地 --workspace 模拟文件是平铺的
        self.assertEqual(na.flatten_workspace(None), {})
        self.assertEqual(na.flatten_workspace({"content": None, "node": 1}), {"content": None, "node": 1})

    def test_fetch_warns_when_workspace_shape_unknown(self):
        self.login()
        self.server.workspace = {"schemaVersion": "InspectionAuditWorkspace@2.0.0", "node": {"nodeId": 24}, "body": {"documents": []}}
        out_dir = Path(self.tmp.name) / "bundle-unknown"
        code, out = run("fetch", "--project", "P-T", "--node", "24", "--out", str(out_dir))
        self.assertEqual(code, 0, out)
        manifest = json.loads((out_dir / "bundle.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["files"], [])
        self.assertTrue(any("接口结构可能变了" in w for w in manifest["warnings"]), manifest["warnings"])

    def test_token_not_sent_to_other_server(self):
        na.write_private(self.session, json.dumps({"baseUrl": "http://127.0.0.1:1", "token": TOKEN}))
        code, out = run("fetch", "--project", "P-T", "--node", "24")
        self.assertEqual(out["error"]["code"], "loginRequired")

    def test_remote_http_needs_opt_in(self):
        with self.assertRaises(na.ClientError) as ctx:
            na.normalize_base("http://203.0.113.5:8081/api/")
        self.assertEqual(ctx.exception.code, "insecureTransport")
        with patch.dict(os.environ, {"AICHECK_ALLOW_HTTP": "1"}):
            self.assertEqual(na.normalize_base("http://203.0.113.5:8081/api/"), "http://203.0.113.5:8081")

    def test_login_refuses_without_tty(self):
        with patch("sys.stdin", io.StringIO("")):
            code, out = run("login", "--username", "inspector")
        self.assertEqual(out["error"]["code"], "ttyRequired")

    def test_cert_registry_validates_and_opts_in(self):
        code, out = run("cert-registry", "--kind", "person", "--identifier", "123")
        self.assertEqual(out["error"]["code"], "invalidArguments")
        self.assertEqual(self.server.requests, [])
        code, out = run("cert-registry", "--kind", "organization_license", "--identifier", "ts1234567-2030")
        self.assertEqual(code, 0, out)
        body = self.server.requests[-1][2]["_body"]
        self.assertEqual(body, {"kind": "organization_license", "identifier": "TS1234567-2030", "allowExternalQuery": True})
        self.assertNotIn("Authorization", self.server.requests[-1][2])

    def test_licence_number_with_letters_is_explained_not_sent(self):
        code, out = run("cert-registry", "--kind", "organization_license", "--identifier", "TS2710A12-2030")
        self.assertEqual(out["error"]["code"], "unsupportedLicenceFormat")
        self.assertIn("公示信息查询平台", out["error"]["message"])
        self.assertEqual(self.server.requests, [])  # 服务器会拒的格式不发

    def sample_file(self) -> Path:
        source = Path(self.tmp.name) / "证书.pdf"
        source.write_bytes(PDF)
        return source

    def local_bundle(self) -> Path:
        source = self.sample_file()
        run_file = Path(self.tmp.name) / "run.json"
        run_file.write_text(json.dumps({"data": {"run": {"reviewRunId": "R-L", "atomicCheckOutcomes": [
            {"atomicCheckId": "AC-R24-01", "result": "passed"}]}}}), encoding="utf-8")
        out_dir = Path(self.tmp.name) / "local"
        code, out = run("local-init", "--node", "24", "--files", str(source), "--out", str(out_dir), "--review-run", str(run_file))
        self.assertEqual(code, 0, out)
        return out_dir

    def write_report(self, bundle: Path, checks: list[dict], reviewed: list[dict] | None = None) -> None:
        if reviewed is None:
            files = json.loads((bundle / "bundle.json").read_text(encoding="utf-8"))["files"]
            reviewed = [{"file": f["path"], "method": "read", "pages": "all"} for f in files]
        report = {"schemaVersion": na.REPORT_SCHEMA, "checks": checks, "reviewedFiles": reviewed}
        (bundle / "audit.json").write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")

    def report_errors(self, bundle: Path) -> str:
        code, out = run("report", "--bundle", str(bundle))
        self.assertEqual(code, 1, out)
        return " ".join(out["error"]["errors"])

    def project_dir(self) -> Path:
        import zipfile
        root = Path(self.tmp.name) / "项目"
        (root / "4、监检合同").mkdir(parents=True)
        (root / "5、施工方案").mkdir()
        (root / "__MACOSX").mkdir()
        (root / "4、监检合同" / "合同.txt").write_text("计划施工时间：2025年11月3日～2026年1月20日", encoding="utf-8")
        with zipfile.ZipFile(root / "5、施工方案" / "方案.docx", "w") as docx:
            docx.writestr("word/document.xml", "<w:document><w:body><w:p><w:r><w:t>本工程主要材质为Q345R。</w:t></w:r></w:p>"
                                               "<w:p><w:r><w:t>电焊工 4 人</w:t></w:r></w:p></w:body></w:document>")
        (root / "焊工证.png").write_bytes(b"\x89PNG fake")
        (root / "5、施工方案" / "~$方案.docx").write_bytes(b"lock")
        (root / ".DS_Store").write_bytes(b"x")
        (root / "__MACOSX" / "._合同.txt").write_bytes(b"x")
        return root

    def test_project_dir_bundle_and_search(self):
        code, out = run("local-init", "--node", "24", "--project-dir", str(self.project_dir()), "--out", str(Path(self.tmp.name) / "pd"))
        self.assertEqual(code, 0, out)
        bundle = Path(out["data"]["bundle"])
        files = json.loads((bundle / "bundle.json").read_text(encoding="utf-8"))["files"]
        self.assertEqual(sorted(f["projectPath"] for f in files), ["4、监检合同/合同.txt", "5、施工方案/方案.docx", "焊工证.png"])
        skipped = json.loads((bundle / "bundle.json").read_text(encoding="utf-8"))["skippedFiles"]
        self.assertEqual(sorted(x["projectPath"] for x in skipped), [".DS_Store", "5、施工方案/~$方案.docx", "__MACOSX/._合同.txt"])
        code, out = run("search", "--bundle", str(bundle))
        self.assertEqual(code, 0, out)
        hits = {Path(f["path"]).name: {x.split(" p")[0] for x in f["termPages"].split("、")} for f in out["data"]["filesWithHits"]}
        self.assertIn("计划施工时间", hits[next(n for n in hits if n.endswith("合同.txt"))])
        self.assertTrue({"材质", "焊工"} <= hits[next(n for n in hits if n.endswith("方案.docx"))])
        self.assertEqual([Path(p).name for p in out["data"]["needsOcr"]], [n for n in (Path(f["path"]).name for f in files) if n.endswith(".png")])
        self.assertEqual(stat.S_IMODE((bundle / out["data"]["saved"]).stat().st_mode), 0o600)
        # 图片只做了检索 = 没看；漏列文件、skipped 不写原因都过不了。
        png = next(f["path"] for f in files if f["path"].endswith(".png"))
        txt = next(f["path"] for f in files if f["path"].endswith(".txt"))
        checks = [{"atomicCheckId": f"AC-R24-0{i}", "verdict": "evidence_insufficient", "reason": "缺施焊记录"} for i in range(1, 6)]
        self.write_report(bundle, checks, [{"file": png, "method": "search"}, {"file": txt, "method": "skipped"}])
        errors = self.report_errors(bundle)
        self.assertIn(f"{png}: 没有文字层也没 OCR，只检索等于没看", errors)
        self.assertIn(f"{txt}: skipped 要写 note", errors)
        self.assertIn("reviewedFiles 缺 1 份文件", errors)

    def test_office_text_heuristics_and_text_command(self):
        table_doc = "序号\x07元件名称\x07规格 Φ89×3.0\x07温度 60°C\x07\n" * 20
        self.assertTrue(na.looks_like_text(table_doc))  # Word 单元格符和 Φ × ° 不算乱码
        self.assertFalse(na.looks_like_text("ˇ\x00\x01\x02ÿ" * 200))
        fake_doc = Path(self.tmp.name) / "not-ole.doc"
        fake_doc.write_bytes(b"plain bytes, not an OLE file")
        with self.assertRaises(ValueError):
            na.word97_text(fake_doc)
        bundle = Path(run("local-init", "--node", "24", "--project-dir", str(self.project_dir()),
                          "--out", str(Path(self.tmp.name) / "tx"))[1]["data"]["bundle"])
        docx = next(f["path"] for f in json.loads((bundle / "bundle.json").read_text(encoding="utf-8"))["files"] if f["path"].endswith(".docx"))
        code, out = run("text", "--file", str(bundle / docx))
        self.assertEqual(code, 0, out)
        saved = Path(out["data"]["saved"])
        self.assertEqual(saved.parent, (bundle / "text").resolve())
        self.assertIn("Q345R", saved.read_text(encoding="utf-8"))
        png = next(f["path"] for f in json.loads((bundle / "bundle.json").read_text(encoding="utf-8"))["files"] if f["path"].endswith(".png"))
        self.assertEqual(run("text", "--file", str(bundle / png))[1]["error"]["code"], "noTextLayer")

    @unittest.skipUnless(importlib.util.find_spec("fitz"), "PyMuPDF 未安装")
    def test_text_refuses_scans_and_repo_files_and_accepts_out_dir(self):
        import fitz
        tmp = Path(self.tmp.name)
        bundle = Path(run("local-init", "--node", "24", "--project-dir", str(self.project_dir()), "--out", str(tmp / "tt"))[1]["data"]["bundle"])
        scan = bundle / "files" / "09-扫描.pdf"
        with fitz.open() as doc:
            doc.new_page()
            doc.new_page()
            doc.save(scan)
        self.assertEqual(run("text", "--file", str(scan))[1]["error"]["code"], "noTextLayer")  # 整份扫描件不能当文字读
        mixed = bundle / "files" / "10-方案.pdf"
        with fitz.open() as doc:
            doc.new_page().insert_text((72, 72), "施工方案 焊接工艺参数表 第一页有足够多的文字内容", fontname="china-s")
            doc.new_page()
            doc.save(mixed)
        code, out = run("text", "--file", str(mixed))
        self.assertEqual((code, out["data"]["pagesWithoutText"]), (0, "2"))
        outside = tmp / "repo" / "rules" / "standards" / "std.pdf"
        outside.parent.mkdir(parents=True)
        outside.write_bytes(mixed.read_bytes())
        self.assertEqual(run("text", "--file", str(outside))[1]["error"]["code"], "outputMissing")
        self.assertFalse((tmp / "repo" / "rules" / "text").exists())  # 不在仓库旁边留下 text/
        out_dir = tmp / "texts"
        out_dir.mkdir()
        self.assertEqual(Path(run("text", "--file", str(outside), "--out", str(out_dir))[1]["data"]["saved"]).parent, out_dir.resolve())
        self.assertEqual(Path(run("text", "--file", str(outside), "--bundle", str(bundle))[1]["data"]["saved"]).parent, (bundle / "text").resolve())

    def test_cert_validity_names_unknown_fields_before_calling_server(self):
        body = {"certificates": [{"certificateNo": "X", "holder": "某", "note": "n"}], "periodStart": "2026-01-01",
                "periodEnd": "2026-02-01", "reasoning": "r"}
        code, out = run("cert-validity", "--json", json.dumps(body, ensure_ascii=False))
        self.assertEqual((code, out["error"]["code"]), (1, "invalidArguments"))
        self.assertIn("reasoning", out["error"]["message"])
        self.assertIn("certificates[].note", out["error"]["message"])
        self.assertEqual(self.server.requests, [])
        self.assertEqual(run("cert-validity", "--json", "{bad")[1]["error"]["code"], "invalidArguments")

    def test_node_group_terms_id_guard_and_risk_flags(self):
        bundle = self.local_bundle()
        terms = na.default_terms(bundle)
        self.assertTrue({"钢印", "焊口", "S30408", "异种钢"} <= set(terms))  # 节点 24 属焊接
        fact = {"name": "持证人", "value": "x", "source": {"file": "files/01-证书.pdf", "page": 1}}
        checks = [{"atomicCheckId": f"AC-R24-0{i}", "verdict": "evidence_insufficient", "reason": "缺记录"} for i in range(1, 6)]
        checks[0]["facts"] = [{**fact, "value": "证件编号 110101199001011237"}]
        self.write_report(bundle, checks)
        report = json.loads((bundle / "audit.json").read_text(encoding="utf-8"))
        report["riskFlags"] = [{"level": "urgent", "flag": "x"}]
        (bundle / "audit.json").write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
        errors = self.report_errors(bundle)
        self.assertIn("完整的 18 位身份证号", errors)
        self.assertIn("riskFlags 每条须有 level", errors)
        checks[0]["facts"] = [{**fact, "value": "证件编号 1101**********1237；统一社会信用代码 913201001234567890"}]
        self.write_report(bundle, checks)
        report = json.loads((bundle / "audit.json").read_text(encoding="utf-8"))
        report["riskFlags"] = [{"level": "high", "check": "AC-R24-02", "flag": "设计材质超出全部已交焊工证", "basis": "平面图"}]
        (bundle / "audit.json").write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
        code, out = run("report", "--bundle", str(bundle))
        self.assertEqual(code, 0, out)
        markdown = (bundle / "audit.md").read_text(encoding="utf-8")
        self.assertLess(markdown.index("## 高风险提示"), markdown.index("## AC-R24-01"))
        self.assertIn("【高】AC-R24-02 设计材质超出全部已交焊工证（平面图）", markdown)

    @unittest.skipUnless(importlib.util.find_spec("fitz"), "PyMuPDF 未安装")
    def test_pages_bundle_output_images_and_sheets(self):
        import fitz
        tmp = Path(self.tmp.name)
        outside = tmp / "repo" / "rules" / "standards" / "std.pdf"
        outside.parent.mkdir(parents=True)
        with fitz.open() as doc:
            for n in range(1, 32):
                doc.new_page().insert_text((72, 72), f"page {n}")
            doc.save(outside)
        # 包外文件（如仓库里的标准原件）不带 --bundle/--out 一律拒绝，不在仓库旁边留下 pages/
        self.assertEqual(run("pages", "--file", str(outside), "--pages", "1")[1]["error"]["code"], "outputMissing")
        self.assertFalse((tmp / "repo" / "rules" / "pages").exists())
        self.assertEqual(run("pages", "--file", str(outside), "--pages", "1", "--bundle", str(tmp / "nope"))[1]["error"]["code"], "bundleMissing")
        bundle = self.local_bundle()
        code, out = run("pages", "--file", str(outside), "--sheet", "--bundle", str(bundle))
        self.assertEqual(code, 0, out)
        self.assertEqual([Path(s).name for s in out["data"]["sheets"]], ["std-sheet-p001-030.png", "std-sheet-p031-031.png"])
        self.assertTrue(all(Path(s).parent == (bundle / "pages").resolve() for s in out["data"]["sheets"]))
        code, out = run("pages", "--file", str(outside), "--sheet", "--pages", "2-4", "--cols", "3", "--bundle", str(bundle))
        with fitz.open(out["data"]["sheets"][0]) as png:
            self.assertEqual(png[0].rect.width, 600)  # 3 列 × 200
        # 图片当单页文档：能渲染、能放大局部，裁剪框不同文件名就不同
        image = bundle / "files" / "02-证书.png"
        pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 400, 300), False)
        pix.clear_with(200)
        pix.save(image)
        code, out = run("pages", "--file", str(image), "--pages", "1", "--clip", "0.1,0.1,0.575,0.5", "--dpi", "144")
        self.assertEqual((code, out["data"]["pageCount"], out["data"]["pages"][0]["textLayer"]), (0, 1, False))
        first = Path(out["data"]["pages"][0]["image"])
        second = Path(run("pages", "--file", str(image), "--pages", "1", "--clip", "0.1,0.1,0.57,0.5")[1]["data"]["pages"][0]["image"])
        self.assertNotEqual(first.name, second.name)
        self.assertEqual(first.parent, (bundle / "pages").resolve())
        code, out = run("pages", "--file", str(image))  # 图片和单页 PDF 不必写 --pages
        self.assertEqual((code, [p["page"] for p in out["data"]["pages"]]), (0, [1]))
        self.assertIn("有 31 页", run("pages", "--file", str(outside), "--bundle", str(bundle))[1]["error"]["message"])

    @unittest.skipUnless(importlib.util.find_spec("fitz"), "PyMuPDF 未安装")
    def test_sheet_shows_seals_kept_as_annotations_and_form_fields(self):
        import fitz
        bundle = self.local_bundle()
        drawing = bundle / "files" / "03-图纸.pdf"
        with fitz.open() as doc:
            page = doc.new_page()
            seal = page.add_rect_annot(fitz.Rect(100, 500, 400, 700))  # 电子章常不在页面内容里
            seal.set_colors(stroke=(1, 0, 0), fill=(1, 0, 0))
            seal.update()
            field = fitz.Widget()
            field.field_type, field.field_name, field.rect = fitz.PDF_WIDGET_TYPE_TEXT, "seal", fitz.Rect(50, 50, 150, 80)
            page.add_widget(field)
            doc.new_page()
            doc.save(drawing)
        code, out = run("pages", "--file", str(drawing), "--sheet")
        self.assertEqual(code, 0, out)
        self.assertEqual(out["data"]["formFieldPages"], {"1": 1})
        with fitz.open(out["data"]["sheets"][0]) as png:
            pix = png[0].get_pixmap()
        samples, n = pix.samples, pix.n
        red = sum(1 for i in range(0, len(samples), n) if samples[i] > 200 and samples[i + 1] < 60 and samples[i + 2] < 60)
        self.assertGreater(red, 50)
        code, out = run("pages", "--file", str(drawing), "--pages", "1-2", "--dpi", "36")
        self.assertEqual([p["formFields"] for p in out["data"]["pages"]], [1, 0])

    @unittest.skipUnless(importlib.util.find_spec("fitz"), "PyMuPDF 未安装")
    def test_partly_scanned_pdf_pages_must_be_accounted_for(self):
        import fitz
        root = Path(self.tmp.name) / "scan-project"
        root.mkdir()
        with fitz.open() as doc:
            doc.new_page().insert_text((72, 72), "焊接工艺卡 焊工 钢印 W01 施焊 2026-01-05", fontname="china-s")
            doc.new_page()  # 扫描页：没有文字层
            doc.save(root / "方案.pdf")
        bundle = Path(run("local-init", "--node", "24", "--project-dir", str(root), "--out", str(Path(self.tmp.name) / "ps"))[1]["data"]["bundle"])
        code, out = run("search", "--bundle", str(bundle))
        self.assertEqual(code, 0, out)
        path = json.loads((bundle / "bundle.json").read_text(encoding="utf-8"))["files"][0]["path"]
        self.assertEqual(out["data"]["needsOcrPages"], {path: "2"})
        self.assertTrue(Path(out["data"]["saved"]).is_absolute())
        self.assertIn("焊工 p1", out["data"]["filesWithHits"][0]["termPages"])  # 按词列命中页
        checks = [{"atomicCheckId": f"AC-R24-0{i}", "verdict": "evidence_insufficient", "reason": "缺记录"} for i in range(1, 6)]
        self.write_report(bundle, checks, [{"file": path, "method": "search"}])
        self.assertIn("第 [2] 页没有文字层", self.report_errors(bundle))
        self.write_report(bundle, checks, [{"file": path, "method": "search", "note": "第 2 页为空白扫描页，已看图"}])
        self.assertEqual(run("report", "--bundle", str(bundle))[0], 0)

    def test_digest_skeleton_and_term_counts(self):
        bundle = self.local_bundle()
        digest = (bundle / "digest.md").read_text(encoding="utf-8")
        self.assertIn("### AC-R24-03", digest)
        self.assertIn("要做的事：按项目代号和实际接头位置逐焊口核验位置覆盖", digest)
        self.assertIn("逐件核对项（逐焊口）", digest)
        self.assertIn("**证据追溯项**", digest)
        self.assertNotIn("服务器工具", digest)  # 本地模式不列服务器工具
        code, out = run("skeleton", "--bundle", str(bundle))
        self.assertEqual(code, 0, out)
        skeleton = json.loads((bundle / "audit.json").read_text(encoding="utf-8"))
        self.assertEqual([c["atomicCheckId"] for c in skeleton["checks"]], [f"AC-R24-0{i}" for i in range(1, 6)])
        self.assertEqual([("coverage" in c) for c in skeleton["checks"]], [False, True, True, True, False])
        self.assertEqual([f["file"] for f in skeleton["reviewedFiles"]], ["files/01-证书.pdf"])
        self.assertEqual(run("skeleton", "--bundle", str(bundle))[1]["error"]["code"], "reportExists")
        errors = self.report_errors(bundle)
        self.assertIn("AC-R24-01: 还没下结论", errors)
        self.assertIn("files/01-证书.pdf: 还没写怎么看的（method）", errors)
        # 节点 1：按 requiredFacts 补“设计变更”等词，不带焊接类噪声词；零命中的词单列
        tank = Path(run("local-init", "--node", "1", "--project-dir", str(self.project_dir()), "--out", str(Path(self.tmp.name) / "t1"))[1]["data"]["bundle"])
        terms = na.default_terms(tank)
        self.assertTrue({"设计变更", "出图专用章", "管道级别"} <= set(terms))
        self.assertNotIn("焊工", terms)
        out = run("search", "--bundle", str(tank))[1]["data"]
        self.assertIn("计划施工时间 1", out["termHitFiles"])
        self.assertNotIn("设计变更", out["termHitFiles"])
        self.assertIn("设计变更", out["zeroHitTerms"])
        # 包里有 1 张图片没被检索到：零命中不能当“没有”用，提示要点明
        self.assertIn("1 份图片或扫描件", out["zeroHitNote"])
        self.assertIn("先跑 ocr", out["zeroHitNote"])

    def test_zero_hit_note_only_when_unsearched_files_exist(self):
        root = Path(self.tmp.name) / "textonly"
        root.mkdir()
        (root / "合同.txt").write_text("计划施工时间 2026-03-25 至 2026-06-30", encoding="utf-8")
        bundle = run("local-init", "--node", "1", "--project-dir", str(root), "--out", str(Path(self.tmp.name) / "to"))[1]["data"]["bundle"]
        out = run("search", "--bundle", bundle)[1]["data"]
        self.assertIn("设计变更", out["zeroHitTerms"])
        self.assertEqual(out["needsOcr"], [])
        self.assertNotIn("zeroHitNote", out)  # 全是文字层，零命中就是真没有，不加噪音

    @unittest.skipUnless(importlib.util.find_spec("fitz"), "PyMuPDF 未安装")
    def test_captioned_image_page_needs_visual_review(self):
        import fitz
        root = Path(self.tmp.name) / "brochure"
        root.mkdir()
        pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 200, 200), False)
        pix.clear_with(180)
        with fitz.open() as doc:
            page = doc.new_page()
            page.insert_image(fitz.Rect(50, 100, 550, 700), pixmap=pix)  # 整页证书扫描
            page.insert_text((60, 80), "设计单位资质证书 扫描件 第一页 仅供参考", fontname="china-s")  # 一行说明
            text_page = doc.new_page()
            text_page.insert_text((60, 80), "短文字页没有图片 这一页只有一行字 但字数不少", fontname="china-s")  # 20–50 字、无图
            doc.save(root / "宣传册.pdf")
        bundle = Path(run("local-init", "--node", "1", "--project-dir", str(root), "--out", str(Path(self.tmp.name) / "bb"))[1]["data"]["bundle"])
        out = run("search", "--bundle", str(bundle))[1]["data"]
        path = json.loads((bundle / "bundle.json").read_text(encoding="utf-8"))["files"][0]["path"]
        self.assertEqual(out["needsOcrPages"], {path: "1"})  # 带图的短字页要 OCR，纯短字页不要

    @unittest.skipUnless(importlib.util.find_spec("fitz"), "PyMuPDF 未安装")
    def test_all_visual_sheets_after_search(self):
        bundle = Path(run("local-init", "--node", "24", "--project-dir", str(self.project_dir()), "--out", str(Path(self.tmp.name) / "av"))[1]["data"]["bundle"])
        self.assertEqual(run("pages", "--all-visual", "--bundle", str(bundle))[1]["error"]["code"], "searchMissing")
        import fitz
        png = next(f["path"] for f in json.loads((bundle / "bundle.json").read_text(encoding="utf-8"))["files"] if f["path"].endswith(".png"))
        pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 300, 200), False)
        pix.clear_with(255)
        pix.save(bundle / png)  # 换成真图片，fitz 才打得开
        run("search", "--bundle", str(bundle))
        code, out = run("pages", "--all-visual", "--bundle", str(bundle))
        self.assertEqual(code, 0, out)
        [item] = out["data"]["files"]
        self.assertEqual((item["file"], item["pageCount"], len(item["sheets"])), (png, 1, 1))
        self.assertTrue(Path(item["sheets"][0]).is_file())

    def test_strict_traceability_conflict_and_per_item(self):
        bundle = self.local_bundle()
        fact = {"name": "n", "value": "v", "source": {"file": "files/01-证书.pdf", "page": 1}}
        passed = lambda cid, **extra: {"atomicCheckId": cid, "verdict": "passed", "facts": [fact], "reasoning": "满足要求。", **extra}
        coverage = {"items": 4, "checked": 4, "source": "施焊记录 4 道焊口"}
        self.write_report(bundle, [
            {"atomicCheckId": "AC-R24-01", "verdict": "evidence_insufficient", "reason": "缺施焊日期"},
            passed("AC-R24-02", coverage=coverage),
            passed("AC-R24-03"),
            passed("AC-R24-04", conflicts=["炉批号与验收记录不一致"]),
            passed("AC-R24-05"),
        ])
        errors = self.report_errors(bundle)
        self.assertIn("AC-R24-03: 规则要求逐焊口核对", errors)
        self.assertIn("AC-R24-04: 列了 conflicts 就不能判符合", errors)
        self.assertIn("AC-R24-05: 证据追溯项不得判符合——证据缺失：AC-R24-01；存在冲突：AC-R24-04。应判需人工确认", errors)
        self.assertNotIn("AC-R24-02", errors)
        partial = {"items": 4, "checked": 3, "source": "施焊记录"}
        self.write_report(bundle, [passed(f"AC-R24-0{i}", **({"coverage": partial} if i == 3 else {"coverage": coverage} if i == 2 else {}))
                                   for i in range(1, 6)])
        errors = self.report_errors(bundle)
        self.assertIn("AC-R24-03: 规则要求逐焊口核对", errors)
        self.assertNotIn("AC-R24-05", errors)
        self.write_report(bundle, [passed(f"AC-R24-0{i}", **({"coverage": coverage} if i in (2, 3, 4) else {})) for i in range(1, 6)])
        code, out = run("report", "--bundle", str(bundle))
        self.assertEqual(code, 0, out)
        self.assertIn("逐件覆盖：4/4", (bundle / "audit.md").read_text(encoding="utf-8"))
        catalog = {c["id"]: c for c in na.rule_catalog(24)["atomicChecks"]}
        self.assertEqual((catalog["AC-R24-05"].get("role"), catalog["AC-R24-03"].get("perItem")), ("traceability", "逐焊口"))
        self.assertEqual(catalog["AC-R24-04"].get("perItem"), "逐焊口")  # instruction 没写“逐”，靠覆盖表

    def test_id_numbers_masked_everywhere_and_resolved_for_registry(self):
        full, masked = "110101199001011237", "1101**********1237"
        root = self.project_dir()
        (root / "焊工名单.txt").write_text(f"焊工 张三 身份证号 {full} 钢印 W01", encoding="utf-8")
        bundle = Path(run("local-init", "--node", "24", "--project-dir", str(root), "--out", str(Path(self.tmp.name) / "id"))[1]["data"]["bundle"])
        roster = next(f["path"] for f in json.loads((bundle / "bundle.json").read_text(encoding="utf-8"))["files"] if f["path"].endswith("焊工名单.txt"))
        text = Path(run("text", "--file", str(bundle / roster))[1]["data"]["saved"]).read_text(encoding="utf-8")
        self.assertIn(masked, text)
        self.assertNotIn(full, text)
        code, out = run("search", "--bundle", str(bundle), "--terms", "身份证号")
        self.assertEqual(code, 0, out)
        self.assertEqual(out["data"]["idNumbersInText"], {masked: roster})  # 这些号码可直接用脱敏号查
        for raw in (json.dumps(out, ensure_ascii=False), Path(out["data"]["saved"]).read_text(encoding="utf-8")):
            self.assertIn(masked, raw)
            self.assertFalse(na.contains_id_number(raw))
        # 脱敏号要配资料包才能查；配了就回原件找完整号码发给服务器，输出和存档仍是脱敏号
        self.assertEqual(run("cert-registry", "--kind", "person", "--identifier", masked)[1]["error"]["code"], "invalidArguments")
        self.assertEqual(self.server.requests, [])
        code, out = run("cert-registry", "--kind", "person", "--identifier", masked, "--bundle", str(bundle))
        self.assertEqual(code, 0, out)
        self.assertEqual(self.server.requests[-1][2]["_body"]["identifier"], full)
        self.assertEqual(out["data"]["records"]["person"]["sfzh"], masked)
        saved = (bundle / out["savedTo"]).read_text(encoding="utf-8")
        self.assertIn(masked, saved)
        self.assertFalse(na.contains_id_number(saved))
        code, out = run("cert-registry", "--kind", "person", "--identifier", "1101**********0000", "--bundle", str(bundle))
        self.assertEqual((code, out["error"]["code"]), (1, "identifierNotFound"))
        # 照图片抄错一位：校验位对不上就不去平台查
        before = len(self.server.requests)
        code, out = run("cert-registry", "--kind", "person", "--identifier", "110101199001011238")
        self.assertEqual((code, out["error"]["code"], len(self.server.requests)), (1, "idChecksumFailed", before))

    def test_json_output_masks_ids_after_a_newline(self):
        # JSON 里换行写成 \n，后面紧跟的号码前一个字符是字母 n：在转义后的文本上扫会漏，所以要先遮字符串再转 JSON
        full, masked = "110101199001011237", "1101**********1237"
        value = {"text": f"姓名：\n张三\n身份证号：\n{full}\n", "nested": [{"note": f"{full}"}, f"\t{full}"], full: "键里也有"}
        raw = na.dump_masked(value)
        self.assertFalse(na.contains_id_number(raw.replace("\\n", "\n").replace("\\t", "\t")), raw)
        self.assertEqual(json.loads(raw)["text"], f"姓名：\n张三\n身份证号：\n{masked}\n")
        self.assertIn(masked, json.loads(raw))
        self.assertEqual(na.mask_value({"n": 3, "ok": True, "none": None}), {"n": 3, "ok": True, "none": None})
        self.assertEqual(na.mask_ids("统一社会信用代码 91110000600000001X 不是身份证"), "统一社会信用代码 91110000600000001X 不是身份证")

    @unittest.skipUnless(importlib.util.find_spec("fitz"), "PyMuPDF 未安装")
    def test_pages_text_masks_id_on_its_own_line(self):
        import fitz
        full, masked = "110101199001011237", "1101**********1237"
        source = Path(self.tmp.name) / "files" / "03-cert.pdf"
        source.parent.mkdir()
        (Path(self.tmp.name) / "bundle.json").write_text("{}", encoding="utf-8")
        with fitz.open() as doc:
            doc.new_page().insert_text((72, 72), f"name:\nid card:\n{full}\nend")
            doc.save(source)
        code, out = run("pages", "--file", str(source), "--pages", "1")
        self.assertEqual(code, 0, out)
        self.assertIn(masked, out["data"]["pages"][0]["text"])
        self.assertFalse(na.contains_id_number(json.dumps(out, ensure_ascii=False).replace("\\n", "\n")))

    def test_registry_503_retried_once(self):
        self.server.registry_unavailable = 1
        with patch.object(na.time, "sleep") as sleep:
            code, out = run("cert-registry", "--kind", "organization_license", "--identifier", "TS1234567-2030")
        self.assertEqual(code, 0, out)  # 公示平台第一次 503，隔几秒重试就查到了
        sleep.assert_called_once()
        self.server.registry_unavailable = 2
        with patch.object(na.time, "sleep"):
            code, out = run("cert-registry", "--kind", "organization_license", "--identifier", "TS1234567-2030")
        self.assertEqual((code, out["error"]["code"]), (1, "http503"))  # 只重试一次

    def test_gateway_error_retried_once_and_standards_trimmed(self):
        self.server.gateway_failures = 1
        with patch.object(na.time, "sleep") as sleep:
            code, out = run("cert-registry", "--kind", "organization_license", "--identifier", "TS1234567-2030")
        self.assertEqual(code, 0, out)
        sleep.assert_called_once()
        self.server.gateway_failures = 2
        with patch.object(na.time, "sleep"):
            code, out = run("cert-registry", "--kind", "organization_license", "--identifier", "TS1234567-2030")
        self.assertEqual((code, out["error"]["code"]), (1, "http502"))  # 只重试一次
        code, out = run("standards", "--query", "TSG D7006")
        self.assertEqual(code, 0, out)
        [item] = out["data"]["items"]
        self.assertLess(len(item["text"]), 400)
        self.assertIn("共 5000 字", item["text"])
        self.assertEqual(item["standardContentArguments"], {"fileId": "KF-1"})

    def test_local_report_leaves_audit_json_alone_and_points_at_originals(self):
        bundle = Path(run("local-init", "--node", "24", "--project-dir", str(self.project_dir()), "--out", str(Path(self.tmp.name) / "lr"))[1]["data"]["bundle"])
        files = [f["path"] for f in json.loads((bundle / "bundle.json").read_text(encoding="utf-8"))["files"]]
        fact = {"name": "焊工人数", "value": "4 人", "source": {"file": "text/方案.txt", "locator": "第 2 行"}}
        checks = [{"atomicCheckId": f"AC-R24-0{i}", "verdict": "evidence_insufficient", "reason": "缺施焊记录"} for i in range(1, 6)]
        checks[1]["facts"] = [fact]
        reviewed = [{"file": p, "method": "skipped" if p.endswith(".txt") else "read", "note": "属合同节点资料"} for p in files]
        self.write_report(bundle, checks, reviewed)
        # 引用转出的文字不算出处：报错并指回原件
        self.assertIn("转出的文字（含 OCR 文字）：file 写 files/ 下的原件", self.report_errors(bundle))
        plan = next(p for p in files if p.endswith("方案.docx"))
        fact["source"] = {"file": plan, "locator": "text/方案.txt 第 2 行"}
        self.write_report(bundle, checks, reviewed)
        written = (bundle / "audit.json").read_bytes()
        code, out = run("report", "--bundle", str(bundle))
        self.assertEqual(code, 0, out)
        self.assertFalse(out["data"]["auditJsonUpdated"])
        self.assertEqual((bundle / "audit.json").read_bytes(), written)  # 本地资料没有服务器结论，不改写
        self.assertNotIn("跳过未看", " ".join(out["data"]["warnings"]))  # skipped 写了原因就合格

    def test_failed_lookup_is_saved_too(self):
        bundle = self.local_bundle()
        with patch.object(na.time, "sleep"):  # 503 会自动重试一次，不真等
            code, out = run("cert-registry", "--kind", "organization_license", "--identifier", "TS9999999-2030", "--bundle", str(bundle))
        self.assertEqual((code, out["error"]["status"]), (1, 503))
        saved = json.loads((bundle / out["savedTo"]).read_text(encoding="utf-8"))
        self.assertEqual((saved["ok"], saved["error"]["code"], saved["arguments"]["identifier"]), (False, "http503", "TS9999999-2030"))
        self.assertTrue(na.is_id_number("110101199001011237"))
        self.assertFalse(na.is_id_number("913201001234567890"))  # 信用代码：出生日期不合法
        self.assertFalse(na.is_id_number("110101199001011238"))  # 校验位不对

    def test_bundle_is_private(self):
        code, out = run("local-init", "--node", "24", "--project", "P-X", "--files", str(self.sample_file()))
        self.assertEqual(code, 0, out)
        bundle = Path(out["data"]["bundle"])
        home = Path(os.environ["AICHECK_AUDIT_HOME"])
        for directory in (home, home / "P-X", bundle.parent, bundle, bundle / "files"):
            self.assertEqual(stat.S_IMODE(directory.stat().st_mode), 0o700, directory)
        self.assertEqual(stat.S_IMODE((bundle / "files/01-证书.pdf").stat().st_mode), 0o600)

    def test_tool_result_saved_to_bundle(self):
        code, out = run("cert-registry", "--kind", "organization_license", "--identifier", "TS1234567-2030",
                        "--bundle", str(Path(self.tmp.name) / "nowhere"))
        self.assertEqual(out["error"]["code"], "bundleMissing")
        self.assertEqual(self.server.requests, [])
        bundle = self.local_bundle()
        code, out = run("cert-registry", "--kind", "organization_license", "--identifier", "TS1234567-2030", "--bundle", str(bundle))
        self.assertEqual(code, 0, out)
        saved = json.loads((bundle / out["savedTo"]).read_text(encoding="utf-8"))
        self.assertEqual(saved["tool"], "cert-registry")
        self.assertEqual(saved["arguments"], {"kind": "organization_license", "identifier": "TS1234567-2030"})
        self.assertEqual(saved["result"]["kind"], "organization_license")
        self.assertEqual(stat.S_IMODE((bundle / out["savedTo"]).stat().st_mode), 0o600)

    def test_local_init_and_report(self):
        bundle = self.local_bundle()
        manifest = json.loads((bundle / "bundle.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["source"], "local")
        self.assertEqual(manifest["files"][0]["path"], "files/01-证书.pdf")
        fact = {"name": "证书编号", "value": "X", "source": {"file": "files/01-证书.pdf", "page": 1, "excerpt": "W01 | 6G"}}
        checks = [{"atomicCheckId": "AC-R24-01", "verdict": "failed", "facts": [fact], "reasoning": "过期"}]
        checks += [{"atomicCheckId": f"AC-R24-0{i}", "verdict": "evidence_insufficient", "reason": "缺施焊记录"} for i in range(2, 6)]
        self.write_report(bundle, checks)
        code, out = run("report", "--bundle", str(bundle))
        self.assertEqual(code, 0, out)
        self.assertEqual(out["data"]["counts"], {"不符合": 1, "证据不足": 4})
        self.assertTrue(out["data"]["auditJsonUpdated"])  # 补了服务器结论
        self.assertTrue(any("differenceNote" in w for w in out["data"]["warnings"]))
        saved = json.loads((bundle / "audit.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["checks"][0]["serverResult"], "passed")
        self.assertIs(saved["checks"][0]["agreesWithServer"], False)
        markdown = (bundle / "audit.md").read_text(encoding="utf-8")
        self.assertIn("不代替监检人员的正式结论", markdown)
        self.assertIn("files/01-证书.pdf 第1页 「W01 \\| 6G」", markdown)

    @unittest.skipUnless(importlib.util.find_spec("fitz"), "PyMuPDF 未安装")
    def test_pages_renders_and_extracts_text(self):
        import fitz
        source = Path(self.tmp.name) / "files" / "01-scan.pdf"
        source.parent.mkdir()
        (Path(self.tmp.name) / "bundle.json").write_text("{}", encoding="utf-8")  # 文件在资料包里：默认写包内 pages/
        with fitz.open() as doc:
            for text in ("page one", "page two"):
                doc.new_page().insert_text((72, 72), text)
            doc.save(source)
        code, out = run("pages", "--file", str(source), "--pages", "2")
        self.assertEqual(code, 0, out)
        [page] = out["data"]["pages"]
        self.assertEqual((page["page"], page["text"]), (2, "page two"))
        self.assertTrue(Path(page["image"]).is_file())
        self.assertEqual(Path(page["image"]).parent, (Path(self.tmp.name) / "pages").resolve())
        code, out = run("pages", "--file", str(source), "--pages", "1-3")
        self.assertEqual(out["error"]["code"], "pageOutOfRange")
        code, out = run("pages", "--file", str(source), "--pages", "1", "--clip", "0,0,0.5,0.25", "--dpi", "72")
        self.assertEqual(code, 0, out)
        image = Path(out["data"]["pages"][0]["image"])
        self.assertIn("-clip", image.name)
        with fitz.open(image) as png:
            self.assertEqual((png[0].rect.width, png[0].rect.height), (298, 211))  # A4 595×842 的左半、上四分之一
        self.assertEqual(stat.S_IMODE(image.stat().st_mode), 0o600)
        code, out = run("pages", "--file", str(source), "--pages", "1", "--clip", "0.5,0,0.4,1")
        self.assertEqual(out["error"]["code"], "invalidArguments")

    @unittest.skipUnless(importlib.util.find_spec("fitz"), "PyMuPDF 未安装")
    def test_pages_rotates_sideways_tables_and_takes_bundle_relative_paths(self):
        import fitz
        bundle = self.local_bundle()
        sideways = bundle / "files" / "05-横表.pdf"
        with fitz.open() as doc:
            page = doc.new_page(width=842, height=595)
            page.draw_rect(fitz.Rect(0, 0, 210, 150), color=(1, 0, 0), fill=(1, 0, 0))  # 左上角一块红
            doc.save(sideways)
        # 资料包里的相对路径配 --bundle 就能找到
        code, out = run("pages", "--file", "files/05-横表.pdf", "--bundle", str(bundle), "--rotate", "90", "--dpi", "72")
        self.assertEqual(code, 0, out)
        page = out["data"]["pages"][0]
        self.assertEqual((page["rotate"], Path(page["image"]).name), (90, "05-横表-p001-r90.png"))
        pix = fitz.Pixmap(page["image"])
        self.assertEqual((pix.width, pix.height), (595, 842))  # 顺时针转 90 度：横页变竖页
        self.assertEqual(pix.pixel(pix.width - 5, 5)[:3], (255, 0, 0))  # 原来的左上角转到右上角
        # --clip 按转正后的样子给：每个角度都截到那块红
        for rotate, box in ((90, "0.75,0,1,0.25"), (180, "0.75,0.75,1,1"), (270, "0,0.75,0.25,1"), (0, "0,0,0.25,0.25")):
            code, out = run("pages", "--file", "files/05-横表.pdf", "--bundle", str(bundle), "--rotate", str(rotate),
                            "--clip", box, "--dpi", "72")
            pix = fitz.Pixmap(out["data"]["pages"][0]["image"])
            self.assertEqual(pix.pixel(pix.width // 2, pix.height // 2)[:3], (255, 0, 0), rotate)
        self.assertEqual(run("pages", "--file", "files/没有.pdf", "--bundle", str(bundle))[1]["error"]["code"], "fileNotFound")

    def test_standard_status_reports_the_status_on_the_given_date(self):
        result = {"status": "COMPLETED", "verdict": "superseded",
                  "standardReferences": [{"effectiveFrom": "2017-09-01", "withdrawnOn": "2026-05-01"}]}
        self.assertEqual([na.status_on_date(result, day)["status"] for day in ("2017-08-31", "2021-03-24", "2026-05-01")],
                         ["not_yet_effective", "in_force", "withdrawn"])
        self.assertEqual(na.status_on_date({"detail": {"effectiveDate": "2025-10-01"}}, "2026-01-01")["status"], "in_force")
        self.assertEqual(na.status_on_date({}, "2026-01-01")["status"], "unknown")
        self.assertEqual(run("standard-status", "--ref", "GB/T 1-2020", "--date", "2021-3-24")[1]["error"]["code"], "invalidArguments")

    def test_report_warns_when_the_primary_clause_is_never_cited(self):
        bundle = self.local_bundle()
        fact = {"name": "证书编号", "value": "X", "source": {"file": "files/01-证书.pdf", "page": 1}}
        checks = [{"atomicCheckId": "AC-R24-01", "verdict": "failed", "facts": [fact], "reasoning": "过期"}]
        checks += [{"atomicCheckId": f"AC-R24-0{i}", "verdict": "evidence_insufficient", "reason": "缺施焊记录"} for i in range(2, 6)]
        self.write_report(bundle, checks)
        code, out = run("report", "--bundle", str(bundle))
        self.assertEqual(code, 0, out)
        self.assertTrue(any("固定主条款" in w and "D2.6.1" in w for w in out["data"]["warnings"]), out["data"]["warnings"])
        # 引用时写出条款号（全角括号、空格都认）就不再警告；写进 limitations 说明没取到也行
        clause = {"name": "主条款", "value": "核查焊工资格", "source": {"file": "standard:rules/standards/TSG D7006-2020 压力管道监督检验规则.pdf", "page": 28,
                                                                  "excerpt": "D2.6.1 焊工（B 类）"}}
        checks[0]["facts"].append(clause)
        self.write_report(bundle, checks)
        self.assertFalse(any("固定主条款" in w for w in run("report", "--bundle", str(bundle))[1]["data"]["warnings"]))
        checks[0]["facts"].pop()
        self.write_report(bundle, checks)
        report = json.loads((bundle / "audit.json").read_text(encoding="utf-8"))
        report["limitations"] = ["TSG D7006 D2.6.1 原文没取到：仓库和服务器都没有"]
        (bundle / "audit.json").write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
        self.assertFalse(any("固定主条款" in w for w in run("report", "--bundle", str(bundle))[1]["data"]["warnings"]))

    def test_report_warns_when_a_passed_check_still_carries_next_steps(self):
        bundle = self.local_bundle()
        fact = {"name": "证书编号", "value": "X", "source": {"file": "files/01-证书.pdf", "page": 1}}
        checks = [{"atomicCheckId": "AC-R24-01", "verdict": "passed", "facts": [fact], "reasoning": "有效期覆盖施焊期",
                   "nextSteps": ["施工方补母材质证"]}]
        checks += [{"atomicCheckId": f"AC-R24-0{i}", "verdict": "evidence_insufficient", "reason": "缺施焊记录"} for i in range(2, 6)]
        self.write_report(bundle, checks)
        code, out = run("report", "--bundle", str(bundle))
        self.assertEqual(code, 0, out)  # 只是警告，不拦报告
        self.assertTrue(any("AC-R24-01" in w and "符合项带着 nextSteps" in w for w in out["data"]["warnings"]), out["data"]["warnings"])
        checks[0]["nextSteps"] = []
        self.write_report(bundle, checks)
        self.assertFalse(any("符合项带着" in w for w in run("report", "--bundle", str(bundle))[1]["data"]["warnings"]))
        checks[0].update(verdict="evidence_insufficient", reason="缺母材质证", nextSteps=["施工方补母材质证"])  # 非符合项带 nextSteps 不警告
        self.write_report(bundle, checks)
        self.assertFalse(any("符合项带着" in w for w in run("report", "--bundle", str(bundle))[1]["data"]["warnings"]))

    def test_sources_may_sit_behind_symlinks_but_not_outside_the_allowed_roots(self):
        tmp = Path(self.tmp.name)
        real = tmp / "elsewhere" / "standards"
        real.mkdir(parents=True)
        (real / "标准.pdf").write_bytes(b"%PDF-1.4 fake\n")
        repo = tmp / "repo"
        (repo / "rules").mkdir(parents=True)
        (repo / "rules" / "standards").symlink_to(real)  # 工作区里 rules/ 常是指向仓库的链接
        (tmp / "secret.json").write_text("{}", encoding="utf-8")
        bundle = self.local_bundle()
        with patch.dict(os.environ, {"AICHECK_REPO": str(repo)}):
            ok = na.source_problem(bundle, {"file": "standard:rules/standards/标准.pdf", "page": 3}, set(), {})
            escape = na.source_problem(bundle, {"file": "standard:../secret.json", "locator": "x"}, set(), {})
        self.assertIsNone(ok)  # 打不开的 PDF 只在 check_report 里给警告，不算出处错误
        self.assertEqual(escape, "引用来源不存在或越出允许目录")
        self.assertEqual(na.source_problem(bundle, {"file": "server:../../secret.json", "locator": "x"}, set(), {}),
                         "引用来源不存在或越出允许目录")

    def test_report_rejects_unsourced_and_missing_checks(self):
        bundle = self.local_bundle()
        self.write_report(bundle, [
            {"atomicCheckId": "AC-R24-01", "verdict": "passed", "facts": [{"name": "n", "value": "v", "source": {"file": "files/01-证书.pdf"}}]},
            {"atomicCheckId": "AC-R24-02", "verdict": "not_applicable"},
            {"atomicCheckId": "AC-R24-02", "verdict": "maybe"},
            {"atomicCheckId": "AC-R26-01", "verdict": "evidence_insufficient", "reason": "x"},
        ])
        code, out = run("report", "--bundle", str(bundle))
        self.assertEqual(code, 1)
        errors = " ".join(out["error"]["errors"])
        for expected in ("AC-R24-01: 符合 至少要一条", "AC-R24-02: 不适用 必须写 reason", "verdict 必须是",
                         "缺少原子检查：AC-R24-03", "不属于本节点的检查：AC-R26-01", "重复的检查：AC-R24-02"):
            self.assertIn(expected, errors)
        self.assertFalse((bundle / "audit.md").exists())

    # ------------------------------------------------------------ OCR（经服务器：MinerU，排队超时自动改千问）

    FULL_ID, MASKED_ID = "110101199001011237", "1101**********1237"

    def scan_bundle(self, name: str = "ocr") -> tuple[Path, str]:
        root = Path(self.tmp.name) / f"{name}-project"
        root.mkdir()
        (root / "焊工证-张三.png").write_bytes(b"\x89PNG fake scan")
        (root / "合同.txt").write_text("计划施工时间：2025年11月3日～2026年1月20日", encoding="utf-8")
        bundle = Path(run("local-init", "--node", "24", "--project-dir", str(root), "--out", str(Path(self.tmp.name) / name))[1]["data"]["bundle"])
        png = next(f["path"] for f in json.loads((bundle / "bundle.json").read_text(encoding="utf-8"))["files"] if f["path"].endswith(".png"))
        return bundle, png

    def certificate_result(self) -> dict:
        return {"resultAvailable": True, "pageCount": 1, "documentType": "welder_certificate",
                "processing": {"provider": "mineru"}, "quality": {"status": "usable"},
                "fragments": [
                    {"pageNo": 1, "readingOrder": 2, "text": f"证书编号 {self.FULL_ID} 有效期至 $2027$ 年 3 月"},
                    {"pageNo": 1, "readingOrder": 1, "text": "特种设备作业人员证"},
                    {"pageNo": 1, "readingOrder": 3, "text": "项目代号 GTAW-FeⅡ-6G-3/60-FefS-02/10/12", "blockType": "table",
                     "tableHtml": "<table><tr><td>项目代号</td><td>GTAW-FeⅡ-6G-3/60-FefS-02/10/12</td></tr></table>"}],
                "seals": [{"pageNo": 1, "text": "某某市市场监督管理局"}],
                "documentFields": [{"fieldName": "证书编号", "fieldValue": self.FULL_ID}]}

    def test_latex_merged_cells_and_server_result_become_plain_page_text(self):
        cases = {"厚度为 $14\\mathrm{mm}$ 的Q345R": "厚度为 14mm 的Q345R", "$14 \\mathrm{~mm}$": "14mm", "$CO_{2}$": "CO2",
                 "$\\mathrm{CO}_{2}$": "CO2", "$25\\leqslant D <76$": "25≤D<76", "$8D\\sim 10D$": "8D~10D",
                 "$\\geq D+100$": "≥D+100", "${L}_{1}$": "L1", "$60^{\\circ}$": "60°", "$\\phi 89\\times 3.0$": "φ89×3.0"}
        for raw, plain in cases.items():
            self.assertEqual(na.plain_latex(raw), plain, raw)
        html = ('<table><tr><td rowspan="2">板</td><td>手工焊</td><td rowspan="2">自定</td></tr>'
                '<tr><td>机动焊</td></tr><tr><td>管</td><td colspan="2">&lt;25</td></tr></table>')
        # 合并单元格在所跨的每一行都重复：逐行读就知道“机动焊”这一行的厚度也是“自定”
        self.assertEqual(na.table_text(html).splitlines(), ["板 | 手工焊 | 自定", "板 | 机动焊 | 自定", "管 | <25 | <25"])
        pages = na.server_ocr_pages({"pageCount": 3, "fragments": [
            {"pageNo": 1, "readingOrder": 2, "text": "第二段"}, {"pageNo": 1, "readingOrder": 1, "text": "第一段"},
            {"pageNo": 2, "readingOrder": 1, "text": "板 手工焊 自定 板 机动焊", "tableHtml": html}],
            "seals": [{"pageNo": 2}], "signatures": [{"pageNo": 1, "text": "张三"}]})
        self.assertEqual(pages[1], "第一段\n第二段\n[签名：张三]")  # 按阅读顺序，签名排在本页文字后
        self.assertEqual(pages[2].splitlines()[1], "板 | 机动焊 | 自定")  # 表格用原 HTML 展开，不用服务器压平的文字
        self.assertIn("[印章：服务器未读出章上的字]", pages[2])
        self.assertEqual(pages[3], "")  # 空白页也占位，页码不错位

    def test_ocr_needs_login_and_local_consent_then_feeds_text_search_and_registry(self):
        bundle, png = self.scan_bundle()
        code, out = run("ocr", "--bundle", str(bundle))
        self.assertEqual((code, out["error"]["code"]), (1, "loginRequired"))
        self.login()
        code, out = run("ocr", "--bundle", str(bundle))
        self.assertEqual((code, out["error"]["code"]), (1, "egressNotApproved"))  # 本地资料先问用户
        self.assertEqual(self.server.ocr_uploads, [])
        self.server.ocr_result = self.certificate_result()
        code, out = run("ocr", "--bundle", str(bundle), "--allow-egress")
        self.assertEqual(code, 0, out)
        [done] = out["data"]["done"]
        self.assertEqual((done["file"], done["pages"], done["provider"]), (png, 1, "mineru"))
        [(raw_headers, body)] = self.server.ocr_uploads
        headers = {k.lower(): v for k, v in raw_headers.items()}  # HTTP 头不分大小写；urllib 会改写成 X-aicheck-…
        self.assertEqual(body, (bundle / png).read_bytes())  # 传的是原件字节
        sha = next(f["sha256"] for f in json.loads((bundle / "bundle.json").read_text(encoding="utf-8"))["files"] if f["path"] == png)
        meta = json.loads(base64.urlsafe_b64decode(headers["x-aicheck-ocr-metadata-b64"]))
        self.assertEqual(meta, {"fileName": f"{sha[:16]}.png", "options": {"language": "ch"}})  # 上传名只用哈希，不带人名
        self.assertEqual((headers["content-type"], headers["authorization"]), ("application/octet-stream", f"Bearer {TOKEN}"))
        self.assertEqual(headers["idempotency-key"], f"aicheck-node-audit-{sha[:48]}")
        self.assertTrue((bundle / "ocr" / "egress-approved.json").exists())
        record = bundle / "ocr" / f"{na.ocr_key(png)}.json"
        self.assertEqual(stat.S_IMODE(record.stat().st_mode), 0o600)
        readable = Path(done["saved"]).read_text(encoding="utf-8")
        self.assertIn(self.MASKED_ID, readable)
        self.assertNotIn(self.FULL_ID, readable)
        self.assertLess(readable.index("特种设备作业人员证"), readable.index("证书编号"))  # 按阅读顺序
        self.assertIn("项目代号 | GTAW-FeⅡ-6G-3/60-FefS-02/10/12", readable)
        self.assertIn("有效期至 2027 年 3 月", readable)
        self.assertIn("[印章：某某市市场监督管理局]", readable)
        self.assertIn("服务器抽取的字段", readable)
        code, out = run("ocr", "--bundle", str(bundle))  # 已同意过；原件没变就不重做
        self.assertEqual((code, out["data"]["cached"], len(self.server.ocr_uploads)), (0, [png], 1))
        code, out = run("text", "--file", png, "--bundle", str(bundle))
        self.assertEqual((code, out["data"]["status"], out["data"]["ocrPages"]), (0, "ocr", "1"))
        self.assertIn("--- 第 1 页（OCR） ---", Path(out["data"]["saved"]).read_text(encoding="utf-8"))
        code, out = run("search", "--bundle", str(bundle), "--terms", "项目代号")
        self.assertEqual(code, 0, out)
        hit = next(f for f in out["data"]["filesWithHits"] if f["path"] == png)
        self.assertEqual(hit["ocrPages"], "1")
        self.assertEqual(out["data"]["needsOcr"], [])
        self.assertEqual(out["data"]["idNumbersInText"], {self.MASKED_ID: png})
        code, out = run("cert-registry", "--kind", "person", "--identifier", self.MASKED_ID, "--bundle", str(bundle))
        self.assertEqual(code, 0, out)
        self.assertEqual(self.server.requests[-1][2]["_body"]["identifier"], self.FULL_ID)  # 完整号码只从 OCR 原文回查
        for path in bundle.rglob("*"):
            if path.is_file():
                self.assertNotIn(TOKEN.encode(), path.read_bytes(), path)  # 令牌不进资料包

    def test_removed_local_ocr_commands_are_not_mentioned_anywhere_in_the_skill(self):
        """本机密钥版（ocr-setup、vlm、本机直连 MinerU/百炼）已删；脚本提示和文档里不许再让 agent 去用它们。"""
        skill = Path(na.__file__).resolve().parents[1]
        stale = ("ocr-setup", "vlm", "AICHECK_MINERU", "AICHECK_VLM", "AICHECK_OCR_CONFIG", "qwen3-vl", "dashscope")
        found = [f"{path.relative_to(skill)}: {word}" for path in sorted(skill.rglob("*"))
                 if path.is_file() and path.suffix in {".py", ".md"} for word in stale
                 if word in path.read_text(encoding="utf-8").lower()]
        self.assertEqual(found, [])

    def test_text_output_for_ocr_pages_points_at_the_server_result_not_a_removed_command(self):
        bundle, png = self.scan_bundle("hint")
        self.login()
        self.server.ocr_result = self.certificate_result()
        with patch.object(na, "OCR_POLL_SECONDS", 0):
            run("ocr", "--bundle", str(bundle), "--allow-egress")
        code, out = run("text", "--file", png, "--bundle", str(bundle))
        self.assertEqual(code, 0, out)
        self.assertIn("服务器识别", out["data"]["ocrNote"])
        self.assertNotIn("vlm", json.dumps(out, ensure_ascii=False))

    def test_ocr_resumes_a_pending_job_and_marks_the_qwen_fallback(self):
        bundle, png = self.scan_bundle("resume")
        self.login()
        self.server.ocr_result = {**self.certificate_result(), "processing": {"provider": "qwen", "fallback": {"from": "mineru", "to": "qwen"}}}
        self.server.ocr_running_polls = 2
        self.server.ocr_final = {"status": "success", "provider": "qwen"}
        with patch.object(na, "OCR_POLL_SECONDS", 0):
            code, out = run("ocr", "--bundle", str(bundle), "--allow-egress", "--timeout", "0")
            self.assertEqual(code, 0, out)
            self.assertEqual([(p["file"], p["state"]) for p in out["data"]["pending"]], [(png, "running")])
            self.assertIn("接着等", out["data"]["nextStep"])
            code, out = run("ocr", "--bundle", str(bundle), "--timeout", "30")
            self.assertEqual(code, 0, out)
        [done] = out["data"]["done"]
        self.assertEqual((done["file"], done["provider"]), (png, "qwen"))
        self.assertEqual(len(self.server.ocr_uploads), 1)  # 续等不重传
        self.assertFalse((bundle / "ocr" / "pending.json").exists())
        self.assertIn("识别：千问", Path(done["saved"]).read_text(encoding="utf-8"))

    def test_ocr_reports_a_failed_job_and_keeps_no_text(self):
        bundle, png = self.scan_bundle("fail")
        self.login()
        self.server.ocr_final = {"status": "failed", "diagnostics": [{"code": "QWEN_OCR_FAILED", "level": "error"}]}
        with patch.object(na, "OCR_POLL_SECONDS", 0):
            code, out = run("ocr", "--bundle", str(bundle), "--allow-egress")
        self.assertEqual(code, 0, out)
        self.assertEqual(out["data"]["failed"], [{"file": png, "reason": "服务器 OCR failed：QWEN_OCR_FAILED"}])
        self.assertFalse((bundle / "ocr" / f"{na.ocr_key(png)}.json").exists())

    # ---- 重试换键：服务器的幂等记录不过期，同一个键永远拿回第一次建的任务（失败的也是）

    def upload_keys(self) -> list[str]:
        return [{k.lower(): v for k, v in headers.items()}["idempotency-key"] for headers, _ in self.server.ocr_uploads]

    def test_ocr_retry_after_a_failed_job_creates_a_new_job_with_a_new_key(self):
        bundle, png = self.scan_bundle("retry")
        self.login()
        self.server.ocr_final = {"status": "failed", "diagnostics": [{"code": "MINERU_FAILED"}]}
        with patch.object(na, "OCR_POLL_SECONDS", 0):
            code, out = run("ocr", "--bundle", str(bundle), "--allow-egress")
            self.assertEqual(code, 0, out)
            self.assertEqual([f["file"] for f in out["data"]["failed"]], [png])
            self.assertIn("换新任务重试", out["data"]["nextStep"])
            sha = next(f["sha256"] for f in json.loads((bundle / "bundle.json").read_text(encoding="utf-8"))["files"] if f["path"] == png)
            self.assertEqual(json.loads((bundle / "ocr" / "attempts.json").read_text(encoding="utf-8")), {sha: 1})
            # 重跑（不加 --force）：同一个键服务器会拿回失败的老任务；换了键才建新任务，这次成功
            self.server.ocr_final = {"status": "success", "provider": "mineru"}
            self.server.ocr_result = self.certificate_result()
            code, out = run("ocr", "--bundle", str(bundle))
        self.assertEqual(code, 0, out)
        self.assertEqual([d["file"] for d in out["data"]["done"]], [png])
        keys = self.upload_keys()
        self.assertEqual(keys, [f"aicheck-node-audit-{sha[:48]}", f"aicheck-node-audit-{sha[:48]}-r1"])
        self.assertEqual(len(self.server.ocr_jobs), 2)  # 两个任务：失败的和重试的
        self.assertNotIn(sha, json.dumps(out["data"]["failed"]))  # 输出里不带哈希

    def test_ocr_force_redoes_a_finished_file_with_a_new_job_and_plain_reruns_stay_cached(self):
        bundle, png = self.scan_bundle("force")
        self.login()
        self.server.ocr_result = self.certificate_result()
        with patch.object(na, "OCR_POLL_SECONDS", 0):
            run("ocr", "--bundle", str(bundle), "--allow-egress")
            run("ocr", "--bundle", str(bundle))  # 没变：不重做
            self.assertEqual(len(self.server.ocr_uploads), 1)
            code, out = run("ocr", "--bundle", str(bundle), "--force")
            self.assertEqual((code, [d["file"] for d in out["data"]["done"]]), (0, [png]))
            run("ocr", "--bundle", str(bundle), "--force")
        keys = self.upload_keys()
        self.assertEqual([k.rsplit("-r", 1)[-1] if "-r" in k.split("aicheck-node-audit-")[1] else "0" for k in keys], ["0", "1", "2"])
        self.assertEqual(len(set(keys)), 3)

    # ---- 服务器暂时不可用（API 每约半小时重启一次）：不中止，任务还在，下次接着等

    def test_ocr_polling_treats_gateway_errors_as_still_waiting(self):
        bundle, png = self.scan_bundle("gw")
        self.login()
        self.server.ocr_result = self.certificate_result()
        self.server.ocr_running_polls = 1  # 第一次查还在识别，任务留在待处理里
        with patch.object(na, "OCR_POLL_SECONDS", 0), patch.object(na, "GATEWAY_RETRY_SECONDS", 0):
            code, out = run("ocr", "--bundle", str(bundle), "--allow-egress", "--timeout", "0")  # 先把任务交上去
            self.assertEqual([p["state"] for p in out["data"]["pending"]], ["running"])
            self.server.ocr_status_failures = 10 ** 6  # 服务器一直 502
            code, out = run("ocr", "--bundle", str(bundle), "--timeout", "0")
            self.assertEqual(code, 0, out)  # 没有中止
            self.assertEqual([(p["file"], p["state"]) for p in out["data"]["pending"]], [(png, "unreachable")])
            self.assertEqual(out["data"]["failed"], [])  # 不是识别失败
            self.assertIn("任务还在", out["data"]["nextStep"])
            self.assertTrue((bundle / "ocr" / "pending.json").exists())
            self.assertFalse((bundle / "ocr" / "attempts.json").exists())  # 不动重试计数
            self.server.ocr_status_failures = 3  # 恢复：中间还夹着几次 502，同一次命令里等过去
            code, out = run("ocr", "--bundle", str(bundle), "--timeout", "60")
        self.assertEqual(code, 0, out)
        self.assertEqual([d["file"] for d in out["data"]["done"]], [png])
        self.assertEqual(len(self.server.ocr_uploads), 1)  # 全程没有重传
        self.assertFalse((bundle / "ocr" / "pending.json").exists())

    def test_ocr_upload_retries_gateway_errors_and_stops_when_the_server_stays_down(self):
        bundle, png = self.scan_bundle("up")
        self.login()
        self.server.ocr_result = self.certificate_result()
        sleeps = []
        with patch.object(na, "OCR_POLL_SECONDS", 0), patch.object(na, "GATEWAY_RETRY_SECONDS", 0), \
                patch.object(na.time, "sleep", side_effect=sleeps.append):
            self.server.ocr_upload_failures = 2  # API 重启中：Api.call 自己重试一次后抛出，再由 with_server_retry 等一等
            code, out = run("ocr", "--bundle", str(bundle), "--allow-egress")
            self.assertEqual((code, [d["file"] for d in out["data"]["done"]]), (0, [png]))
            self.assertIn(10, sleeps)  # 等了第一档 10 秒再试
            self.assertEqual(len(self.server.ocr_uploads), 1)
            # 服务器一直不可用：不抛错、不动重试计数，文件标成可重试
            bundle2, png2 = self.scan_bundle("up2")
            self.server.ocr_jobs.clear()
            self.server.ocr_uploads.clear()
            self.server.ocr_upload_failures = 10 ** 6
            code, out = run("ocr", "--bundle", str(bundle2), "--allow-egress")
            self.assertEqual(code, 0, out)
            self.assertEqual([(f["file"], f["retryable"]) for f in out["data"]["failed"]], [(png2, True)])
            self.assertIn("键不变，不会重复建任务", out["data"]["failed"][0]["reason"])
            self.assertFalse((bundle2 / "ocr" / "attempts.json").exists())
            self.server.ocr_upload_failures = 0  # 恢复后重跑：还是第一个键（可能已经建过任务，会被拿回，不会重复）
            code, out = run("ocr", "--bundle", str(bundle2))
        self.assertEqual((code, [d["file"] for d in out["data"]["done"]]), (0, [png2]))
        self.assertTrue(self.upload_keys()[0].startswith("aicheck-node-audit-") and "-r" not in self.upload_keys()[0].split("audit-")[1])

    def test_report_needs_ocr_for_a_scanned_page_it_rests_on(self):
        bundle, png = self.scan_bundle("gate")
        run("search", "--bundle", str(bundle))
        fact = {"name": "证书", "value": "焊工证在", "source": {"file": png, "page": 1, "excerpt": "特种设备作业人员证"}}
        checks = [{"atomicCheckId": "AC-R24-01", "verdict": "passed", "facts": [fact], "reasoning": "证在有效期内。"},
                  *({"atomicCheckId": f"AC-R24-0{i}", "verdict": "evidence_insufficient", "reason": "缺记录"} for i in range(2, 6))]
        files = json.loads((bundle / "bundle.json").read_text(encoding="utf-8"))["files"]
        self.write_report(bundle, checks, [{"file": f["path"], "method": "ocr" if f["path"] == png else "text"} for f in files])
        self.assertIn(f"AC-R24-01: 确定结论引用的扫描页 {png} 第 1 页没有 OCR 文字", self.report_errors(bundle))
        self.login()
        self.server.ocr_result = self.certificate_result()
        with patch.object(na, "OCR_POLL_SECONDS", 0):
            self.assertEqual(run("ocr", "--bundle", str(bundle), "--allow-egress")[0], 0)
        code, out = run("report", "--bundle", str(bundle))
        self.assertEqual(code, 0, out)
    # ------------------------------------------------------------ 结果图（服务器用 HTML 模板渲染成 PNG）

    def audited_bundle(self, bundle: Path | None = None) -> Path:
        bundle = bundle or self.local_bundle()
        fact = {"name": "有效期至", "value": "2025-12", "source": {"file": "files/01-证书.pdf", "page": 1, "excerpt": "有效期至2025年12月"}}
        checks = [{"atomicCheckId": "AC-R24-01", "verdict": "failed", "facts": [fact], "reasoning": "证书有效期早于施焊日期。其余说明。",
                   "nextSteps": ["请施工方更换在有效期内的焊工"]},
                  *({"atomicCheckId": f"AC-R24-0{i}", "verdict": "evidence_insufficient", "reason": "缺施焊记录。",
                     "nextSteps": ["请施工方补施焊记录"]} for i in range(2, 6))]
        self.write_report(bundle, checks)
        return bundle

    def test_audit_image_body_mirrors_the_markdown_report_and_masks_ids(self):
        bundle = self.audited_bundle()
        manifest, report, errors_, _ = na.check_report(bundle)
        self.assertEqual(errors_, [])
        report["checks"][0]["agreesWithServer"], report["checks"][1]["agreesWithServer"] = False, True
        report["riskFlags"] = [{"level": "high", "flag": "设计材质超出全部已交证书", "basis": "AC-R24-02"}]
        body = na.audit_image_body(manifest, report, "焊工资格")
        self.assertEqual((body["outcome"], body["nodeId"], body["nodeName"], body["ruleId"]), ("failed", 24, "焊工资格", "R24"))
        self.assertEqual(body["outcomeExplain"], na.node_outcome(report["checks"])["explain"])
        first = body["checks"][0]
        self.assertEqual((first["atomicCheckId"], first["verdict"], first["reason"]), ("AC-R24-01", "failed", "证书有效期早于施焊日期。"))
        self.assertEqual(first["evidence"], na.check_evidence(report["checks"][0], limit=3))
        self.assertEqual([c["differsFromServer"] for c in body["checks"][:3]], [True, False, None])  # 服务器结论：不同／一致／没有
        self.assertTrue(all("**" not in step for step in body["nextSteps"]) and body["nextSteps"])  # markdown 粗体不进图
        self.assertEqual(body["riskFlags"], [{"level": "high", "flag": "设计材质超出全部已交证书", "basis": "AC-R24-02"}])
        report["summary"] = f"证件 {self.FULL_ID} 的持证人"
        self.assertNotIn(self.FULL_ID, json.dumps(na.audit_image_body(manifest, report), ensure_ascii=False))  # 证号再脱敏一遍

    def test_render_sends_only_the_summary_and_saves_the_image_privately(self):
        bundle = self.audited_bundle()
        self.login()
        code, out = run("render", "--bundle", str(bundle))
        self.assertEqual(code, 0, out)
        target = bundle / "audit.png"
        data = out["data"]
        self.assertEqual(([Path(p).resolve() for p in data["images"]], data["pageCount"], data["outcome"], data["bytes"]),
                         ([target.resolve()], 1, "不通过", len(PNG) + 1))
        self.assertEqual((target.read_bytes(), stat.S_IMODE(target.stat().st_mode)), (PNG + b"\x01", 0o600))
        [sent] = self.server.image_requests
        self.assertEqual((sent["outcome"], len(sent["checks"])), ("failed", 5))
        self.assertNotIn("facts", json.dumps(sent))  # 只发摘要，不发每项的事实全文
        self.assertEqual(self.server.requests[-1][2]["Authorization"], f"Bearer {TOKEN}")
        custom = Path(self.tmp.name) / "out" / "result.png"
        code, out = run("render", "--bundle", str(bundle), "--out", str(custom))
        self.assertEqual((code, custom.read_bytes(), [Path(p).resolve() for p in out["data"]["images"]]), (0, PNG + b"\x01", [custom.resolve()]))

    def test_a_long_result_comes_back_as_several_pages_saved_in_order_and_replacing_the_old_ones(self):
        bundle = self.audited_bundle()
        self.login()
        self.server.image_pages = 3
        code, out = run("render", "--bundle", str(bundle))
        self.assertEqual(code, 0, out)
        names = [Path(p).name for p in out["data"]["images"]]
        self.assertEqual((names, out["data"]["pageCount"]), (["audit-1.png", "audit-2.png", "audit-3.png"], 3))
        self.assertEqual([(bundle / n).read_bytes() for n in names], [PNG + bytes([n]) for n in (1, 2, 3)])  # 页序没乱
        self.assertTrue(all(stat.S_IMODE((bundle / n).stat().st_mode) == 0o600 for n in names))
        self.assertFalse((bundle / "audit.png").exists())
        self.server.image_pages = 2  # 重新审计后内容变短：上次多出来的第 3 页不能留着，否则会被当成这次结果的一部分
        code, out = run("render", "--bundle", str(bundle))
        self.assertEqual(sorted(p.name for p in bundle.glob("audit*.png")), ["audit-1.png", "audit-2.png"])
        self.server.image_pages = 1  # 变成一页：回到 audit.png，分页文件全部清掉
        code, out = run("render", "--bundle", str(bundle))
        self.assertEqual(sorted(p.name for p in bundle.glob("audit*.png")), ["audit.png"])
        custom = Path(self.tmp.name) / "out" / "result.png"  # --out 多页：在文件名后加页码，不动目录里别的文件
        (custom.parent).mkdir(parents=True)
        (custom.parent / "keep-me.png").write_bytes(b"x")
        self.server.image_pages = 2
        code, out = run("render", "--bundle", str(bundle), "--out", str(custom))
        self.assertEqual((code, sorted(p.name for p in custom.parent.iterdir())), (0, ["keep-me.png", "result-1.png", "result-2.png"]))

    def test_render_refuses_a_response_that_is_not_a_set_of_png_pages(self):
        bundle = self.audited_bundle()
        self.login()
        self.server.image_mode = "garbled"
        code, out = run("render", "--bundle", str(bundle))
        self.assertEqual((code, out["error"]["code"]), (1, "badResponse"))
        self.assertEqual(list(bundle.glob("audit*.png")), [])  # 不留任何半成品
        self.server.image_mode = "png"
        self.server.image_pages = na.MAX_IMAGE_PAGES + 1
        code, out = run("render", "--bundle", str(bundle))
        self.assertEqual((code, out["error"]["code"]), (1, "badResponse"))
        self.assertEqual(list(bundle.glob("audit*.png")), [])

    def test_render_needs_a_valid_report_and_a_login_and_sends_nothing_otherwise(self):
        bundle = self.local_bundle()
        self.login()
        self.write_report(bundle, [{"atomicCheckId": "AC-R24-01", "verdict": "passed"}])  # 缺检查、缺事实
        code, out = run("render", "--bundle", str(bundle))
        self.assertEqual((code, out["error"]["code"]), (1, "reportInvalid"))
        good = self.audited_bundle(bundle)  # 同一个资料包改成合格的审计结果
        self.session.unlink()
        code, out = run("render", "--bundle", str(good))
        self.assertEqual((code, out["error"]["code"]), (1, "loginRequired"))
        self.assertEqual(self.server.image_requests, [])
        self.assertEqual(list(good.glob("audit*.png")), [])

    def test_render_explains_a_server_without_the_endpoint_and_an_expired_login(self):
        bundle = self.audited_bundle()
        self.login()
        self.server.image_mode = "missing"
        code, out = run("render", "--bundle", str(bundle))
        self.assertEqual((code, out["error"]["code"]), (1, "renderNotDeployed"))
        self.assertIn("audit.md", out["error"]["message"])
        self.server.image_mode = "auth200"  # 这个服务器的业务错误是 HTTP 200 + JSON（code 401），不能当成图片存下来
        code, out = run("render", "--bundle", str(bundle))
        self.assertEqual((code, out["error"]["code"]), (1, "loginRequired"))
        self.assertIn("重新 login", out["error"]["message"])
        self.assertEqual(list(bundle.glob("audit*.png")), [])

    def test_render_waits_out_one_gateway_error_during_a_restart(self):
        bundle = self.audited_bundle()
        self.login()
        with patch.object(na, "GATEWAY_RETRY_SECONDS", 0):
            self.server.image_gateway_failures = 1
            code, out = run("render", "--bundle", str(bundle))
            self.assertEqual((code, (bundle / "audit.png").read_bytes()), (0, PNG + b"\x01"))
            (bundle / "audit.png").unlink()
            self.server.image_gateway_failures = 2  # 重试一次还是 502：报错，不留半张图
            code, out = run("render", "--bundle", str(bundle))
        self.assertEqual((code, out["error"]["code"]), (1, "http502"))
        self.assertEqual(list(bundle.glob("audit*.png")), [])


    # ------------------------------------------------------------ report 直接给出完整结果

    def test_report_returns_the_complete_result_not_just_the_path(self):
        bundle = self.audited_bundle()
        code, out = run("report", "--bundle", str(bundle))
        self.assertEqual(code, 0, out)
        data = out["data"]
        self.assertEqual(data["fullReport"], (bundle / "audit.md").read_text(encoding="utf-8"))  # 和文件一字不差
        self.assertEqual(Path(data["markdown"]).resolve(), (bundle / "audit.md").resolve())
        for number in range(1, 6):
            self.assertIn(f"### AC-R24-0{number}", data["fullReport"])  # 每一项都在，不只是有问题的
        for needle in ("证书有效期早于施焊日期", "有效期至", "2025-12", "files/01-证书.pdf 第1页", "缺施焊记录",
                       "请施工方更换在有效期内的焊工", "## 逐项明细", "## 已阅读文件"):
            self.assertIn(needle, data["fullReport"])
        self.assertIn("fullReport", data["next"])  # 提示助手把它贴给用户

    def test_audit_md_prints_the_coverage_line_only_when_something_was_counted(self):
        bundle = self.local_bundle()
        blank = {"items": None, "checked": None, "source": ""}  # skeleton 留下的空统计，不是统计结果
        self.write_report(bundle, [
            {"atomicCheckId": "AC-R24-01", "verdict": "evidence_insufficient", "reason": "缺施焊记录。", "coverage": blank},
            {"atomicCheckId": "AC-R24-02", "verdict": "evidence_insufficient", "reason": "只知道总数。", "coverage": {"items": 5, "checked": None, "source": ""}},
            {"atomicCheckId": "AC-R24-03", "verdict": "evidence_insufficient", "reason": "只核了三道。", "coverage": {"items": 5, "checked": 3, "source": "施焊记录"}},
            {"atomicCheckId": "AC-R24-04", "verdict": "evidence_insufficient", "reason": "没统计。"},
            {"atomicCheckId": "AC-R24-05", "verdict": "evidence_insufficient", "reason": "没统计。", "coverage": None},
        ])
        code, out = run("report", "--bundle", str(bundle))
        self.assertEqual(code, 0, out)
        text = out["data"]["fullReport"]
        self.assertNotIn("None", text)  # 回归：曾打印「逐件覆盖：None/None（）」
        self.assertEqual(text.count("逐件覆盖"), 2)
        self.assertIn("逐件覆盖：未知/5\n", text)  # 只知道一半就写未知，不打印 None，也没有空括号
        self.assertIn("逐件覆盖：3/5（施焊记录）", text)


    def test_every_bundle_command_reports_a_wrong_path_as_json_not_a_traceback(self):
        """回归：report／render 对不存在的资料包目录直接抛 FileNotFoundError，助手看到的是一屏 Traceback。"""
        missing = str(Path(self.tmp.name) / "no-such-bundle")
        for command in (["report"], ["render"], ["skeleton"], ["sync"], ["ocr"], ["search"]):
            code, out = run(*command, "--bundle", missing)
            self.assertEqual((code, out["ok"], out["error"]["code"]), (1, False, "bundleMissing"), command)
            self.assertIn("fetch", out["error"]["message"])
        self.assertEqual(self.server.requests, [])  # 路径不对就什么都不发


if __name__ == "__main__":
    unittest.main()
