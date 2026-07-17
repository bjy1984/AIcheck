from __future__ import annotations

from copy import deepcopy

from libs.material_review_assets import load_material_review_asset, material_review_asset_status
from libs.ocr_readiness import build_document_ocr_readiness


class FakeRepo:
    def __init__(self, parse_results: list[dict] | None = None) -> None:
        self.state = {"ocr_parse_results": parse_results or []}

    @staticmethod
    def clone(value):
        return deepcopy(value)


def document(status: str = "已识别") -> dict:
    return {
        "id": "DOC-OCR-READY",
        "currentVersionId": "DV-OCR-READY-V1",
        "currentOcrStatus": status,
    }


def parse_result(*, fragments: list[dict], status: str = "success", quality: dict | None = None) -> dict:
    return {
        "id": "PARSE-OCR-READY",
        "parseResultId": "PARSE-OCR-READY",
        "documentVersionId": "DV-OCR-READY-V1",
        "status": status,
        "quality": quality or {"status": "auto_usable", "reasons": []},
        "fields": [],
        "fragments": fragments,
        "tables": [],
        "seals": [],
        "finishedAt": "2026-07-10 12:00:00",
    }


def test_recognized_label_without_parse_result_is_inconsistent() -> None:
    readiness = build_document_ocr_readiness(FakeRepo(), document())

    assert readiness["status"] == "inconsistent"
    assert readiness["artifactIntegrity"] is False
    assert readiness["retryable"] is True
    assert readiness["blockingReasons"][0]["code"] == "OCR_STATUS_WITHOUT_PARSE_RESULT"


def test_parse_text_without_bbox_is_incomplete() -> None:
    repo = FakeRepo([parse_result(fragments=[{"text": "检测报告编号 UT-001"}])])

    readiness = build_document_ocr_readiness(repo, document())

    assert readiness["status"] == "incomplete"
    assert readiness["fragmentCount"] == 1
    assert readiness["bboxCoverage"] == 0


def test_parse_text_with_bbox_is_ready() -> None:
    repo = FakeRepo(
        [parse_result(fragments=[{"text": "检测报告编号 UT-001", "bbox": [10, 20, 110, 48]}])]
    )

    readiness = build_document_ocr_readiness(repo, document())

    assert readiness["status"] == "ready"
    assert readiness["artifactIntegrity"] is True
    assert readiness["bboxCoverage"] == 1


def test_parse_with_required_quality_gap_is_incomplete_even_with_bbox() -> None:
    repo = FakeRepo(
        [
            parse_result(
                fragments=[{"text": "DRAWING LIST", "bbox": [10, 20, 110, 48]}],
                quality={"status": "needs_human_review", "reasons": ["REQUIRED_FIELD_MISSING"]},
            )
        ]
    )

    readiness = build_document_ocr_readiness(repo, document())

    assert readiness["status"] == "incomplete"
    assert readiness["outcomeStatus"] == "partial"
    assert readiness["artifactIntegrity"] is False
    assert readiness["blockingReasons"][0]["code"] == "OCR_QUALITY_GATE_BLOCKED"


def test_material_review_asset_is_packaged_and_versioned() -> None:
    asset = load_material_review_asset()
    status = material_review_asset_status()

    assert asset["schemaVersion"] == "aicheck-material-review-points@1"
    assert asset["itemCount"] == 156
    assert asset["sourceSha256"]
    assert status["ready"] is True
