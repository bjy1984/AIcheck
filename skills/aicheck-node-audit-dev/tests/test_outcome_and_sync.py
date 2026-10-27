"""Node outcome, the user-facing audit.md, and syncing results to a fake AIcheck server (no real accounts or data)."""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit

SPEC = importlib.util.spec_from_file_location("node_audit_sync_test", Path(__file__).resolve().parents[2] / "aicheck-node-audit/scripts/node_audit.py")
na = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(na)

TOKEN = "test-token-not-real"
PDF = b"%PDF-1.4 fake\n"
ID = "11010519491231002X"  # 校验位正确的虚构号码
NODE = "/api/projects/P-S/inspection/nodes/24"
WORKSPACE = {"submission": {"documents": [
    {"id": "DOC-1", "fileName": "焊工证.pdf", "currentVersionId": "V-1", "bindings": [{"documentVersionId": "V-1"}]},
    {"id": "DOC-2", "fileName": "施工方案.pdf", "currentVersionId": "V-2", "bindings": [{"documentVersionId": "V-2"}]},
]}}
EVIDENCE_CHAIN = {"links": [
    {"id": "NEL-1", "documentVersionId": "V-1", "manualStatus": "confirmed", "pageNo": 2, "bbox": [10, 20, 180, 42], "quotedText": "2025-12"},
    {"id": "NEL-3", "documentVersionId": "V-1", "manualStatus": "confirmed", "pageNo": 1, "bbox": [10, 60, 180, 82],
     "quotedText": "GTAW-FeⅡ-6G-3/57"},
    {"id": "NEL-4", "documentVersionId": "V-1", "manualStatus": "confirmed", "pageNo": 3, "bbox": [10, 60, 180, 82],
     "quotedText": "别的字段"},  # 同文件别的页：不能借来挂
    {"id": "NEL-2", "documentVersionId": "V-2", "manualStatus": "pending", "pageNo": 3, "bbox": [10, 20, 180, 42],
     "quotedText": "2026-05 至 2026-06"},  # 未确认：服务器不收
]}


class FakeServer:
    def __init__(self):
        self.posts: list[tuple[str, dict, dict]] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def send_json(self, data=None, status=200, code=0, message=None):
                raw = json.dumps({"code": code, "data": data, "message": message}, ensure_ascii=False).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self):
                path = urlsplit(self.path).path
                if self.headers.get("Authorization") != f"Bearer {TOKEN}":
                    return self.send_json(None, 401, "UNAUTHORIZED")
                if path == f"{NODE}/audit-workspace":
                    return self.send_json(WORKSPACE)
                if path == f"{NODE}/evidence-chain":
                    return self.send_json(EVIDENCE_CHAIN)
                if path.endswith("/original"):
                    self.send_response(200)
                    self.end_headers()
                    return self.wfile.write(PDF)
                return self.send_json(None, 404, "NOT_FOUND")

            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length)) if length else None
                outer.posts.append((urlsplit(self.path).path, dict(self.headers), body))
                if urlsplit(self.path).path == "/api/review/findings":
                    return self.send_json({"finding": {"id": f"FND-{len(outer.posts)}", "status": "draft", "humanStatus": "pending_human_review"}})
                return self.send_json(None, 404, "NOT_FOUND")

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


def fact(name, value, file, page=1):
    return {"name": name, "value": value, "source": {"file": file, "page": page, "excerpt": value}}


def fill(bundle: Path) -> None:
    """A complete report: one failed, one human review, two evidence insufficient, traceability human review."""
    report = json.loads((bundle / "audit.json").read_text(encoding="utf-8"))
    cert, plan = "files/01-焊工证.pdf", "files/02-施工方案.pdf"
    verdicts = {
        "AC-R24-01": ("failed", {"facts": [fact("有效期至", "2025-12", cert, 2), fact("计划施工期", "2026-05 至 2026-06", plan, 3)],
                                 "reasoning": "证书有效期至 2025-12，早于计划施工期起始 2026-05。证书在施工期内已过期。",
                                 "nextSteps": ["更换证书有效的焊工"]}),
        "AC-R24-02": ("human_review_required", {"facts": [fact("母材", "S30408", plan, 5)], "reason": "图纸材质需设计澄清。",
                                                "conflicts": ["材料表写 20 钢，平面图写 S30408"]}),
        "AC-R24-03": ("evidence_insufficient", {"reason": "没有施焊记录，无法逐焊口核对位置。"}),
        "AC-R24-04": ("evidence_insufficient", {"facts": [fact("持证项目", "GTAW-FeⅡ-6G-3/57", cert, 1)], "reason": "缺施焊记录。"}),
        "AC-R24-05": ("human_review_required", {"reason": "AC-R24-02 列了冲突，按追溯项口径需人工确认。"}),
    }
    for check in report["checks"]:
        verdict, extra = verdicts[check["atomicCheckId"]]
        check.update(verdict=verdict, **extra)
    for entry in report["reviewedFiles"]:
        entry.update(method="read", pages="全部")
    report.update(summary="测试报告", auditor="test", auditedAt="2026-10-25T10:00:00+08:00", missingMaterials=["施焊记录"],
                  riskFlags=[{"level": "high", "check": "AC-R24-04", "flag": "不锈钢段超出证书范围"}])
    (bundle / "audit.json").write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")


