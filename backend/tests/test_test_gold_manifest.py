from __future__ import annotations

import json
from pathlib import Path

from libs.document_auto_gold import category_definition_snapshot
from scripts.test_gold_manifest import audit_test_gold_manifest, model_input_for_case


BACKEND = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND.parent
MANIFEST = BACKEND / "ocr_eval" / "test_gold_manifest.json"


def load_manifest() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def test_manifest_covers_exactly_all_23_repository_test_files():
    payload = load_manifest()
    manifest_paths = {item["relativePath"] for item in payload["cases"]}
    actual_paths = {
        str(path.relative_to(REPO_ROOT / "test"))
        for path in (REPO_ROOT / "test").rglob("*")
        if path.is_file() and path.name != ".DS_Store"
    }

    assert payload["expectedFileCount"] == 23
    assert len(payload["cases"]) == 23
    assert manifest_paths == actual_paths


def test_manifest_has_valid_hashes_fine_labels_and_known_categories():
    payload = load_manifest()
    allowed = {
        item["category"]
        for item in category_definition_snapshot()["categories"]
    }

    for case in payload["cases"]:
        assert case["sha256"].startswith("sha256:")
        assert len(case["sha256"]) == len("sha256:") + 64
        assert case["goldDocumentClass"]
        assert case["expectedCategories"]
        assert set(case["expectedCategories"]) <= allowed


def test_mixed_folders_have_explicit_file_level_document_classes():
    payload = load_manifest()
    cases = {item["relativePath"]: item for item in payload["cases"]}

    assert cases["1、设计、安装资质证书/广东政和设计院压力管道设计资质.png"]["goldDocumentClass"] == "design_license"
    assert cases["1、设计、安装资质证书/江苏三江压力管道资质.jpg"]["goldDocumentClass"] == "construction_license"
    assert cases["6、会审记录、图纸/会审记录.png"]["goldDocumentClass"] == "drawing_review_record"
    assert cases["6、会审记录、图纸/地上甲类储罐区2（含泵区）施工图.pdf"]["goldDocumentClass"] == "design_document"
    assert cases["9、焊工资质核查/李卫伍社保缴纳证明.pdf"]["goldDocumentClass"] == "welder_social_security_evidence"
    assert cases["9、焊工资质核查/焊工清单.docx"]["goldDocumentClass"] == "welder_roster"


def test_audit_verifies_all_file_hashes():
    report = audit_test_gold_manifest(REPO_ROOT, MANIFEST)

    assert report["ok"] is True
    assert report["fileCount"] == 23
    assert report["hashMismatchCount"] == 0
    assert report["unknownCategoryCount"] == 0


def test_model_input_contains_only_category_definitions_and_markdown():
    case = dict(load_manifest()["cases"][0])
    case["goldDocumentClass"] = "DO_NOT_LEAK_HUMAN_GOLD_LABEL"
    model_input = model_input_for_case(
        case,
        markdown="# MinerU正文\n\n压力管道设计",
        category_snapshot=category_definition_snapshot(),
    )
    serialized = json.dumps(model_input, ensure_ascii=False)

    assert set(model_input) == {"categoryDefinitionsJson", "ocrMarkdown"}
    assert case["relativePath"] not in serialized
    assert case["goldDocumentClass"] not in serialized
    assert "fileName" not in serialized
    assert "relativePath" not in serialized
