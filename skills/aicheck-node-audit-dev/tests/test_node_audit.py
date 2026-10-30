"""Node audit helper against a fake AIcheck server; no real accounts or project data."""
from __future__ import annotations

import base64
import contextlib
import hashlib
import importlib.util
import io
import json
import os
import re
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
        self.workspace_mode = "ok"  # auth200 | forbidden200 | missing200：生产的业务错误是 HTTP 200 + 数字 code
        # 服务器 OCR 接口的测试桩：上传、查状态、取结果（同 apps/api/mineru_ocr_routes）
        self.ocr_uploads: list[tuple[dict, bytes]] = []  # (请求头, 正文)
        self.ocr_jobs: dict[str, str] = {}  # Idempotency-Key → jobId
        self.ocr_running_polls = 0  # 状态查询先回几次 running
        self.ocr_final = {"status": "success", "provider": "mineru"}
        self.ocr_job_status: dict[str, dict] = {}  # 个别任务的状态（如上次留下的失败任务），盖过 ocr_final
        self.ocr_result: dict = {}
        self.image_mode = "png"  # png | missing（服务器没部署）| auth200（HTTP 200 里藏着没登录的 JSON）| garbled（页内容不是 PNG）
        self.image_pages = 1  # 服务器这次渲染出几页
        self.skill_codes: dict[str, tuple[str, str]] = {}  # 网页授权：授权码 → (code_challenge, 回调地址)
        self.image_requests: list[dict] = []
        self.image_gateway_failures = 0
        self.ocr_status_failures = 0  # 查状态、取结果先回几次 502（API 重启中）
        self.ocr_upload_failures = 0  # 上传先回几次 502
        self.ocr_status_mode = "ok"  # missing：任务被服务器清理（HTTP 200 + 40404）；auth：令牌过期（HTTP 200 + 401）
        self.download_failures = 0  # 下载原件先回几次 502
        self.calls: list[tuple[str, dict]] = []  # 下面这些只读接口收到的 (路径, 查询或正文)
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
                    self.send_json({"reason": "AUTH_REQUIRED"}, status=200, code=401, message="请先登录。")
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
                if path in {"/api/readyz", "/api/inspection-services/capabilities"} or path.startswith("/api/inspection-services/standards/"):
                    outer.calls.append((path, parse_qs(urlsplit(self.path).query)))
                    self.send_json({"ready": True} if path == "/api/readyz" else
                                   {"tools": ["certificate-registry"]} if path.endswith("capabilities") else
                                   {"fileId": path.split("/")[-2], "text": "D2.6.1 焊工（B 类）"})
                    return
                if not self.authed():
                    return
                if path == "/api/auth/me":
                    self.send_json({"user": {"username": "zhang", "role": "inspection", "displayName": "张", "token": "x"}})
                    return
                if path.startswith("/api/internal/ocr/mineru/tasks/") and outer.ocr_status_mode != "ok":
                    code = {"missing": 40404, "auth": 401}[outer.ocr_status_mode]
                    self.send_json({"reason": "X"}, status=200, code=code, message="对象不存在或无权访问。" if code == 40404 else "请先登录。")
                    return
                if path.startswith("/api/internal/ocr/mineru/tasks/") and outer.ocr_status_failures > 0:
                    outer.ocr_status_failures -= 1
                    self.send_json(None, status=502, code="BAD_GATEWAY", message="Bad Gateway")
                    return
                if path.startswith("/api/internal/ocr/mineru/tasks/") and path.endswith("/result"):
                    self.send_json(outer.ocr_result)
                    return
                if path.startswith("/api/internal/ocr/mineru/tasks/"):
                    job = path.rsplit("/", 1)[-1]
                    outer.calls.append((path, {}))
                    if job in outer.ocr_job_status:
                        self.send_json({"jobId": job, "recommendedPollSeconds": 0, **outer.ocr_job_status[job]})
                        return
                    running = outer.ocr_running_polls > 0
                    outer.ocr_running_polls -= 1 if running else 0
                    self.send_json({"jobId": job, "recommendedPollSeconds": 0,
                                    **({"status": "running", "provider": "mineru", "statusMessage": "MinerU 正在处理文件。"}
                                       if running else outer.ocr_final)})
                    return
                if path == f"{node}/audit-workspace" and outer.workspace_mode != "ok":
                    business = {"auth200": 401, "forbidden200": 403, "missing200": 40404}[outer.workspace_mode]
                    self.send_json({"reason": "X"}, status=200, code=business, message="服务器拒绝。")
                elif path == f"{node}/audit-workspace":
                    self.send_json(outer.workspace)
                elif path == f"{node}/rules/current-version":
                    self.send_json({"rule": outer.server_rule})
                elif path == f"{node}/standards":
                    self.send_json([{"standardName": "TSG D7006", "clauseNo": "D2.6.1"}])
                elif path == f"{node}/evidence-chain":
                    self.send_json({"reason": "FORBIDDEN"}, status=200, code=403, message="当前角色无权执行该操作。")
                elif path == "/api/review-runs/RRUN-NEW":
                    self.send_json({"run": {"reviewRunId": "RRUN-NEW", "atomicCheckOutcomes": [
                        {"atomicCheckId": "AC-R24-01", "result": "evidence_insufficient", "decisionSource": "rule_engine"},
                        {"atomicCheckId": "AC-R24-05", "result": "passed", "decisionSource": "rule_engine"}]}})
                elif path == "/api/projects/P-T/documents/DOC-1/original" and outer.download_failures > 0:
                    outer.download_failures -= 1
                    self.send_json(None, status=502, code="BAD_GATEWAY", message="Bad Gateway")
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
                if path == "/api/inspection-services/certificate-validity":
                    outer.calls.append((path, body))
                    self.send_json({"conclusion": "valid", "certificates": body["certificates"]})
                    return
                if path in {"/api/auth/logout", "/api/cnse/organizations/search"}:
                    if self.authed():
                        outer.calls.append((path, body))
                        self.send_json({"loggedOut": True} if path.endswith("logout") else {"items": [{"name": body["keyword"], "licenseNo": "TS1234567-2030"}]})
                    return
                if path == "/api/auth/skill/token":
                    import hashlib as _h

                    challenge, redirect = outer.skill_codes.pop(str(body.get("code")), ("", ""))
                    verifier = str(body.get("codeVerifier") or "")
                    expected = base64.urlsafe_b64encode(_h.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
                    if challenge and expected == challenge and body.get("redirectUri") == redirect:
                        self.send_json({"token": "web-token", "user": {"username": "zhang", "role": "inspection"}})
                    else:
                        self.send_json(None, status=400, code=40001, message="授权码无效、已用过或已过期")
                elif path == "/api/inspection-services/certificate-registry" and outer.gateway_failures:
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

    def test_server_json_is_masked_in_the_bundle_and_the_raw_copy_still_serves_the_registry(self):
        full, masked = "110101199001011237", "1101**********1237"
        self.login()
        fields = [{"documentVersionId": "V-1", "fieldName": "身份证号", "fieldValue": full, "pageNo": 1, "confidence": 0.9}]
        self.server.workspace = {**WORKSPACE, "content": {**WORKSPACE["content"], "ocr": {"extractedFields": fields}}}
        out_dir = Path(self.tmp.name) / "masked"
        code, out = run("fetch", "--project", "P-T", "--node", "24", "--out", str(out_dir))
        self.assertEqual(code, 0, out)
        # 助手会读的那几份（根目录 JSON、摘要）只有脱敏号；原文在 ocr/server/ 下，只给脚本回查
        for name in ("workspace.json", "review-run.json", "digest.md"):
            text = (out_dir / name).read_text(encoding="utf-8")
            self.assertNotIn(full, text, name)
            self.assertFalse(na.contains_id_number(text), name)
        self.assertIn(masked, (out_dir / "workspace.json").read_text(encoding="utf-8"))
        raw = out_dir / "ocr" / "server" / "workspace.json"
        self.assertIn(full, raw.read_text(encoding="utf-8"))
        self.assertEqual(stat.S_IMODE(raw.stat().st_mode), 0o600)
        # 原件是打不开的假 PDF、没跑 OCR：完整号码只在服务器 JSON 原文里，脱敏号照样查得了登记
        code, out = run("cert-registry", "--kind", "person", "--identifier", masked, "--bundle", str(out_dir))
        self.assertEqual(code, 0, out)
        self.assertEqual(self.server.requests[-1][2]["_body"]["identifier"], full)
        self.assertEqual(out["data"]["records"]["person"]["sfzh"], masked)

    def test_business_errors_inside_http_200_are_translated_like_http_errors(self):
        self.login()
        for mode, expected, server_code in (("auth200", "loginRequired", "401"), ("forbidden200", "forbidden", "403"),
                                            ("missing200", "notFound", "40404")):
            self.server.workspace_mode = mode
            code, out = run("fetch", "--project", "P-T", "--node", "24", "--out", str(Path(self.tmp.name) / mode))
            self.assertEqual((code, out["error"]["code"], out["error"]["serverCode"]), (1, expected, server_code), out)
            self.assertFalse((Path(self.tmp.name) / mode).exists())  # 拿不到工作区就不建包
            if expected == "loginRequired":
                self.assertIn("login --web", out["error"]["message"])

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
        # --pages 只转指定页，存成带页码的文件，不覆盖整份转出的那份
        code, out = run("text", "--file", str(mixed), "--pages", "1")
        self.assertEqual((code, out["data"]["readPages"], out["data"]["pages"]), (0, "1", 2), out)
        self.assertNotIn("pagesWithoutText", out["data"])
        part = Path(out["data"]["saved"])
        self.assertEqual(part.name, "10-方案.p1.txt")
        self.assertIn("--- 第 1 页 ---", part.read_text(encoding="utf-8"))
        self.assertNotIn("第 2 页", part.read_text(encoding="utf-8"))
        self.assertIn("第 2 页", (bundle / "text" / "10-方案.txt").read_text(encoding="utf-8"))
        self.assertEqual(run("text", "--file", str(mixed), "--pages", "2")[1]["data"]["pagesWithoutText"], "2")
        self.assertEqual(run("text", "--file", str(mixed), "--pages", "3")[1]["error"]["code"], "pageOutOfRange")
        long_pdf = bundle / "files" / "11-长文件.pdf"
        with fitz.open() as doc:
            for n in range(1, 22):
                doc.new_page().insert_text((72, 72), f"第{n}页 焊接记录 焊口编号 W{n:03d} 焊工钢印 足够多的文字", fontname="china-s")
            doc.save(long_pdf)
        whole = run("text", "--file", str(long_pdf))[1]["data"]
        self.assertIn("--pages", whole["readHint"])  # 整份超过 20 页就提示按命中页读
        code, out = run("text", "--file", str(long_pdf), "--pages", "2-3,21")
        self.assertEqual((code, out["data"]["readPages"], Path(out["data"]["saved"]).name), (0, "2-3,21", "11-长文件.p2-3_21.txt"))
        self.assertNotIn("readHint", out["data"])
        self.assertEqual(re.findall(r"--- 第 (\d+) 页", Path(out["data"]["saved"]).read_text(encoding="utf-8")), ["2", "3", "21"])
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

    def test_masking_also_hides_misread_and_spaced_numbers_but_leaves_other_codes_alone(self):
        # OCR 读错一位（校验位对不上）、号码被拆成 6+8+4 段：都要遮；以 9 开头的信用代码、嵌着日期的 18 位单号不遮
        self.assertEqual(na.mask_ids("号码 110101199001011238（校验位错）"), "号码 1101**********1238（校验位错）")
        self.assertEqual(na.mask_ids("号码 110101 19900101 1237 末"), "号码 1101**********1237 末")
        untouched = "单号 202610271234567890 信用代码 91110000600000001X 哈希 ab110101199001011237cd"
        self.assertEqual(na.mask_ids(untouched), untouched)
        self.assertTrue(na.contains_id_number("110101199001011238"))
        self.assertFalse(na.is_id_number("110101199001011238"))
        self.assertTrue(na.is_id_number("110101 19900101 1237"))
        # 读错一位的号码：search 列出脱敏号，查登记时脚本找回它、校验不过就交人工，不去平台、不让助手看图重读
        misread, masked = "110101199001011238", "1101**********1238"
        root = self.project_dir()
        (root / "焊工名单.txt").write_text(f"焊工 李四 身份证号 {misread}", encoding="utf-8")
        bundle = Path(run("local-init", "--node", "24", "--project-dir", str(root), "--out", str(Path(self.tmp.name) / "misread"))[1]["data"]["bundle"])
        code, out = run("search", "--bundle", str(bundle), "--terms", "身份证号")
        self.assertEqual(code, 0, out)
        self.assertIn(masked, out["data"]["idNumbersInText"])
        before = len(self.server.requests)
        code, out = run("cert-registry", "--kind", "person", "--identifier", masked, "--bundle", str(bundle))
        self.assertEqual((code, out["error"]["code"], len(self.server.requests)), (1, "idChecksumFailed", before), out)
        self.assertIn("交人工", out["error"]["message"])
        self.assertNotIn("--clip", out["error"]["message"])

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
        # 合并单元格在所跨的每一行都重复：逐行读就知道“机动焊”这一行的厚度也是“自定”；横跨的只写一次、标跨几列
        self.assertEqual(na.table_text(html).splitlines(), ["板 | 手工焊 | 自定", "板 | 机动焊 | 自定", "管 | <25（跨2列）"])
        spans = ('<table><tr><td colspan="3">化学成分%</td></tr><tr><td>C</td><td>Mn</td><td>Si</td></tr>'
                 '<tr><td rowspan="2" colspan="2">合格</td><td>a</td></tr><tr><td>b</td></tr>'
                 '<tr><td colspan="2"></td><td>c</td></tr></table>')
        self.assertEqual(na.table_text(spans).splitlines(),
                         ["化学成分%（跨3列）", "C | Mn | Si", "合格（跨2列） | a", "合格（跨2列） | b", " | c"])
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
        # 失败了当场换新任务重传一次；第二次还失败才报，并说明已经重试过
        self.assertEqual(out["data"]["failed"], [{"file": png, "reason": "服务器 OCR failed：QWEN_OCR_FAILED", "autoRetried": True}])
        self.assertEqual((out["data"]["retried"], len(self.server.ocr_uploads)), ([png], 2))
        self.assertIn("不要反复重跑", out["data"]["nextStep"])
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
            # 这一次命令里：第一个任务失败 → 当场换键 r1 重传 → 又失败；两次都记下
            self.assertEqual(json.loads((bundle / "ocr" / "attempts.json").read_text(encoding="utf-8")), {sha: 2})
            # 重跑（不加 --force）：同一个键服务器会拿回失败的老任务；换了键才建新任务，这次成功
            self.server.ocr_final = {"status": "success", "provider": "mineru"}
            self.server.ocr_result = self.certificate_result()
            code, out = run("ocr", "--bundle", str(bundle))
        self.assertEqual(code, 0, out)
        self.assertEqual([d["file"] for d in out["data"]["done"]], [png])
        keys = self.upload_keys()
        self.assertEqual(keys, [f"aicheck-node-audit-{sha[:48]}", f"aicheck-node-audit-{sha[:48]}-r1", f"aicheck-node-audit-{sha[:48]}-r2"])
        self.assertEqual(len(self.server.ocr_jobs), 3)  # 三个任务：失败的、当场重试又失败的、这次成功的
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
            # 没传上去不是识别失败：单列 notUploaded，failed 里只放真失败
            self.assertEqual((out["data"]["notUploaded"], out["data"]["failed"]), ([png2], []))
            self.assertIn("键不变，不会重复建任务", out["data"]["nextStep"])
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
    def test_report_checks_the_excerpt_against_the_cited_page(self):
        bundle, png = self.scan_bundle("excerpt")
        self.login()
        self.server.ocr_result = self.certificate_result()
        with patch.object(na, "OCR_POLL_SECONDS", 0):
            self.assertEqual(run("ocr", "--bundle", str(bundle), "--allow-egress")[0], 0)
        run("search", "--bundle", str(bundle))
        files = json.loads((bundle / "bundle.json").read_text(encoding="utf-8"))["files"]
        reviewed = [{"file": f["path"], "method": "ocr" if f["path"] == png else "text"} for f in files]

        def report(excerpt: str, verdict: str = "passed") -> tuple[int, dict]:
            fact = {"name": "证书", "value": "在", "source": {"file": png, "page": 1, "excerpt": excerpt}}
            head = {"atomicCheckId": "AC-R24-01", "verdict": verdict, "facts": [fact], "reasoning": "理由。", "reason": "理由。"}
            checks = [head, *({"atomicCheckId": f"AC-R24-0{i}", "verdict": "evidence_insufficient", "reason": "缺记录"} for i in range(2, 6))]
            self.write_report(bundle, checks, reviewed)
            return run("report", "--bundle", str(bundle))

        # 照抄的摘录都过：脱敏号对得上 OCR 原文里的完整号，表格竖线、空白、省略号隔开的几段、印章行都容得下
        for excerpt in (f"证书编号 {self.MASKED_ID} 有效期至 2027 年 3 月", "项目代号 GTAW-FeⅡ-6G-3/60-FefS-02/10/12",
                        "特种设备作业人员证…有效期至 2027 年", "[印章：某某市市场监督管理局]"):
            code, out = report(excerpt)
            self.assertEqual(code, 0, (excerpt, out))
        # 改写或编造的摘录：符合／不符合项算错误，其他结论只警告
        code, out = report("有效期至 2030 年 3 月")
        self.assertEqual(code, 1, out)
        self.assertTrue(any("摘录「有效期至 2030 年 3 月」不在" in e for e in out["error"]["errors"]), out)
        code, out = report("有效期至 2030 年 3 月", verdict="human_review_required")
        self.assertEqual(code, 0, out)
        self.assertTrue(any("摘录「有效期至 2030 年 3 月」不在" in w for w in out["data"]["warnings"]), out)

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


    # ------------------------------------------------------------ login --web（浏览器授权，回调本机）

    def fake_browser(self, action: str = "approve", wrong_state_first: bool = False):
        """替代 webbrowser.open：解开授权链接，像用户在网页上点了授权/拒绝那样请求本机回调地址。"""
        from urllib.error import HTTPError
        from urllib.request import urlopen

        seen: dict = {}

        def open_(url: str) -> bool:
            payload = url.split("#/skill-authorize/", 1)[1]
            request_ = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
            seen.update(url=url, request=request_)
            if action == "ignore":
                return True

            def click():
                if wrong_state_first:
                    try:
                        urlopen(f"{request_['r']}?code=STOLEN&state=not-the-state", timeout=5)
                    except HTTPError as exc:
                        seen["wrongStateStatus"] = exc.code
                if action == "deny":
                    urlopen(f"{request_['r']}?error=access_denied&state={request_['s']}", timeout=5).read()
                    return
                code = "CODE-" + request_["s"][:12]
                self.server.skill_codes[code] = (request_["c"], request_["r"])
                urlopen(f"{request_['r']}?code={code}&state={request_['s']}", timeout=5).read()

            threading.Thread(target=click, daemon=True).start()
            return True

        return seen, patch("webbrowser.open", open_)

    def test_web_login_saves_a_token_without_any_password_and_needs_no_terminal(self):
        seen, browser = self.fake_browser()
        with browser, patch("sys.stdin", io.StringIO("")):  # 没有终端也能跑：口令只在浏览器里输
            code, out = run("login", "--web", "--timeout", "20")
        self.assertEqual(code, 0, out)
        self.assertEqual((out["data"]["username"], out["data"]["role"]), ("zhang", "inspection"))
        saved = json.loads(self.session.read_text(encoding="utf-8"))
        self.assertEqual((saved["token"], saved["baseUrl"], saved["method"]), ("web-token", self.server.url, "web"))
        self.assertEqual(stat.S_IMODE(self.session.stat().st_mode), 0o600)
        request_ = seen["request"]
        self.assertRegex(request_["r"], r"^http://127\.0\.0\.1:\d+/callback$")  # 只回调本机
        self.assertTrue(seen["url"].startswith(f"{self.server.url}/#/skill-authorize/"))
        [(_, _, headers)] = [r for r in self.server.requests if r[1] == "/api/auth/skill/token"]
        self.assertNotIn("Authorization", headers)  # 换令牌这一步不带任何令牌
        self.assertEqual(headers["_body"]["redirectUri"], request_["r"])
        self.assertNotIn(headers["_body"]["codeVerifier"], seen["url"])  # 校验码从没出现在浏览器链接里

    def test_web_login_ignores_a_callback_with_the_wrong_state(self):
        seen, browser = self.fake_browser(wrong_state_first=True)
        with browser:
            code, out = run("login", "--web", "--timeout", "20")
        self.assertEqual((code, seen["wrongStateStatus"]), (0, 400), out)
        self.assertEqual(json.loads(self.session.read_text(encoding="utf-8"))["token"], "web-token")

    def test_web_login_reports_a_denial_and_a_timeout_and_saves_nothing(self):
        _, browser = self.fake_browser("deny")
        with browser:
            code, out = run("login", "--web", "--timeout", "20")
        self.assertEqual((code, out["error"]["code"]), (1, "webLoginDenied"))
        _, browser = self.fake_browser("ignore")
        with browser:
            code, out = run("login", "--web", "--timeout", "1")
        self.assertEqual((code, out["error"]["code"]), (1, "webLoginTimeout"))
        self.assertIn("#/skill-authorize/", out["error"]["authorizeUrl"])  # 超时也把链接给出来，方便手动打开
        self.assertFalse(self.session.exists())

    def test_web_login_prints_the_link_and_can_skip_opening_a_browser(self):
        err = io.StringIO()
        with patch("webbrowser.open") as opener, contextlib.redirect_stderr(err):
            _, out = run("login", "--web", "--no-browser", "--timeout", "1")
        opener.assert_not_called()
        self.assertEqual(out["error"]["code"], "webLoginTimeout")
        self.assertIn("#/skill-authorize/", err.getvalue())  # 链接先打到 stderr，助手可以发给用户

    def test_password_login_still_needs_a_username_and_a_terminal(self):
        _, out = run("login")
        self.assertEqual(out["error"]["code"], "usernameRequired")
        with patch("sys.stdin", io.StringIO("")):
            _, out = run("login", "--username", "inspector")
        self.assertEqual(out["error"]["code"], "ttyRequired")
        self.assertIn("login --web", out["error"]["message"])

    # ------------------------------------------------------------ 中危修复（2026-10-28）

    def test_out_into_an_existing_shared_directory_leaves_its_permissions_alone(self):
        shared = Path(self.tmp.name) / "shared"
        shared.mkdir(mode=0o755)
        os.chmod(shared, 0o755)
        code, out = run("local-init", "--node", "24", "--files", str(self.sample_file()), "--out", str(shared / "a" / "b"))
        self.assertEqual(code, 0, out)
        self.assertEqual(stat.S_IMODE(shared.stat().st_mode), 0o755)  # 本来就有、在审计目录外：不动
        for created in (shared / "a", shared / "a" / "b"):
            self.assertEqual(stat.S_IMODE(created.stat().st_mode), 0o700, created)  # 这次新建的：只有自己能进

    def test_a_download_hit_by_a_restart_is_retried_and_a_lost_one_must_be_named_in_the_report(self):
        self.login()
        self.server.download_failures = 1
        with patch.object(na, "GATEWAY_RETRY_SECONDS", 0):
            code, out = run("fetch", "--project", "P-T", "--node", "24", "--out", str(Path(self.tmp.name) / "retry"))
        self.assertEqual(code, 0, out)
        self.assertEqual(out["data"]["files"], 1)  # 502 一次之后重试拿到了
        self.server.download_failures = 2
        bundle = Path(self.tmp.name) / "lost"
        with patch.object(na, "GATEWAY_RETRY_SECONDS", 0):
            code, out = run("fetch", "--project", "P-T", "--node", "24", "--out", str(bundle))
        self.assertEqual(code, 0, out)
        [lost] = out["data"]["skippedFiles"]
        self.assertTrue(lost["downloadFailed"])
        self.assertTrue(any("没下载到" in w for w in out["data"]["warnings"]))
        checks = [{"atomicCheckId": f"AC-R24-0{i}", "verdict": "evidence_insufficient", "reason": "缺记录"} for i in range(1, 6)]
        self.write_report(bundle, checks, [])
        self.assertIn("资料包缺原件 焊工证/张三.pdf", self.report_errors(bundle))
        report = json.loads((bundle / "audit.json").read_text(encoding="utf-8"))
        report["limitations"] = ["焊工资格证（张三.pdf）没下载到，AC-R24-01 无法核对"]
        (bundle / "audit.json").write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
        code, out = run("report", "--bundle", str(bundle))
        self.assertEqual(code, 0, out)

    def test_two_lookups_in_the_same_second_keep_separate_archives(self):
        bundle = self.local_bundle()
        ticks = iter(range(1, 1000))  # 时钟永远停在同一秒，只有微秒在走
        with patch.object(na, "datetime", wraps=na.datetime) as clock:
            clock.now.side_effect = lambda *_: na.datetime(2026, 10, 28, 9, 0, 0, next(ticks))
            saved = {run("search", "--bundle", str(bundle))[1]["data"]["saved"] for _ in range(2)}
        self.assertEqual(len(saved), 2)
        self.assertEqual(len(list((bundle / "search").glob("*.json"))), 2)

    def test_ocr_polling_gives_up_on_a_vanished_job_and_keeps_waiting_through_an_expired_login(self):
        bundle, _ = self.scan_bundle("vanish")
        self.login()
        self.server.ocr_running_polls = 99
        with patch.object(na, "OCR_POLL_SECONDS", 0):
            code, out = run("ocr", "--bundle", str(bundle), "--allow-egress", "--timeout", "0")
        self.assertEqual((code, len(out["data"]["pending"])), (0, 1), out)
        self.server.ocr_status_mode = "auth"  # 令牌过期：中断，但待办留着，重新授权后接着等
        code, out = run("ocr", "--bundle", str(bundle), "--timeout", "0")
        self.assertEqual((code, out["error"]["code"]), (1, "loginRequired"))
        self.assertEqual(len(json.loads((bundle / "ocr" / "pending.json").read_text(encoding="utf-8"))), 1)
        self.server.ocr_status_mode = "missing"  # 任务被服务器清理：这一份算失败，不再每次卡在这里
        code, out = run("ocr", "--bundle", str(bundle), "--timeout", "0")
        self.assertEqual(code, 0, out)
        self.assertIn("notFound", out["data"]["failed"][0]["reason"])
        self.assertFalse((bundle / "ocr" / "pending.json").exists())
        self.server.ocr_status_mode, self.server.ocr_running_polls = "ok", 0
        self.server.ocr_result = self.certificate_result()
        uploads = len(self.server.ocr_uploads)
        with patch.object(na, "OCR_POLL_SECONDS", 0):
            code, out = run("ocr", "--bundle", str(bundle))
        self.assertEqual((code, len(out["data"]["done"])), (0, 1), out)
        self.assertEqual(len(self.server.ocr_uploads), uploads + 1)
        self.assertTrue(self.server.ocr_uploads[-1][0]["Idempotency-Key"].endswith("-r1"))  # 换新键，建新任务

    @unittest.skipUnless(importlib.util.find_spec("fitz"), "PyMuPDF 未安装")
    def test_a_scan_with_a_few_lines_of_text_layer_still_counts_as_a_scanned_page(self):
        import fitz
        source = Path(self.tmp.name) / "扫描带页眉.pdf"
        lines = "\n".join(["Header line of scanner software 2026-10-28"] * 3)  # 约 130 字的垃圾文字层
        with fitz.open() as doc:
            doc.new_page().insert_text((72, 72), "\n".join(["Plain text page with enough words to read."] * 8))
            page = doc.new_page()
            page.insert_image(page.rect, stream=PNG)  # 一张图铺满整页
            page.insert_text((72, 72), lines)
            small = doc.new_page()
            small.insert_image(fitz.Rect(0, 0, 60, 60), stream=PNG)  # 小 logo 不算
            small.insert_text((72, 72), lines)
            doc.save(source)
        layer = na.file_text(source)[1]
        self.assertTrue(all(len(t.strip()) >= 50 for t in layer), layer)
        self.assertEqual(na.scan_pages(source, layer), {2})
        self.assertEqual(na.ocr_reason(source), "第 2 页是扫描页")

    def test_ocr_reformats_an_old_record_from_the_finished_job_without_uploading_again(self):
        bundle, png = self.scan_bundle("rerender")
        self.login()
        self.server.ocr_result = self.certificate_result()
        with patch.object(na, "OCR_POLL_SECONDS", 0):
            self.assertEqual(run("ocr", "--bundle", str(bundle), "--allow-egress")[0], 0)
        record_path = na.ocr_record_path(bundle, png)
        old = json.loads(record_path.read_text(encoding="utf-8"))
        old.pop("renderVersion")  # 改排版之前存的记录
        record_path.write_text(json.dumps(old, ensure_ascii=False), encoding="utf-8")
        text = run("text", "--file", str(bundle / png), "--bundle", str(bundle))[1]["data"]
        self.assertIn("ocrOutdated", text)
        uploads = len(self.server.ocr_uploads)
        with patch.object(na, "OCR_POLL_SECONDS", 0):
            code, out = run("ocr", "--bundle", str(bundle))
        self.assertEqual(code, 0, out)
        self.assertEqual((out["data"]["rerendered"], len(self.server.ocr_uploads)), ([png], uploads))
        self.assertEqual(json.loads(record_path.read_text(encoding="utf-8"))["renderVersion"], na.OCR_RENDER_VERSION)
        # 服务器上那个任务没了：只记一次，旧文字照用，下次不再重试
        old["renderVersion"] = 1
        record_path.write_text(json.dumps(old, ensure_ascii=False), encoding="utf-8")
        self.server.ocr_status_mode = "missing"
        code, out = run("ocr", "--bundle", str(bundle))
        self.assertEqual(code, 0, out)
        self.assertTrue(out["data"]["failed"][0]["rerender"])
        self.assertNotIn("换新任务", out["data"].get("nextStep", ""))
        code, out = run("ocr", "--bundle", str(bundle))
        self.assertEqual((out["data"]["cached"], out["data"]["failed"]), ([png], []))
        self.assertEqual(len(self.server.ocr_uploads), uploads)

    def test_reading_records_must_match_the_bundle(self):
        bundle, png = self.scan_bundle("methods")
        run("search", "--bundle", str(bundle))
        files = json.loads((bundle / "bundle.json").read_text(encoding="utf-8"))["files"]
        other = next(f["path"] for f in files if f["path"] != png)
        checks = [{"atomicCheckId": f"AC-R24-0{i}", "verdict": "evidence_insufficient", "reason": "缺记录"} for i in range(1, 6)]
        self.write_report(bundle, checks, [{"file": png, "method": "ocr"}, {"file": other, "method": "text"}])
        self.assertIn(f"reviewedFiles {png}: 标了 ocr，但资料包里没有这份原件的 OCR 文字", self.report_errors(bundle))
        self.write_report(bundle, checks, [{"file": png, "method": "text"}, {"file": other, "method": "text"}])
        self.assertIn(f"reviewedFiles {png}: 是扫描件、没有文字层，text 读不到字", self.report_errors(bundle))
        self.write_report(bundle, checks, [{"file": png, "method": "pages"}, {"file": other, "method": "text"}])
        code, out = run("report", "--bundle", str(bundle))
        self.assertEqual(code, 0, out)  # 旧报告（看图写法）仍能复核，只警告
        self.assertTrue(any("看图的旧写法 pages" in w for w in out["data"]["warnings"]))

    def test_sync_matches_an_excerpt_copied_from_skill_text_against_the_server_quote(self):
        full, masked = "110101199001011237", "1101**********1237"
        link = {"id": "EL-1", "documentVersionId": "V-1", "manualStatus": "confirmed", "pageNo": 2, "bbox": [0, 0, 10, 10]}
        chain = {"links": [{**link, "quotedText": "化学成分 合格 合格 C 0.12"}]}
        fact = {"name": "C", "value": "0.12", "source": {"file": "files/01.pdf", "page": 2, "excerpt": "化学成分 | 合格（跨2列） | C 0.12"}}
        self.assertEqual(na.matching_evidence_links(fact, "V-1", chain), [])  # 横跨格在 skill 里写一次，服务器重复写：不硬配
        chain = {"links": [{**link, "quotedText": "化学成分 合格 C 0.12"}]}
        self.assertEqual(na.matching_evidence_links(fact, "V-1", chain), ["EL-1"])
        seal = {"name": "印章", "value": "某某局", "source": {"file": "files/01.pdf", "page": 2, "excerpt": "[印章：某某市市场监督管理局]"}}
        chain = {"links": [{**link, "quotedText": "某某市市场监督管理局"}]}
        self.assertEqual(na.matching_evidence_links(seal, "V-1", chain), ["EL-1"])
        holder = {"name": "身份证号", "value": masked, "source": {"file": "files/01.pdf", "page": 2, "excerpt": f"身份证号 {masked}"}}
        chain = {"links": [{**link, "fieldName": "身份证号", "quotedText": f"身份证号：{full}"}]}
        self.assertEqual(na.matching_evidence_links(holder, "V-1", chain), ["EL-1"])  # 服务器引文里是完整号码，按脱敏后比

    # ------------------------------------------------------------ 低危修复（2026-10-28）

    def test_table_text_survives_html_with_missing_end_tags_and_overlong_rowspans(self):
        self.assertEqual(na.table_text('<table><tr><td rowspan="5">A</td><td>1</td></tr><tr><td>2</td></tr></table>').splitlines(),
                         ["A | 1", "A | 2"])  # rowspan 写多了不凭空多出几行
        self.assertEqual(na.table_text("<table><tr><td>a<td>b<tr><td>c<td>d</table>").splitlines(), ["a | b", "c | d"])
        self.assertEqual(na.table_text("<table><tr><td>x</td><td>y</td></tr><tr><td>last</td><td>row").splitlines(),
                         ["x | y", "last | row"])  # 末行没有 </tr> 也不丢

    def test_a_page_list_that_is_not_numbers_is_reported_as_json(self):
        bundle = self.local_bundle()
        code, out = run("text", "--file", str(bundle / "files/01-证书.pdf"), "--pages", "abc")
        self.assertEqual(code, 1)
        self.assertIn(out["error"]["code"], {"invalidArguments", "noTextLayer"})  # 坏 PDF 先报没文字；不再抛堆栈
        with self.assertRaises(na.ClientError) as caught:
            na.parse_pages("4-x", 10)
        self.assertEqual(caught.exception.code, "invalidArguments")

    def test_report_finds_an_id_number_right_after_a_newline_in_audit_json(self):
        bundle = self.local_bundle()
        checks = [{"atomicCheckId": f"AC-R24-0{i}", "verdict": "evidence_insufficient", "reason": "缺记录"} for i in range(1, 6)]
        checks[0]["reason"] = "焊工名单写着：\n110101199001011237"  # 存成 JSON 是 "\\n110101…"，号码前一个字符是字母 n
        self.write_report(bundle, checks)
        self.assertIn("audit.json 里有完整的 18 位身份证号", self.report_errors(bundle))

    def test_digest_lists_a_bounded_number_of_server_fields_and_spells_out_conditional_clauses(self):
        self.login()
        fields = [{"documentVersionId": "V-1", "fieldName": f"字段{i}", "fieldValue": str(i), "pageNo": 1} for i in range(200)]
        self.server.workspace = {**WORKSPACE, "content": {**WORKSPACE["content"], "ocr": {"extractedFields": fields}}}
        out_dir = Path(self.tmp.name) / "digest-cap"
        self.assertEqual(run("fetch", "--project", "P-T", "--node", "24", "--out", str(out_dir))[0], 0)
        digest = (out_dir / "digest.md").read_text(encoding="utf-8")
        self.assertIn(f"| 字段{na.DIGEST_FIELD_ROWS - 1} |", digest)
        self.assertNotIn(f"| 字段{na.DIGEST_FIELD_ROWS} |", digest)
        self.assertIn("共 200 条", digest)
        clause = {"standardRef": "STD-X", "clauseNo": "D2.4.1(8)", "sourcePage": 28, "verificationStatus": "source_verified",
                  "applicability": "foreign_grade_material_used"}
        self.assertIn("适用：foreign_grade_material_used", na.clause_line(clause))
        self.assertNotIn("适用", na.clause_line({**clause, "applicability": "always"}))

    def test_connection_logout_and_the_read_only_lookups_reach_the_server(self):
        code, out = run("connection")
        self.assertEqual(code, 0, out)
        self.assertEqual((out["data"]["tokenPresent"], out["data"]["ready"]), (False, {"ready": True}))
        self.assertNotIn("user", out["data"])
        # 没登录：要令牌的查询直接说要登录，不发请求
        self.assertEqual(run("cnse-org-search", "--keyword", "某某阀门")[1]["error"]["code"], "loginRequired")
        self.login()
        code, out = run("connection")
        self.assertEqual(out["data"]["user"], {"username": "zhang", "role": "inspection", "displayName": "张"})  # 不回显别的字段
        code, out = run("cnse-org-search", "--keyword", "某某阀门")
        self.assertEqual((code, out["data"]["items"][0]["licenseNo"]), (0, "TS1234567-2030"), out)
        code, out = run("node-standards", "--project", "P-T", "--node", "24")
        self.assertEqual((code, out["data"][0]["clauseNo"]), (0, "D2.6.1"), out)
        code, out = run("standard-content", "--file-id", "KF-1", "--page-no", "3", "--section", "D2.6.1")
        self.assertEqual((code, out["data"]["fileId"]), (0, "KF-1"), out)
        self.assertIn(("/api/inspection-services/standards/KF-1/canonical", {"pageNo": ["3"], "section": ["D2.6.1"]}), self.server.calls)
        payload = {"certificates": [{"certificateNo": "1101**********1237", "holder": "张三", "validUntil": "2027-03-01"}],
                   "periodStart": "2026-01-01", "periodEnd": "2026-06-30"}
        code, out = run("cert-validity", "--json", json.dumps(payload, ensure_ascii=False))
        self.assertEqual((code, out["data"]["conclusion"]), (0, "valid"), out)
        self.assertIn(("/api/inspection-services/certificate-validity", payload), self.server.calls)
        code, out = run("logout")
        self.assertEqual((code, out["data"]), (0, {"loggedOut": True}))
        self.assertFalse(self.session.exists())
        self.assertEqual(self.server.calls[-1][0], "/api/auth/logout")  # 服务器那边的令牌也作废


    # ---- 2026-10-28 评测暴露的 OCR 路径问题：失败任务、时长、读得不全、文字层靠不住

    def stale_failed_job(self, bundle: Path, png: str, created: str) -> None:
        """服务器上已经有一个用第一个键建的、失败了的任务（上次留下的，或别的资料包传过同一份原件）。"""
        sha = next(f["sha256"] for f in json.loads((bundle / "bundle.json").read_text(encoding="utf-8"))["files"] if f["path"] == png)
        self.server.ocr_jobs[f"aicheck-node-audit-{sha[:48]}"] = "OCRJ-OLD"
        self.server.ocr_job_status["OCRJ-OLD"] = {"status": "failed", "createdAt": created,
                                                  "diagnostics": [{"code": "HTTP_401", "level": "error", "retryable": False}]}

    def test_ocr_retries_a_failed_job_left_from_before_in_the_same_run(self):
        bundle, png = self.scan_bundle("stale")
        self.login()
        self.server.ocr_result = self.certificate_result()
        self.stale_failed_job(bundle, png, "2026-01-01 08:00:00")  # 北京时间，远早于本次命令
        with patch.object(na, "OCR_POLL_SECONDS", 0):
            code, out = run("ocr", "--bundle", str(bundle), "--allow-egress")
        self.assertEqual(code, 0, out)
        # 同一个键拿回的是那个老的失败任务：当场换键重传，这一次命令里就出结果，不用再跑一遍
        self.assertEqual(([d["file"] for d in out["data"]["done"]], out["data"]["failed"], out["data"]["retried"]), ([png], [], [png]))
        self.assertEqual([key.endswith("-r1") for key in self.upload_keys()], [False, True])

    def test_ocr_says_a_server_side_mineru_token_failure_is_not_the_users_login(self):
        bundle, png = self.scan_bundle("engine")
        self.login()
        fresh = na.datetime.now(na.OCR_SERVER_TZ).strftime("%Y-%m-%d %H:%M:%S")
        self.server.ocr_final = {"status": "failed", "createdAt": fresh, "diagnostics": [{"code": "HTTP_401", "level": "error"}]}
        with patch.object(na, "OCR_POLL_SECONDS", 0):
            code, out = run("ocr", "--bundle", str(bundle), "--allow-egress")
        self.assertEqual(code, 0, out)
        [failed] = out["data"]["failed"]
        self.assertEqual((failed["file"], failed["kind"]), (png, "engineAuth"))
        self.assertIn("不是你的登录令牌", failed["reason"])
        self.assertEqual(len(self.server.ocr_uploads), 1)  # 这次刚建的任务就被拒：当场重传也一样，不浪费
        self.assertNotIn("retried", out["data"])
        self.assertIn("管理员", out["data"]["nextStep"])
        self.assertNotIn("login --web", out["data"]["nextStep"])

    def test_ocr_leaves_a_stale_failed_job_for_next_time_instead_of_blaming_the_mineru_token(self):
        # c 轮评测：上次留下的 401 任务轮询到时预算已用完，被报成“服务器 MinerU 令牌坏了、重跑没用”，其实重跑就好
        bundle, png = self.scan_bundle("stale-late")
        self.login()
        self.server.ocr_result = self.certificate_result()
        self.stale_failed_job(bundle, png, "2026-01-01 08:00:00")
        with patch.object(na, "OCR_POLL_SECONDS", 0), patch.object(na, "OCR_BUDGET_CAP", 0):
            code, out = run("ocr", "--bundle", str(bundle), "--allow-egress")
        self.assertEqual(code, 0, out)
        self.assertEqual((out["data"]["failed"], out["data"]["notSubmitted"]), ([], [png]))
        self.assertNotIn("管理员", out["data"]["nextStep"])
        sha = next(f["sha256"] for f in json.loads((bundle / "bundle.json").read_text(encoding="utf-8"))["files"] if f["path"] == png)
        self.assertEqual(json.loads((bundle / "ocr" / "attempts.json").read_text(encoding="utf-8")), {sha: 1})
        with patch.object(na, "OCR_POLL_SECONDS", 0):
            code, out = run("ocr", "--bundle", str(bundle))
        self.assertEqual(([d["file"] for d in out["data"]["done"]], out["data"]["failed"]), ([png], []))
        self.assertEqual([key.endswith("-r1") for key in self.upload_keys()], [False, True])  # 下次直接换新键

    def test_ocr_lists_a_resubmitted_file_once_and_reports_progress(self):
        bundle, png = self.scan_bundle("resubmit")
        self.login()
        self.server.ocr_result = self.certificate_result()
        self.server.ocr_running_polls = 10 ** 6  # 换键后的新任务一直在识别
        self.stale_failed_job(bundle, png, "2026-01-01 08:00:00")
        with patch.object(na, "OCR_POLL_SECONDS", 0), patch.object(na, "OCR_MIN_REQUEST", 0):
            code, out = run("ocr", "--bundle", str(bundle), "--allow-egress", "--timeout", "1")
        self.assertEqual(code, 0, out)
        self.assertEqual(out["data"]["retried"], [png])
        self.assertEqual([(p["file"], p.get("retried")) for p in out["data"]["pending"]], [(png, True)])
        self.assertEqual(out["data"]["progress"], "0/1 份已有 OCR 文字")

    def test_ocr_request_timeouts_stay_inside_the_budget(self):
        # c 轮评测：--timeout 480 的一条跑了 10.2 分钟，被 Bash 的 10 分钟上限转后台
        root = Path(self.tmp.name) / "deadline-project"
        root.mkdir()
        for name in ("a-焊工证.png", "b-焊工证.png"):
            (root / name).write_bytes(b"\x89PNG fake scan " + name.encode())
        bundle = Path(run("local-init", "--node", "24", "--project-dir", str(root), "--out", str(Path(self.tmp.name) / "deadline"))[1]["data"]["bundle"])
        self.login()
        self.server.ocr_result = self.certificate_result()
        uploads, calls = [], []
        upload, call = na.Api.upload, na.Api.call

        def spy_upload(api, path, content, *, headers, timeout=300):
            uploads.append(timeout)
            return upload(api, path, content, headers=headers, timeout=timeout)

        def spy_call(api, method, path, **kwargs):
            if "/internal/ocr/" in path:
                calls.append(kwargs.get("timeout"))
            return call(api, method, path, **kwargs)

        with patch.object(na, "OCR_POLL_SECONDS", 0), patch.object(na.Api, "upload", spy_upload), patch.object(na.Api, "call", spy_call):
            code, out = run("ocr", "--bundle", str(bundle), "--allow-egress", "--timeout", "30")
        self.assertEqual((code, len(out["data"]["done"])), (0, 2), out)
        self.assertEqual(uploads[0], na.OCR_FIRST_REQUEST)  # 保证进展的第一份
        self.assertTrue(all(t <= 30 for t in uploads[1:]), uploads)  # 之后的都不超过剩余时间
        self.assertTrue(calls and all(t <= na.OCR_FIRST_REQUEST for t in calls), calls)

    def test_large_photos_are_downscaled_before_upload(self):
        # 2026-10-29 生产：5712×3213 的手机照片 MinerU 全部失败，4032×2268 的都成功
        fitz = na.quiet_fitz()
        root = Path(self.tmp.name) / "photos"
        root.mkdir()
        big, small = root / "big.png", root / "small.png"
        fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 60, 20), False).save(str(big))
        fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 30, 10), False).save(str(small))
        with patch.object(na, "OCR_MAX_IMAGE_SIDE", 40):
            name, data = na.upload_payload(big, "a" * 64)
            shrunk = fitz.Pixmap(data)
            self.assertEqual((name, shrunk.width, shrunk.height), ("a" * 16 + ".jpg", 40, 13))
            self.assertEqual(na.upload_payload(small, "b" * 64), ("b" * 16 + ".png", small.read_bytes()))  # 不大的照原样传
        fake = root / "fake.png"
        fake.write_bytes(b"\x89PNG not really")
        self.assertEqual(na.upload_payload(fake, "c" * 64), ("c" * 16 + ".png", b"\x89PNG not really"))  # 读不出尺寸：照原样交服务器判断

    def test_downscaled_photos_get_their_own_idempotency_key(self):
        # 2026-10-29 评测：键按原件哈希算、内容却是缩小后的，原尺寸传过的照片再传被拒 40905，整条 ocr 中止
        fitz = na.quiet_fitz()
        root = Path(self.tmp.name) / "key-project"
        root.mkdir()
        fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 60, 20), False).save(str(root / "a-焊工证.png"))
        fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 30, 10), False).save(str(root / "b-焊工证.png"))
        bundle = Path(run("local-init", "--node", "24", "--project-dir", str(root), "--out", str(Path(self.tmp.name) / "key"))[1]["data"]["bundle"])
        self.login()
        self.server.ocr_result = self.certificate_result()
        sent = {}
        upload = na.Api.upload

        def spy_upload(api, path, content, *, headers, timeout=300):
            sent[headers["Idempotency-Key"]] = content
            return upload(api, path, content, headers=headers, timeout=timeout)

        with patch.object(na, "OCR_MAX_IMAGE_SIDE", 40), patch.object(na, "OCR_POLL_SECONDS", 0), patch.object(na.Api, "upload", spy_upload):
            code, out = run("ocr", "--bundle", str(bundle), "--allow-egress")
        self.assertEqual((code, len(out["data"]["done"])), (0, 2), out)
        originals = {hashlib.sha256(p.read_bytes()).hexdigest() for p in root.iterdir()}
        self.assertEqual({key: hashlib.sha256(content).hexdigest()[:48] in key for key, content in sent.items()}, {key: True for key in sent})
        self.assertEqual(sum(any(sha[:48] in key for sha in originals) for key in sent), 1)  # 只有原样传的那份沿用原件哈希

    def test_ocr_counts_blank_pages_only_where_the_file_needs_ocr(self):
        fitz = na.quiet_fitz()
        root = Path(self.tmp.name) / "blank-project"
        root.mkdir()
        doc = fitz.open()
        doc.new_page().insert_text((40, 60), "\n".join(f"Pipe line {i} material 20# GB/T 8163 DN50" for i in range(6)))
        doc.new_page()  # 扫描页：没有文字层
        doc.save(root / "07-施工记录.pdf")
        doc.close()
        (root / "09-焊工证.png").write_bytes(b"\x89PNG fake scan")
        bundle = Path(run("local-init", "--node", "24", "--project-dir", str(root), "--out", str(Path(self.tmp.name) / "blank"))[1]["data"]["bundle"])
        self.login()
        self.server.ocr_result = {"resultAvailable": True, "pageCount": 2, "processing": {"provider": "mineru"}, "fragments": []}
        with patch.object(na, "OCR_POLL_SECONDS", 0):
            code, out = run("ocr", "--bundle", str(bundle), "--allow-egress")
        self.assertEqual(code, 0, out)
        done = {d["file"].split("-", 1)[1]: d for d in out["data"]["done"]}  # local-init 在文件名前加了序号
        self.assertEqual(done["07-施工记录.pdf"]["blankPages"], "2")  # 有文字层的第 1 页 OCR 空着不要紧
        # 整份没有文字层、OCR 也一个字没读出：明说重跑没用，reviewedFiles 怎么写
        step = next(s for s in out["data"]["nextStep"].split("；") if "整份 OCR 都没读出字" in s)
        self.assertIn("09-焊工证.png", step)
        self.assertNotIn("07-施工记录.pdf", step)
        self.assertIn("skipped", out["data"]["nextStep"])
        # 报告里把这份标 ocr：说清楚是 OCR 读不出字，该标 skipped
        files = json.loads((bundle / "bundle.json").read_text(encoding="utf-8"))["files"]
        run("search", "--bundle", str(bundle))
        self.write_report(bundle, [{"atomicCheckId": f"AC-R24-0{i}", "verdict": "evidence_insufficient", "reason": "缺记录"} for i in range(1, 6)],
                          [{"file": f["path"], "method": "ocr"} for f in files])
        png = next(f["path"] for f in files if f["path"].endswith(".png"))
        self.assertIn(f"reviewedFiles {png}: 服务器 OCR 一个字也没读出", self.report_errors(bundle))

    def test_ocr_flags_a_long_line_repeated_on_a_page_and_drops_model_replies(self):
        # c 轮评测：贵州强度计算书同一行 405 字重复 10 次没被标；二维码处混进识别模型的英文说明
        bundle, png = self.scan_bundle("lines")
        self.login()
        line = "压力管道GC2 ø108×4 强度计算：广东省建设工程勘察设计院计算书第一部分内容说明与计算结果"
        reply = ("The image provided is a QR code. It does not contain any text, mathematical formulas, tables, "
                 "or figures that can be processed according to the OCR instructions.")
        self.server.ocr_result = {"resultAvailable": True, "pageCount": 1, "processing": {"provider": "mineru"},
                                  "fragments": [*({"pageNo": 1, "readingOrder": i, "text": line} for i in range(6)),
                                                {"pageNo": 1, "readingOrder": 9, "text": reply}]}
        with patch.object(na, "OCR_POLL_SECONDS", 0):
            code, out = run("ocr", "--bundle", str(bundle), "--allow-egress")
        self.assertEqual(code, 0, out)
        self.assertIn("识别跑飞", out["data"]["qualityWarnings"][png])
        saved = Path(out["data"]["done"][0]["saved"]).read_text(encoding="utf-8")
        self.assertNotIn("The image provided", saved)
        self.assertIn(na.MODEL_REPLY_MARK, saved)
        # 正文里以 The image 开头的英文不是模型说明，不动
        self.assertEqual(na.strip_model_replies("The image quality indicator shall be placed on the source side."),
                         "The image quality indicator shall be placed on the source side.")

    def test_standard_table_pages_read_from_ocr_but_project_files_keep_their_text_layer(self):
        # c 轮评测：NB/T 47014-2023 第 41 页表 6 文字层缺了最大值一列，text 给的却是文字层
        fitz = na.quiet_fitz()
        repo = Path(self.tmp.name) / "repo"
        (repo / "rules" / "standards").mkdir(parents=True)
        bundle, _ = self.scan_bundle("std-table")
        layer = "\n".join(f"Table 6 row {i}: welding position range thickness" for i in range(6))
        paths = {"standard:rules/standards/表.pdf": repo / "rules" / "standards" / "表.pdf", "files/99-表.pdf": bundle / "files" / "99-表.pdf"}
        table = "参数 | 最小值 | 最大值\n厚度 | 1.5 | 8\n直径 | 25 | 不限"
        with patch.object(na, "repo_root", return_value=repo):
            for relative, path in paths.items():
                doc = fitz.open()
                doc.new_page().insert_text((40, 60), layer)
                doc.save(path)
                doc.close()
                na.write_private(na.ocr_record_path(bundle, relative), na.dump(
                    {"file": relative, "sha256": na.cached_sha(path), "renderVersion": na.OCR_RENDER_VERSION,
                     "pages": [{"page": 1, "text": table}]}))
            _, _, merged, used = na.page_texts(bundle, "standard:rules/standards/表.pdf", paths["standard:rules/standards/表.pdf"])
            self.assertEqual((used, merged[0]), ({1}, table))
            _, _, merged, used = na.page_texts(bundle, "files/99-表.pdf", paths["files/99-表.pdf"])
            self.assertEqual(used, set())  # 工程资料的数字文字层比 OCR 准

    def test_ocr_only_seals_on_text_layer_drawing_pages_are_appended_once(self):
        # 10-29 服务器节点评测：储罐施工图有文字层，设计许可章、签字栏人名是图片，只在 OCR 里，text、search 读不到
        root = Path(self.tmp.name) / "seal-project"
        root.mkdir()
        sentence = "管道安装完毕后应进行压力试验，水压试验压力为设计压力的一点五倍。"
        with na.quiet_fitz().open() as doc:
            for n in range(1, 7):
                doc.new_page().insert_text((40, 60), "\n".join([f"管道布置图 第{n}张 图号 S10{n}", sentence if n == 3 else "设计说明见首页"] * 3),
                                           fontname="china-s")
            doc.save(root / "施工图.pdf")
        bundle = Path(run("local-init", "--node", "4", "--project-dir", str(root), "--out", str(Path(self.tmp.name) / "seal"))[1]["data"]["bundle"])
        [relative] = [f["path"] for f in json.loads((bundle / "bundle.json").read_text(encoding="utf-8"))["files"]]
        source = bundle / relative
        seal = "压力管道设计 | 主要负责人:张三（跨3列） | TS1234567-2028有效期至:2028年1月17日"
        ocr_pages = [{"page": n, "text": f"管道布置图 | 第{n}张 | 图号 S10{n}\n{seal}\n版次REV. | 审核REVD.\n李四 | III级\nIII级"} for n in range(1, 7)]
        ocr_pages[1]["text"] += "\n" + sentence  # 服务器把第 3 页的字记到了第 2 页
        ocr_pages[2]["text"] = ""
        na.write_private(na.ocr_record_path(bundle, relative), json.dumps(
            {"file": relative, "sha256": na.cached_sha(source), "renderVersion": na.OCR_RENDER_VERSION, "pages": ocr_pages}, ensure_ascii=False))
        status, layer, merged, used = na.page_texts(bundle, relative, source)
        self.assertEqual((status, used), ("text", set()))
        self.assertEqual(merged[2], layer[2])  # 这页没有 OCR 文字
        tails = [m[len(l.strip()):] for m, l in zip(merged, layer)]
        self.assertEqual(tails[0], f"\n\n{na.OCR_SUPPLEMENT_MARK}\n压力管道设计 | 主要负责人:张三 | TS1234567-2028有效期至:2028年1月17日\n"
                                   "版次REV. | 审核REVD.\n李四 | III级")
        for tail in tails[1:2] + tails[3:]:
            self.assertIn("压力管道设计 | 主要负责人:张三 | TS1234567-2028有效期至:2028年1月17日", tail)  # 章每页照给
            self.assertIn("李四", tail)  # 签字栏人名每页照给
            self.assertNotIn("版次REV.", tail)  # 每页都有的双语栏名只给第一页
            self.assertNotIn("第", tail)  # 文字层有的格不补
        self.assertNotIn("压力试验", tails[1])  # 错记到第 2 页、其实在第 3 页文字层里的字不补
        code, out = run("text", "--file", relative, "--bundle", str(bundle), "--pages", "1-2")
        self.assertEqual(code, 0, out)
        self.assertEqual((out["data"]["ocrSupplementPages"], "ocrPages" in out["data"]), ("1-2", False))
        self.assertIn("--- 第 1 页（文字层＋OCR 补充） ---", Path(out["data"]["saved"]).read_text(encoding="utf-8"))
        code, out = run("search", "--bundle", str(bundle), "--only", "--terms", "张三")
        self.assertEqual(code, 0, out)
        hits = json.loads(Path(out["data"]["saved"]).read_text(encoding="utf-8"))["files"][0]["hits"]
        self.assertEqual(sorted({h["page"] for h in hits}), [1, 2, 4, 5, 6])
        self.assertIsNone(na.excerpt_problem(bundle, {"file": relative, "page": 1, "excerpt": "主要负责人:张三"}, {relative}, {}))

    def test_a_docx_with_embedded_pictures_goes_to_ocr_and_reads_both_parts(self):
        # c 轮评测：储罐焊工清单 docx 文末嵌着焊工证照片，没被标成要 OCR
        import zipfile
        root = Path(self.tmp.name) / "docx-project"
        root.mkdir()
        with zipfile.ZipFile(root / "焊工清单.docx", "w") as docx:
            docx.writestr("word/document.xml", "<w:document><w:body><w:p><w:r><w:t>焊工清单：张三 GTAW 管道焊接，证件照片附后。</w:t></w:r></w:p>"
                                               "</w:body></w:document>")
            docx.writestr("word/media/image1.png", b"\x89PNG fake photo")
        bundle = Path(run("local-init", "--node", "24", "--project-dir", str(root), "--out", str(Path(self.tmp.name) / "docx"))[1]["data"]["bundle"])
        docx_path = json.loads((bundle / "bundle.json").read_text(encoding="utf-8"))["files"][0]["path"]
        code, out = run("search", "--bundle", str(bundle))
        self.assertIn(docx_path, out["data"]["embeddedImages"])
        code, out = run("text", "--file", str(bundle / docx_path))
        self.assertIn("嵌了 1 张图片", out["data"]["embeddedImages"])
        self.login()
        self.server.ocr_result = {"resultAvailable": True, "pageCount": 1, "processing": {"provider": "mineru"},
                                  "fragments": [{"pageNo": 1, "readingOrder": 1, "text": "特种设备作业人员证 张三"}]}
        with patch.object(na, "OCR_POLL_SECONDS", 0):
            code, out = run("ocr", "--bundle", str(bundle), "--allow-egress")
        self.assertEqual(([d["file"] for d in out["data"]["done"]], code), ([docx_path], 0), out)
        code, out = run("text", "--file", str(bundle / docx_path))
        body = Path(out["data"]["saved"]).read_text(encoding="utf-8")
        self.assertIn("焊工清单：张三 GTAW 管道焊接", body)
        self.assertIn("特种设备作业人员证 张三", body)
        self.assertNotIn("embeddedImages", out["data"])

    def test_ocr_timeout_covers_the_whole_command_and_resumes_where_it_stopped(self):
        root = Path(self.tmp.name) / "budget-project"
        root.mkdir()
        for name in ("a-焊工证.png", "b-焊工证.png"):
            (root / name).write_bytes(b"\x89PNG fake scan " + name.encode())
        bundle = Path(run("local-init", "--node", "24", "--project-dir", str(root), "--out", str(Path(self.tmp.name) / "budget"))[1]["data"]["bundle"])
        files = [f["path"] for f in json.loads((bundle / "bundle.json").read_text(encoding="utf-8"))["files"]]
        self.assertEqual(len(files), 2)
        self.login()
        self.server.ocr_result = self.certificate_result()
        self.server.ocr_running_polls = 99
        with patch.object(na, "OCR_POLL_SECONDS", 0), patch.object(na, "OCR_BUDGET_CAP", 0):
            # 上限压到 0：--timeout 给多大都按上限算，只传一份、查一份就收手
            code, out = run("ocr", "--bundle", str(bundle), "--allow-egress", "--timeout", "9999")
            self.assertEqual(code, 0, out)
            self.assertEqual((len(self.server.ocr_uploads), out["data"]["notSubmitted"]), (1, [files[1]]))
            self.assertIn("到点", out["data"]["nextStep"])
            code, out = run("ocr", "--bundle", str(bundle), "--timeout", "0")
            self.assertEqual(code, 0, out)
            # 第二次：先把上次没传的那份传上去；状态只查了一份，没查到的排在前面，下次先查
            self.assertEqual(len(self.server.ocr_uploads), 2)
            self.assertNotIn("notSubmitted", out["data"])
            self.assertEqual([(p["file"], p["state"]) for p in out["data"]["pending"]], [(files[1], "submitted"), (files[0], "running")])
            self.assertIn("没来得及查", out["data"]["nextStep"])
        self.server.ocr_running_polls = 0
        with patch.object(na, "OCR_POLL_SECONDS", 0):
            code, out = run("ocr", "--bundle", str(bundle))
        self.assertEqual((code, sorted(d["file"] for d in out["data"]["done"])), (0, sorted(files)))
        self.assertEqual(len(self.server.ocr_uploads), 2)  # 全程没有重传
        self.assertFalse((bundle / "ocr" / "pending.json").exists())

    def test_ocr_flags_pages_it_read_poorly_and_text_and_search_say_so(self):
        bundle, png = self.scan_bundle("quality")
        self.login()
        # MinerU 识别跑飞：同一句话反复出现、后面一长串“零”（评测里的配管平面图）
        self.server.ocr_result = {"resultAvailable": True, "pageCount": 1, "processing": {"provider": "mineru"},
                                  "fragments": [{"pageNo": 1, "readingOrder": 1, "text": "某某区人民法院" * 3 + "零" * 60}]}
        with patch.object(na, "OCR_POLL_SECONDS", 0):
            code, out = run("ocr", "--bundle", str(bundle), "--allow-egress")
        self.assertEqual(code, 0, out)
        self.assertIn("识别跑飞", out["data"]["qualityWarnings"][png])
        self.assertIn("不能写“原件没有”", out["data"]["nextStep"])
        saved = Path(out["data"]["done"][0]["saved"]).read_text(encoding="utf-8")
        self.assertIn("--- 第 1 页（OCR 读得不全：识别跑飞", saved)
        self.assertIn("czxm", saved)  # 焊工证代号字母会认错：以登记为准
        code, out = run("ocr", "--bundle", str(bundle))  # 已识别过（cached）也照样提醒
        self.assertEqual((code, out["data"]["cached"]), (0, [png]))
        self.assertIn(png, out["data"]["qualityWarnings"])
        code, out = run("text", "--file", png, "--bundle", str(bundle))
        self.assertIn("不能写“原件没有”", out["data"]["ocrQuality"])
        self.assertIn("CTAF", out["data"]["ocrNote"])
        code, out = run("search", "--bundle", str(bundle), "--terms", "异种钢接头", "--only")
        self.assertIn("读得不全", out["data"]["zeroHitNote"])
        self.assertIn(png, out["data"]["ocrQuality"])

    @unittest.skipUnless(importlib.util.find_spec("fitz"), "PyMuPDF 未安装")
    def test_a_large_drawing_page_is_flagged_even_when_ocr_reads_its_title_block(self):
        import fitz
        root = Path(self.tmp.name) / "drawing-project"
        root.mkdir()
        with fitz.open() as doc:
            page = doc.new_page(width=1684, height=1191)  # A2 横放的施工图扫描件
            page.insert_image(page.rect, stream=PNG)
            doc.new_page().insert_image(fitz.Rect(0, 0, 595, 842), stream=PNG)  # A4 的扫描页不算图纸
            # CAD 出的矢量图：没有图片，标注转成了线条，文字层只剩图框编号（评测里储罐施工图第 23–30 页）
            doc.new_page(width=1684, height=1191).insert_text((72, 72), "123BA123456DC45B6A CLASSA grid")
            doc.save(root / "施工图.pdf")
        bundle = Path(run("local-init", "--node", "24", "--project-dir", str(root), "--out", str(Path(self.tmp.name) / "drawing"))[1]["data"]["bundle"])
        [pdf] = [f["path"] for f in json.loads((bundle / "bundle.json").read_text(encoding="utf-8"))["files"]]
        layer = na.file_text(bundle / pdf)[1]
        self.assertEqual((na.scan_pages(bundle / pdf, layer), na.ocr_reason(bundle / pdf)), ({1, 2, 3}, "扫描件"))
        self.login()
        title = "广东某某设计院 工程名称 储罐区工艺管道 图号 GS-01 比例 1:100 设计 校对 审核 日期 2026.04 材料表见第 2 页"
        self.server.ocr_result = {"resultAvailable": True, "pageCount": 3, "fragments": [
            {"pageNo": 1, "readingOrder": 1, "text": title}, {"pageNo": 2, "readingOrder": 1, "text": title}]}
        with patch.object(na, "OCR_POLL_SECONDS", 0):
            code, out = run("ocr", "--bundle", str(bundle), "--allow-egress")
        self.assertEqual(code, 0, out)
        self.assertEqual(out["data"]["qualityWarnings"][pdf],
                         "第 1 页是大幅面图纸（图签、表格读得出，图上分散的标注常读不全）；第 3 页没读出字")

    @unittest.skipUnless(importlib.util.find_spec("fitz"), "PyMuPDF 未安装")
    def test_an_unreliable_text_layer_gives_way_to_server_ocr(self):
        import fitz
        root = Path(self.tmp.name) / "layer-project"
        root.mkdir()
        rare = "\n".join(["罾邳氍瞀劓泺罾邳氍瞀"] * 8)  # 80 个罕用字：扫描件自带的识别文字认错了
        matrix = "\n".join(["○", "—"] * 60)  # 120 行一格一行：符号矩阵被文字层拆散
        hidden = "\n".join(["钢管外径允许偏差为正负百分之一，壁厚允许偏差为正负百分之十二点五。"] * 8)
        with fitz.open() as doc:
            doc.new_page().insert_text((72, 72), rare, fontname="china-s")
            doc.new_page().insert_text((72, 30), matrix, fontname="china-s", fontsize=5)
            page = doc.new_page()
            page.insert_image(page.rect, stream=PNG)
            page.insert_text((40, 72), hidden, fontname="china-s", render_mode=3)  # 隐形文字层
            doc.new_page().insert_text((72, 72), "\n".join(["Plain text page with enough words to read."] * 8))
            doc.save(root / "标准表格.pdf")
        bundle = Path(run("local-init", "--node", "24", "--project-dir", str(root), "--out", str(Path(self.tmp.name) / "layer"))[1]["data"]["bundle"])
        [relative] = [f["path"] for f in json.loads((bundle / "bundle.json").read_text(encoding="utf-8"))["files"]]
        source = bundle / relative
        layer = na.file_text(source)[1]
        self.assertEqual(na.layer_problems(source, layer), {1: "garbled", 2: "table", 3: "embedded"})
        self.assertEqual(na.scan_pages(source, layer), {1})  # 认错的识别文字按扫描页算：要 OCR，报告引用要有 OCR 文字
        self.assertEqual(na.ocr_reason(source), "第 1 页是扫描页")
        code, out = run("text", "--file", relative, "--bundle", str(bundle))  # 还没 OCR：照给文字层，但说清哪几页靠不住
        self.assertEqual(code, 0, out)
        warning = out["data"]["layerWarnings"]
        for part in ("第 1 页文字层是认错了的识别文字", "第 2 页表格被文字层拆成一格一行", "第 3 页是扫描件自带的识别文字", "先跑 ocr"):
            self.assertIn(part, warning)
        ocr_pages = [{"page": 1, "text": "表 5 钢管的力学性能"}, {"page": 2, "text": "焊接方法 | 重要因素\n气焊 | ○"},
                     {"page": 3, "text": "钢管外径允许偏差为±1%"}, {"page": 4, "text": ""}]
        na.write_private(na.ocr_record_path(bundle, relative), json.dumps(
            {"file": relative, "sha256": na.cached_sha(source), "renderVersion": na.OCR_RENDER_VERSION, "pages": ocr_pages}, ensure_ascii=False))
        status, _, merged, used = na.page_texts(bundle, relative, source)
        self.assertEqual((status, used), ("text", {1, 2, 3}))
        self.assertEqual(merged[:3], [p["text"] for p in ocr_pages[:3]])  # 只给 OCR，不和靠不住的文字层并排
        self.assertTrue(merged[3].startswith("Plain text page"))
        code, out = run("text", "--file", relative, "--bundle", str(bundle))
        self.assertEqual((out["data"]["ocrPages"], "layerWarnings" in out["data"]), ("1-3", False))
        # 摘录核对：照 OCR 抄的、之前照文字层抄的都算数；两份都没有的不算
        for excerpt, ok in (("钢管外径允许偏差为±1%", True), ("钢管外径允许偏差为正负百分之一", True), ("钢管外径允许偏差为±2%", False)):
            problem = na.excerpt_problem(bundle, {"file": relative, "page": 3, "excerpt": excerpt}, {relative}, {})
            self.assertEqual(problem is None, ok, (excerpt, problem))

    def test_italic_latin_letters_in_gb_standard_text_layers_are_restored(self):
        self.assertEqual("犠＝０．０２４９１犛（犇－犛）".translate(na.ITALIC_LATIN), "W＝０．０２４９１S（D－S）")
        self.assertEqual("犌犅／犜８１６３".translate(na.ITALIC_LATIN), "GB／T８１６３")
        self.assertEqual("焊接工艺评定".translate(na.ITALIC_LATIN), "焊接工艺评定")
        self.assertEqual(na.match_text("外径犇≤159mm"), na.match_text("外径D≤159mm"))  # 旧摘录照抄了没还原的字也对得上
        if importlib.util.find_spec("fitz"):
            import fitz
            source = Path(self.tmp.name) / "斜体.pdf"
            with fitz.open() as doc:
                doc.new_page().insert_text((72, 72), "外径犇≤159mm", fontname="china-s")
                doc.save(source)
            self.assertIn("外径D≤159mm", na.file_text(source)[1][0])


if __name__ == "__main__":
    unittest.main()