class OutcomeTest(unittest.TestCase):
    def test_outcome_from_verdicts(self):
        o = lambda *vs: na.node_outcome([{"verdict": v} for v in vs])["label"]
        self.assertEqual(o("passed", "passed"), "通过")
        self.assertEqual(o("passed", "not_applicable"), "通过")
        self.assertEqual(o("passed", "failed", "evidence_insufficient"), "不通过")
        self.assertEqual(o("passed", "evidence_insufficient"), "暂不能判定通过")  # 缺证不是不通过
        self.assertEqual(o("passed", "human_review_required"), "暂不能判定通过")
        self.assertEqual(o("not_applicable"), "暂不能判定通过")  # 一项都没核实过不能说通过

    def test_full_id_numbers_never_reach_the_user_or_the_server(self):
        check = {"atomicCheckId": "AC-R24-01", "name": "证书", "verdict": "failed", "reasoning": f"证号 {ID} 已过期。",
                 "facts": [fact("证号", ID, "files/01-证.pdf", 2)], "nextSteps": [f"核对 {ID}"]}
        manifest = {"projectId": "P", "nodeId": 24, "ruleId": "R24", "source": "server", "fetchedAt": "t"}
        md = na.render_markdown(manifest, {"checks": [check]}, [])
        self.assertNotIn(ID, md)
        self.assertIn("1101", md)
        self.assertNotIn(ID, na.finding_description(check, na.node_outcome([check])))


class ReadableOutputTest(unittest.TestCase):
    def test_helpers_cut_at_clause_breaks_and_group_pages_by_file(self):
        long = "已交的证书签署齐全，且引用了编号，" + "但设计里还有别的管段没有评定，" * 12 + "。"
        cut = na.first_sentence(long, 40)
        self.assertTrue(cut.endswith("…") and len(cut) <= 40 and "，" not in cut[-3:-1])
        self.assertEqual(na.leading_sentences("第一句。第二句。" + "长" * 300 + "。", 30), "第一句。第二句。")
        self.assertTrue(na.leading_sentences("长" * 300 + "。", 30).endswith("…"))
        self.assertEqual(na.short_time("2026-10-26T18:40:00-07:00"), "2026-10-26 18:40")
        self.assertEqual(na.short_time(None), "—")
        check = {"facts": [fact("a", "1", "files/01-证书.pdf", 5), fact("b", "2", "files/01-证书.pdf", 1), fact("c", "3", "files/01-证书.pdf", 5),
                           fact("d", "4", "files/02-合同.pdf", 3), fact("e", "5", "files/03-图纸.pdf", 2)]}
        self.assertEqual(na.check_evidence(check), "证书.pdf 第1、5页；合同.pdf 第3页 等 4 处")
        self.assertEqual(na.check_evidence(check, limit=4), "证书.pdf 第1、5页；合同.pdf 第3页；图纸.pdf 第2页")

    def test_report_leads_with_the_things_to_do_and_keeps_long_reasons_in_the_detail(self):
        reason = "资料里缺这一项的原件，" + "需要施工方补充并说明来源，" * 30 + "。"
        checks = [
            {"atomicCheckId": "AC-R99-01", "name": "规则·甲", "verdict": "human_review_required", "reasoning": "事实齐了。需要监检人员确认。", "reason": "x",
             "facts": [fact("n", "v", "files/01-证书.pdf", 1)], "nextSteps": ["监检人员核对原件", "补齐 AC-R99-02 所列缺口后重新审计"]},
            {"atomicCheckId": "AC-R99-02", "name": "规则·乙", "verdict": "evidence_insufficient", "reason": reason,
             "nextSteps": ["请施工方补施焊记录", "监检人员核对原件"]},
            {"atomicCheckId": "AC-R99-03", "name": "规则·丙", "verdict": "failed", "reasoning": reason, "facts": [fact("n", "v", "files/01-证书.pdf", 2)],
             "nextSteps": ["整改后重新报审"]},
        ]
        manifest = {"projectId": "P", "nodeId": 99, "ruleId": "R99", "source": "local", "fetchedAt": "2026-10-26T18:07:27-07:00"}
        md = na.render_markdown(manifest, {"checks": checks, "auditedAt": "2026-10-26T18:40:00-07:00"}, [])
        self.assertIn("共 3 项检查：❌ 不符合 1　❓ 证据不足 1　👤 需人工确认 1", md)
        self.assertIn("取数 2026-10-26 18:07", md)
        todo = md.split("## 最需要先做的事")[1].split("\n## ")[0]
        order = [todo.index(s) for s in ("整改后重新报审", "请施工方补施焊记录", "监检人员核对原件", "补齐 AC-R99-02")]
        self.assertEqual(order, sorted(order))  # 先整改、再补资料、再人工确认，指向别项的建议排最后
        self.assertEqual(todo.count("监检人员核对原件"), 1)  # 相同的建议只出现一次
        shown = md.split("## 不通过的原因")[1].split("## 需要人工确认")[0]
        self.assertIn(reason.strip(), shown)  # 不符合的原因写全
        section = md.split("## 证据不足")[1].split("## 逐项明细")[0]
        self.assertNotIn(reason.strip(), section)  # 证据不足的长说明只留开头，全文在逐项明细
        self.assertIn("完整说明见下面“逐项明细”AC-R99-02", section)
        self.assertIn(reason.strip(), md.split("## 逐项明细")[1])


