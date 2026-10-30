"""盲评包：服务器结论去掉，资料和证据挂载留着。临时目录里造一个服务器资料包，不碰真数据。"""
from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

BLIND = Path(__file__).resolve().parents[1] / "eval/blind_bundle.py"
spec = importlib.util.spec_from_file_location("blind_under_test", BLIND)
blind = importlib.util.module_from_spec(spec)
spec.loader.exec_module(blind)
na = blind.na


class BlindBundleTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.bundle = Path(self.tmp.name) / "P-1" / "node-08" / "20261029-000000"
        (self.bundle / na.SERVER_RAW_DIR).mkdir(parents=True)
        self.rules = {"ruleId": "R08", "rule": {"name": "标准版本", "criteria": "现行有效", "checkMethod": "逐项核对"},
                      "standardClauses": [], "node": {"requiredMaterials": []},
                      "atomicChecks": [{"id": "AC-R08-01", "name": "现行有效", "instruction": "核查标准是否现行有效", "serverTools": []}]}
        self.manifest = {"schemaVersion": na.BUNDLE_SCHEMA, "source": "server", "baseUrl": "http://server", "projectId": "P-1",
                         "nodeId": 8, "ruleId": "R08", "fetchedAt": "2026-10-29T07:00:00", "files": [],
                         "parts": {"workspace": "workspace.json", "reviewRun": "review-run.json"},
                         "serverOutcomes": {"AC-R08-01": {"result": "evidence_insufficient"}}, "atomicChecks": ["AC-R08-01"]}
        workspace = {"node": {"status": "待人工确认"}, "aiReview": {"aiRuns": [{"conclusion": "证据不足"}]}}
        for relative, value in (("bundle.json", self.manifest), ("rules.json", self.rules), ("workspace.json", workspace),
                                (f"{na.SERVER_RAW_DIR}/workspace.json", workspace), ("review-run.json", {"outcomes": 1}),
                                (f"{na.SERVER_RAW_DIR}/review-run.json", {"outcomes": 1}), ("evidence-chain.json", {"links": [{"pageNo": 3}]})):
            na.write_private(self.bundle / relative, na.dump(value))
        na.write_digest(self.bundle, self.manifest, self.rules, workspace)

    def tearDown(self):
        self.tmp.cleanup()

    def test_server_conclusions_are_removed_and_inputs_kept(self):
        self.assertIn("服务器结果：evidence_insufficient", (self.bundle / "digest.md").read_text(encoding="utf-8"))
        out = blind.blind(self.bundle)
        self.assertEqual(len(out["removed"]), 6)
        digest = (self.bundle / "digest.md").read_text(encoding="utf-8")
        self.assertIn("服务器结果：—", digest)
        self.assertNotIn("evidence_insufficient", digest)
        manifest = json.loads((self.bundle / "bundle.json").read_text(encoding="utf-8"))
        self.assertEqual((manifest["serverOutcomes"], manifest["parts"]), ({}, {"workspace": "workspace.json"}))
        for relative in ("review-run.json", f"{na.SERVER_RAW_DIR}/review-run.json"):
            self.assertFalse((self.bundle / relative).exists())
        for relative in ("workspace.json", f"{na.SERVER_RAW_DIR}/workspace.json"):
            workspace = json.loads((self.bundle / relative).read_text(encoding="utf-8"))
            self.assertEqual((workspace["aiReview"], workspace["node"]), ({}, {"status": "待人工确认"}))
        self.assertTrue((self.bundle / "evidence-chain.json").exists())  # 证据挂在哪页是输入，留着
        self.assertEqual(blind.blind(self.bundle)["removed"], [])  # 再跑一次不出错

    def test_a_local_bundle_is_refused(self):
        na.write_private(self.bundle / "bundle.json", na.dump({**self.manifest, "source": "local"}))
        with self.assertRaises(SystemExit):
            blind.blind(self.bundle)


if __name__ == "__main__":
    unittest.main()
