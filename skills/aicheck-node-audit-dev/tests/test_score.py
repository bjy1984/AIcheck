"""Scoring against a gold answer, on a synthetic bundle; no project data."""
from __future__ import annotations

import contextlib
import copy
import importlib.util
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2] / "aicheck-node-audit"


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


na = load("node_audit_for_score_test", ROOT / "scripts/node_audit.py")
sc = load("score_under_test", Path(__file__).resolve().parents[1] / "eval/score.py")

GOLD = {
    "schemaVersion": "aicheck-node-audit-gold@1",
    "id": "synthetic-24",
    "checks": {
        "AC-R24-01": {"verdict": "evidence_insufficient", "accept": ["human_review_required"]},
        "AC-R24-02": {"verdict": "evidence_insufficient"},
        "AC-R24-03": {"verdict": "evidence_insufficient"},
        "AC-R24-04": {"verdict": "evidence_insufficient"},
        "AC-R24-05": {"verdict": "human_review_required", "accept": ["evidence_insufficient"]},
    },
    "keyFacts": [
        {"id": "K1", "desc": "合同计划工期", "where": "AC-R24-01", "anyOf": [["2025-11-03", "2026-01-20"]], "citeFile": "监检合同", "weight": 2},
        {"id": "K2", "desc": "FeⅢ 不覆盖", "where": "AC-R24-02", "anyOf": [["FeIII"]], "weight": 2},
        {"id": "K3", "desc": "缺施焊记录", "where": "missingMaterials", "anyOf": [["施焊记录"]], "weight": 1},
    ],
    "expectConflicts": ["AC-R24-04"],
    "toolsUsed": ["cert-registry"],
    "forbiddenPatterns": [{"id": "id-number", "validator": "id_number", "desc": "报告出现完整身份证号"}],
}


class ScoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        home = Path(self.tmp.name)
        self.env = patch.dict(os.environ, {"AICHECK_AUDIT_HOME": str(home / "audits"),
                                           "AICHECK_SESSION_FILE": str(home / "session.json")})
        self.env.start()
        project = home / "项目"
        project.mkdir()
        (project / "压力管道施工监检合同.txt").write_text("计划施工时间 2025年11月3日～2026年1月20日", encoding="utf-8")
        (project / "焊工证.txt").write_text("证", encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()):
            na.main(["local-init", "--node", "24", "--project-dir", str(project), "--out", str(home / "b")])
        self.bundle = home / "b"
        self.files = json.loads((self.bundle / "bundle.json").read_text(encoding="utf-8"))["files"]

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def write(self, checks, **extra):
        report = {"schemaVersion": na.REPORT_SCHEMA, "checks": checks,
                  "reviewedFiles": [{"file": f["path"], "method": "read"} for f in self.files], **extra}
        (self.bundle / "audit.json").write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")

    def good_checks(self, contract: str):
        fact = {"name": "计划施工时间", "value": "2025年11月3日至2026年1月20日", "source": {"file": contract, "page": 1}}
        return [
            {"atomicCheckId": "AC-R24-01", "verdict": "evidence_insufficient", "reason": "缺施焊日期", "facts": [fact]},
            {"atomicCheckId": "AC-R24-02", "verdict": "evidence_insufficient", "reason": "铬钼钢段 FeⅢ 不在 FeⅠ 证覆盖内"},
            {"atomicCheckId": "AC-R24-03", "verdict": "evidence_insufficient", "reason": "无施焊记录"},
            {"atomicCheckId": "AC-R24-04", "verdict": "evidence_insufficient", "reason": "批号矛盾", "conflicts": ["批号不一致"]},
            {"atomicCheckId": "AC-R24-05", "verdict": "human_review_required", "reason": "有冲突"},
        ]

    def test_full_marks_with_normalized_dates_and_roman_numerals(self):
        contract = next(f["path"] for f in self.files if "监检合同" in f["fileName"])
        self.write(self.good_checks(contract), missingMaterials=["实际施焊记录：未提供"])
        (self.bundle / "tool-results").mkdir()
        (self.bundle / "tool-results" / "20261023-000000-cert-registry.json").write_text('{"ok": false, "error": {}}', encoding="utf-8")
        self.assertEqual(sc.score(GOLD, self.bundle)["points"], 18.5)  # 查询失败已存档：半分
        (self.bundle / "tool-results" / "20261023-000001-cert-registry.json").write_text('{"ok": true, "result": {}}', encoding="utf-8")
        result = sc.score(GOLD, self.bundle)
        self.assertEqual(result["critical"], [])
        # 结论 5×2 + 事实 2+2+1 + 冲突 1 + 工具 1 + 校验 2
        self.assertEqual((result["points"], result["max"], result["percent"]), (19.0, 19.0, 100.0))
        self.assertFalse(result["all_pass"])  # 满分不等于固定主条款取证完整
        self.assertEqual(result["standardEvidence"]["status"], "review_required")

    def test_false_pass_uncited_fact_and_id_leak_are_caught(self):
        other = next(f["path"] for f in self.files if "焊工证" in f["fileName"])
        checks = self.good_checks(other)  # 工期引到了焊工证上
        checks[2] = {"atomicCheckId": "AC-R24-03", "verdict": "passed", "facts": [{"name": "n", "value": "v", "source": {"file": other, "page": 1}}]}
        checks[3].pop("conflicts")
        checks[4]["verdict"] = "evidence_insufficient"
        self.write(checks, summary="持证人身份证 110101199001011237，信用代码 913201001234567890")
        result = sc.score(GOLD, self.bundle)
        joined = " ".join(result["critical"])
        self.assertIn("误判符合 AC-R24-03", joined)
        self.assertIn("报告出现完整身份证号", joined)
        self.assertIn("报告未通过校验", joined)  # 逐焊口检查无 coverage 判符合，校验器拒绝
        facts = {r["id"]: r for r in result["keyFacts"]}
        self.assertEqual((facts["K1"]["found"], facts["K1"]["cited"], facts["K1"]["points"]), (True, False, 1.0))
        self.assertEqual(facts["K3"]["points"], 0.0)
        verdicts = {r["check"]: r["points"] for r in result["verdicts"]}
        self.assertEqual((verdicts["AC-R24-03"], verdicts["AC-R24-05"]), (0.0, 1.0))
        self.assertIn("| AC-R24-03 | evidence_insufficient | passed | 0/2 |", sc.markdown(result))

    def test_a_pass_the_gold_accepts_is_not_a_critical_error(self):
        other = next(f["path"] for f in self.files if "焊工证" in f["fileName"])
        checks = self.good_checks(other)
        checks[2] = {"atomicCheckId": "AC-R24-03", "verdict": "passed", "facts": [{"name": "n", "value": "v", "source": {"file": other, "page": 1}}],
                     "reasoning": "x", "coverage": {"items": 1, "checked": 1, "source": "x"}}
        self.write(checks)
        gold = {**GOLD, "checks": {**GOLD["checks"], "AC-R24-03": {**GOLD["checks"]["AC-R24-03"], "accept": ["passed"]}}}
        self.assertFalse([c for c in sc.score(gold, self.bundle)["critical"] if "误判符合" in c])
        self.assertTrue([c for c in sc.score(GOLD, self.bundle)["critical"] if "误判符合" in c])

    def test_anywhere_fact_with_cite_file_counts_a_citation_in_any_check(self):
        contract = next(f["path"] for f in self.files if "监检合同" in f["fileName"])
        self.write(self.good_checks(contract))
        gold = {**GOLD, "keyFacts": [{"id": "A1", "desc": "工期", "where": "anywhere", "anyOf": [["2025-11-03"]],
                                      "citeFile": "监检合同", "weight": 2}]}
        [fact] = sc.score(gold, self.bundle)["keyFacts"]
        self.assertEqual((fact["found"], fact["cited"], fact["points"]), (True, True, 2.0))

    def test_lenient_score_counts_accepted_alternatives_in_full(self):
        contract = next(f["path"] for f in self.files if "监检合同" in f["fileName"])
        checks = self.good_checks(contract)
        checks[0]["verdict"] = "human_review_required"  # gold 首选证据不足，也接受需人工确认
        checks[4]["verdict"] = "evidence_insufficient"  # gold 首选需人工确认，也接受证据不足
        self.write(checks)
        result = sc.score(GOLD, self.bundle)
        alternatives = [r for r in result["verdicts"] if r["points"] == 1]
        self.assertEqual(len(alternatives), 2)
        self.assertEqual(result["lenientPoints"], result["points"] + 2)
        self.assertGreater(result["lenientPercent"], result["percent"])

    def test_fact_only_in_risk_flags_counts(self):
        gold = {**GOLD, "keyFacts": [{"id": "K4", "desc": "订货单位不是施工单位", "anyOf": [["某某供应链公司"]], "weight": 1}]}
        contract = next(f["path"] for f in self.files if "监检合同" in f["fileName"])
        self.write(self.good_checks(contract))
        self.assertEqual(sc.score(gold, self.bundle)["keyFacts"][0]["points"], 0.0)
        self.write(self.good_checks(contract), riskFlags=[{"level": "medium", "flag": "质证订货单位为某某供应链公司", "basis": "质证第 2 页"}])
        self.assertEqual(sc.score(gold, self.bundle)["keyFacts"][0]["points"], 1.0)

    def standard_fixture(self):
        # Invented standard and clause; no gold facts or real project data.
        clause = {"standardRef": "STD-DEMO-2099", "clauseNo": "A1", "sourcePage": 2,
                  "knowledgeFileId": "KF-SYNTHETIC", "bindingRole": "primary", "applicability": "always"}
        (self.bundle / "rules.json").write_text(json.dumps({"standardClauses": [clause]}))
        archive = "tool-results/demo-standard-content.json"
        record = {"tool": "standard-content", "ok": True,
                  "arguments": {"file_id": "KF-SYNTHETIC", "page_no": 2},
                  "result": {"knowledgeFileId": "KF-SYNTHETIC", "selection": {"contentFound": True},
                             "blocks": [{"pageNo": 2, "text": "A1 Example requirement: keep records."}]}}
        report = {"checks": [{"facts": [{"source": {"file": "tool:standard-content",
                   "locator": archive + "，第2页A1"}}]}]}
        return clause, archive, record, report

    def save_standard(self, archive, record):
        path = self.bundle / archive
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(record))

    def test_standard_evidence_distinguishes_missing_failed_and_empty_content(self):
        _, archive, record, report = self.standard_fixture()
        self.assertEqual(sc.standard_evidence(self.bundle, {})["rows"][0]["status"], "not_recorded")
        self.assertEqual(sc.standard_evidence(self.bundle, report)["rows"][0]["status"], "unbacked_citation")
        self.save_standard(archive, {**record, "ok": False, "error": {"code": "unavailable"}})
        self.assertEqual(sc.standard_evidence(self.bundle, report)["rows"][0]["status"], "retrieval_failed")
        record["result"]["selection"]["contentFound"] = False
        self.save_standard(archive, record)
        self.assertEqual(sc.standard_evidence(self.bundle, report)["rows"][0]["status"], "content_unverified")

    def test_standard_evidence_requires_matching_archive_content_and_citation(self):
        _, archive, record, report = self.standard_fixture()
        self.save_standard(archive, record)
        self.assertEqual(sc.standard_evidence(self.bundle, report)["status"], "complete")
        self.assertEqual(sc.standard_evidence(self.bundle, {})["rows"][0]["status"], "retrieved_uncited")
        changes = [("wrong identity", lambda r: r["result"].update(knowledgeFileId="KF-OTHER")),
                   ("wrong tool", lambda r: r.update(tool="standards")),
                   ("wrong page", lambda r: r["result"]["blocks"][0].update(pageNo=3)),
                   ("clause prefix", lambda r: r["result"]["blocks"][0].update(text="A10 另一条要求")),
                   ("empty content", lambda r: r["result"].update(blocks=[]))]
        for label, mutate in changes:
            with self.subTest(label=label):
                changed = copy.deepcopy(record)
                mutate(changed)
                self.save_standard(archive, changed)
                self.assertEqual(sc.standard_evidence(self.bundle, report)["status"], "review_required")
        self.save_standard(archive, record)
        report["checks"][0]["facts"][0]["source"]["locator"] = archive + ".backup，A1"
        self.assertNotEqual(sc.standard_evidence(self.bundle, report)["status"], "complete")

    def test_local_standard_and_conditional_binding_require_review_not_false_failure(self):
        clause, _, _, _ = self.standard_fixture()
        report = {"checks": [{"facts": [{"source": {"file": "standard:rules/standards/DEMO-2099.pdf",
                   "page": 2, "excerpt": "A1 示例要求"}}]}]}
        result = sc.standard_evidence(self.bundle, report)
        self.assertEqual(result["rows"][0]["status"], "local_citation_review")
        clause["applicability"] = "when applicable"
        (self.bundle / "rules.json").write_text(json.dumps({"standardClauses": [clause]}))
        self.assertEqual(sc.standard_evidence(self.bundle, report)["rows"][0]["status"], "applicability_review")

    def test_broken_rules_or_archive_are_visible(self):
        _, archive, _, report = self.standard_fixture()
        self.save_standard(archive, {})
        (self.bundle / archive).write_text("{broken")
        self.assertTrue(sc.standard_evidence(self.bundle, report)["warnings"])
        (self.bundle / "rules.json").write_text("{broken")
        self.assertEqual(sc.standard_evidence(self.bundle, report)["status"], "review_required")

    def compound_fixture(self):
        clause, archive, record, report = self.standard_fixture()
        clause["clauseNo"] = "B3.2(4)"
        (self.bundle / "rules.json").write_text(json.dumps({"standardClauses": [clause]}))
        record["arguments"]["section"] = "B3.2"
        record["result"]["blocks"] = [
            {"pageNo": 2, "text": "B3.2 Documents to inspect"},
            {"pageNo": 2, "text": "(3) Retain the delivery record."},
            {"pageNo": 2, "text": "（4） Verify the batch and material on the certificate."},
        ]
        report["checks"][0]["facts"][0]["source"]["locator"] = archive + "，第2页 B3.2(4)"
        return archive, record, report

    def test_compound_clause_parent_and_item_in_separate_blocks(self):
        archive, record, report = self.compound_fixture()
        for section in ("B3.2", "B3.2(4)", None):
            with self.subTest(section=section):
                record["arguments"]["section"] = section
                self.save_standard(archive, record)
                self.assertEqual(sc.standard_evidence(self.bundle, report)["status"], "complete")
                self.assertEqual(sc.standard_evidence(self.bundle, {})["rows"][0]["status"], "retrieved_uncited")

    def test_compound_clause_rejects_unrelated_or_empty_items(self):
        archive, record, report = self.compound_fixture()
        for label, blocks in {
            "wrong parent": ["B3.20 Other", "(4) Other requirement."],
            "next parent": ["B3.2 Correct parent", "B3.3 Other", "(4) Other requirement."],
            "different child": ["B3.2 Correct parent", "(40) Other requirement."],
            "child absent": ["B3.2 Correct parent", "(3) Other requirement."],
            "child without parent": ["(4) Some requirement."],
            "empty child": ["B3.2 Correct parent", "(4)", "(5) Other requirement."],
            "parent only in prose": ["See B3.2 for details.", "(4) Other requirement."],
            "contents entry": ["B3.2 Documents .... 12", "(4) Certificates .... 13"],
            "other nested parent": ["B3.2 Correct parent", "B3.2.1 Other", "(4) Other requirement."],
            "nested subitem": ["B3.2 Correct parent", "(4)(1) Only a nested subitem."],
        }.items():
            with self.subTest(label=label):
                record["result"]["blocks"] = [{"pageNo": 2, "text": s} for s in blocks]
                self.save_standard(archive, record)
                self.assertEqual(sc.standard_evidence(self.bundle, report)["status"], "review_required")

    def test_compound_clause_never_joins_different_pages_or_archives(self):
        archive, record, report = self.compound_fixture()
        record["result"]["blocks"][-1]["pageNo"] = 3
        self.save_standard(archive, record)
        other = copy.deepcopy(record)
        other["result"]["blocks"] = [{"pageNo": 2, "text": "(4) Verify the certificate."}]
        self.save_standard("tool-results/other-standard-content.json", other)
        self.assertEqual(sc.standard_evidence(self.bundle, report)["status"], "review_required")

    def test_compound_clause_explicit_label_and_split_body(self):
        archive, record, report = self.compound_fixture()
        for blocks in (["B3.2(4) Verify the certificate."],
                       ["B 3 . 2 （ 4 ）", "Verify the certificate."]):
            with self.subTest(blocks=blocks):
                record["result"]["blocks"] = [{"pageNo": 2, "text": s} for s in blocks]
                self.save_standard(archive, record)
                self.assertEqual(sc.standard_evidence(self.bundle, report)["status"], "complete")

    def test_clause_heading_or_index_alone_does_not_prove_body_retrieved(self):
        _, archive, record, report = self.standard_fixture()
        for blocks in (["Unrelated text", "A1"], ["A1", "A2 Some other requirement."],
                       ["A1 Example requirement ........ 13"], ["A1(1) A subitem only."],
                       ["A1 (1) A subitem only."], ["A1 . 2 Another section."]):
            with self.subTest(blocks=blocks):
                record["result"]["blocks"] = [{"pageNo": 2, "text": s} for s in blocks]
                self.save_standard(archive, record)
                self.assertEqual(sc.standard_evidence(self.bundle, report)["status"], "review_required")

    def test_explicit_wrong_citation_page_is_not_documented(self):
        _, archive, record, report = self.standard_fixture()
        self.save_standard(archive, record)
        report["checks"][0]["facts"][0]["source"]["page"] = 9
        self.assertEqual(sc.standard_evidence(self.bundle, report)["rows"][0]["status"], "retrieved_uncited")


if __name__ == "__main__":
    unittest.main()