class PrioritySteps(unittest.TestCase):
    def test_checks_take_turns_so_one_check_cannot_fill_the_list(self):
        many = {"atomicCheckId": "AC-R99-01", "verdict": "evidence_insufficient", "nextSteps": [f"补资料{i}" for i in range(1, 8)]}
        other = {"atomicCheckId": "AC-R99-02", "verdict": "evidence_insufficient", "nextSteps": ["补另一份", "再补一份"]}
        failed = {"atomicCheckId": "AC-R99-03", "verdict": "failed", "nextSteps": ["先整改"]}
        steps, more = na.priority_steps([many, other, failed], cap=5)
        self.assertEqual([s.split("：", 1)[1] for s in steps], ["先整改", "补资料1", "补另一份", "补资料2", "再补一份"])
        self.assertEqual(more, 5)


class SyncTest(unittest.TestCase):
    def setUp(self):
        self.server = FakeServer()
        self.tmp = tempfile.TemporaryDirectory()
        home = Path(self.tmp.name)
        session = home / "session.json"
        na.write_private(session, json.dumps({"baseUrl": self.server.url, "token": TOKEN}))
        self.env = patch.dict(os.environ, {"AICHECK_AUDIT_HOME": str(home / "audits"), "AICHECK_SESSION_FILE": str(session),
                                           "AICHECK_BASE_URL": self.server.url})
        self.env.start()
        os.environ.pop("AICHECK_TOKEN", None)
        self.bundle = home / "b"
        code, out = run("fetch", "--project", "P-S", "--node", "24", "--out", str(self.bundle))
        self.assertEqual(code, 0, out)
        run("skeleton", "--bundle", str(self.bundle))
        fill(self.bundle)

    def tearDown(self):
        self.env.stop()
        self.server.close()
        self.tmp.cleanup()

    def test_report_is_user_facing(self):
        code, out = run("report", "--bundle", str(self.bundle))
        self.assertEqual(code, 0, out)
        self.assertEqual(out["data"]["outcome"], "不通过")
        self.assertTrue(out["data"]["syncAvailable"])
        md = (self.bundle / "audit.md").read_text(encoding="utf-8")
        self.assertIn("## 结论：不通过", md)
        for heading in ("## 不通过的原因", "## 需要人工确认", "## 证据不足", "## 需要补充的资料", "## 逐项明细"):
            self.assertIn(heading, md)
        self.assertIn("焊工证.pdf 第2页", md)  # 依据写到文件和页
        self.assertLess(md.index("## 结论"), md.index("## 逐项明细"))

    def test_sync_previews_and_writes_only_after_confirm(self):
        code, out = run("sync", "--bundle", str(self.bundle))
        self.assertEqual(code, 0, out)
        data = out["data"]
        self.assertTrue(data["preview"])
        self.assertEqual(self.server.posts, [])  # 预览不写服务器
        created = {item["check"] for item in data["willCreate"]}
        self.assertEqual(created, {"AC-R24-01", "AC-R24-04"})  # 引用了已确认证据的未符合项
        skipped = {item["check"] for item in data["skipped"]}
        self.assertEqual(skipped, {"AC-R24-02", "AC-R24-03", "AC-R24-05"})  # 没引用文件，或只引用了未确认的证据
        self.assertEqual(next(i for i in data["willCreate"] if i["check"] == "AC-R24-04")["severity"], "high")  # 高风险提示升级
        # 施工方案那条事实没有对应的已确认证据：只挂对上的那条，没对上的列出来，整项照样写
        first = next(i for i in data["willCreate"] if i["check"] == "AC-R24-01")
        self.assertEqual((first["evidenceLinks"], len(first["unmatchedFacts"])), (1, 1))
        self.assertIn("计划施工期", first["unmatchedFacts"][0])

        code, out = run("sync", "--bundle", str(self.bundle), "--confirm")  # 没带预览摘要不写
        self.assertEqual((out["error"]["code"], self.server.posts), ("previewRequired", []))
        code, out = run("sync", "--bundle", str(self.bundle), "--confirm", "--preview-hash", data["previewHash"])
        self.assertEqual(code, 0, out)
        self.assertEqual(out["data"]["synced"], 2)
        bodies = {body["ruleRefs"][0]["atomicCheckId"]: body for _, _, body in self.server.posts}
        self.assertEqual((bodies["AC-R24-01"]["evidenceLinkIds"], bodies["AC-R24-04"]["evidenceLinkIds"]), (["NEL-1"], ["NEL-3"]))
        self.assertIn("没挂证据链接的事实", bodies["AC-R24-01"]["description"])
        paths = [p for p, _, _ in self.server.posts]
        self.assertEqual(paths, ["/api/review/findings"] * 2)
        for _, headers, body in self.server.posts:
            self.assertEqual(body["source"], "ai")
            self.assertEqual(body["suggestedAction"], "human_confirm")
            [ref] = body["ruleRefs"]  # 与服务器其他 AI 发现同样的对象写法
            self.assertEqual((ref["ruleCode"], ref["ruleSetVersion"]), ("R24", "engineering_inspection_v1"))
            self.assertTrue(ref["atomicCheckId"].startswith("AC-R24-"))
            self.assertTrue(body["evidenceLinkIds"])
            self.assertNotIn("NEL-2", body["evidenceLinkIds"])  # 未确认的证据不发
            self.assertNotIn(ID, json.dumps(body, ensure_ascii=False))
            self.assertTrue(headers.get("Idempotency-Key"))
        self.assertTrue(list((self.bundle / "sync").glob("*.json")))

        keys = [h["Idempotency-Key"] for _, h, _ in self.server.posts]
        run("sync", "--bundle", str(self.bundle), "--confirm", "--preview-hash", data["previewHash"])
        self.assertEqual([h["Idempotency-Key"] for _, h, _ in self.server.posts[2:]], keys)  # 重复同步用同一键，服务器不会重复建

        report = json.loads((self.bundle / "audit.json").read_text(encoding="utf-8"))  # 报告改了，旧的同意不算数
        report["checks"][0]["reasoning"] += "补充一句。"
        (self.bundle / "audit.json").write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
        posted = len(self.server.posts)
        code, out = run("sync", "--bundle", str(self.bundle), "--confirm", "--preview-hash", data["previewHash"])
        self.assertEqual((out["error"]["code"], len(self.server.posts)), ("previewChanged", posted))

    def test_sync_refuses_local_bundle_and_invalid_report(self):
        source = Path(self.tmp.name) / "x.pdf"
        source.write_bytes(PDF)
        code, out = run("local-init", "--node", "24", "--files", str(source), "--out", str(Path(self.tmp.name) / "local"))
        code, out = run("sync", "--bundle", out["data"]["bundle"])
        self.assertEqual(out["error"]["code"], "localBundle")
        report = json.loads((self.bundle / "audit.json").read_text(encoding="utf-8"))
        report["checks"][0]["verdict"] = ""
        (self.bundle / "audit.json").write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
        code, out = run("sync", "--bundle", str(self.bundle))
        self.assertEqual(out["error"]["code"], "reportInvalid")
        self.assertEqual(self.server.posts, [])


if __name__ == "__main__":
    unittest.main()
