"""Offline boundary cases: handwritten reports, real validator/scorer, zero model calls.

These tests verify the oracle and tooling. They do not execute an auditor or
automatically infer identities, glyphs, or engineering facts from source text.
"""
from __future__ import annotations

import contextlib
import copy
import hashlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

DEV = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("offline_score", DEV / "eval/score.py")
sc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sc)
na = sc.load_node_audit()
CASES = json.loads((DEV / "tests/fixtures/evidence-boundaries.json").read_text())["cases"]


class EvidenceBoundaryTest(unittest.TestCase):
    def exercise(self, category):
        # Any accidental API call or subprocess/model launch fails these cases.
        with patch("socket.socket.connect", side_effect=AssertionError("offline case attempted network")), \
             patch("subprocess.Popen", side_effect=AssertionError("offline case attempted subprocess")):
            for case in (c for c in CASES if c["category"] == category):
                with self.subTest(case=case["id"]), tempfile.TemporaryDirectory() as directory:
                    bundle = Path(directory)
                    source = "files/" + case["document"]
                    other = "files/无关文件.txt"
                    (bundle / "files").mkdir()
                    (bundle / source).write_text(case["input"])
                    (bundle / other).write_text("不包含本案例的主体或要求。")
                    manifest = {"atomicChecks": ["SYNTH-01"], "files": [
                        {"path": source, "fileName": case["document"]},
                        {"path": other, "fileName": "无关文件.txt"}]}
                    (bundle / "bundle.json").write_text(json.dumps(manifest))
                    (bundle / "rules.json").write_text(json.dumps({"atomicChecks": [{"id": "SYNTH-01"}], "standardClauses": []}))
                    report = {"schemaVersion": na.REPORT_SCHEMA, "checks": [{
                        "atomicCheckId": "SYNTH-01", "verdict": case["verdict"], "reason": case["reason"],
                        "facts": [{"name": "案例事实", "value": case["fact"], "source": {"file": source, "page": 1}}]}],
                        "reviewedFiles": [{"file": source, "method": "text"}, {"file": other, "method": "text"}]}
                    gold = {"schemaVersion": sc.GOLD_SCHEMA, "id": case["id"],
                            "checks": {"SYNTH-01": {"verdict": case["verdict"]}},
                            "keyFacts": [{"id": "F1", "desc": case["input"], "where": "SYNTH-01",
                                          "anyOf": [case["tokens"]], "citeFile": case["document"]}]}

                    def evaluate(value):
                        (bundle / "audit.json").write_text(json.dumps(value, ensure_ascii=False))
                        return sc.score(gold, bundle)

                    baseline = evaluate(report)
                    self.assertTrue(baseline["all_pass"], baseline)
                    self.assertEqual(baseline["percent"], 100)
                    for mutation in case["mutations"]:
                        with self.subTest(mutation=mutation["name"]):
                            bad = copy.deepcopy(report)
                            check = bad["checks"][0]
                            for field in ("verdict", "reason"):
                                if field in mutation:
                                    check[field] = mutation[field]
                            if "fact" in mutation:
                                check["facts"][0]["value"] = mutation["fact"]
                            if mutation.get("omitFact"):
                                check["facts"] = []
                            if mutation.get("wrongSource"):
                                check["facts"][0]["source"]["file"] = other
                            result = evaluate(bad)
                            if "verdict" in mutation:
                                self.assertEqual(result["verdicts"][0]["points"], 0)
                                self.assertFalse(result["all_pass"])
                                self.assertEqual(any("误判" in c for c in result["critical"]), mutation["critical"])
                            if mutation.get("missingFact"):
                                self.assertFalse(result["keyFacts"][0]["found"])
                            if mutation.get("wrongCitation"):
                                self.assertTrue(result["keyFacts"][0]["found"])
                                self.assertFalse(result["keyFacts"][0]["cited"])
                                self.assertEqual(result["keyFacts"][0]["points"], 0.5)

    def test_visual_literal_and_inference_boundaries(self):
        self.exercise("visual")

    def test_entity_roles_and_link_evidence(self):
        self.exercise("entity")

    def test_verdict_classification_boundaries(self):
        self.exercise("classification")

    def test_traceability_conflict_and_missing_data_cannot_pass(self):
        for conflict in (False, True):
            with self.subTest(conflict=conflict):
                checks = [{"atomicCheckId": "SOURCE", "verdict": "evidence_insufficient",
                           "conflicts": ["合成批号矛盾"] if conflict else []},
                          {"atomicCheckId": "TRACE", "verdict": "passed"}]
                errors = []
                na.check_strict_rules(checks, {"TRACE": {"role": "traceability"}}, errors)
                self.assertEqual(len(errors), 1)
                self.assertIn("应判需人工确认" if conflict else "应判证据不足", errors[0])

    @unittest.skipUnless(importlib.util.find_spec("fitz"), "PyMuPDF required")
    def test_image_only_stamp_crop_preserves_pixels_and_full_page(self):
        import fitz
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "synthetic-scan.pdf"
            # A raster-only page: text search cannot supply the characters.
            with fitz.open() as drawing:
                page = drawing.new_page(width=300, height=200)
                page.insert_text((55, 75), "复印无效", fontname="china-s", fontsize=18, color=(1, 0, 0))
                page.draw_rect(fitz.Rect(250, 170, 290, 190), color=(0, 0, 1), fill=(0, 0, 1))
                raster = page.get_pixmap(dpi=144).tobytes("png")
            with fitz.open() as document:
                page = document.new_page(width=300, height=200)
                page.insert_image(page.rect, stream=raster)
                document.save(source)

            def render(*extra):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    code = na.main(["pages", "--file", str(source), "--pages", "1", "--out", str(root / "pages"), *extra])
                self.assertEqual(code, 0, output.getvalue())
                return json.loads(output.getvalue())["data"]["pages"][0]

            full = render()
            self.assertFalse(full["textLayer"])
            digest = hashlib.sha256(Path(full["image"]).read_bytes()).hexdigest()
            clip = render("--clip", "0.1,0.1,0.75,0.6", "--dpi", "300")
            self.assertEqual(clip["page"], 1)
            self.assertEqual(clip["clip"], [0.1, 0.1, 0.75, 0.6])
            self.assertNotEqual(full["image"], clip["image"])
            self.assertEqual(hashlib.sha256(Path(full["image"]).read_bytes()).hexdigest(), digest)
            pix = fitz.Pixmap(clip["image"])
            self.assertGreater(pix.width, 800)
            self.assertGreater(pix.height, 400)
            pixels = list(zip(*(iter(pix.samples),) * pix.n))
            self.assertTrue(any(r > 180 and g < 80 and b < 80 for r, g, b in pixels))
            self.assertFalse(any(b > 180 and r < 80 and g < 80 for r, g, b in pixels))


if __name__ == "__main__":
    unittest.main()
