from __future__ import annotations

import json
from pathlib import Path

from scripts.ocr_100_collection_intake import build_collection_intake
from scripts.ocr_100_collection_intake_verify import verify_collection_intake


def write_closure(path: Path, *, missing: int = 1) -> None:
    path.write_text(
        json.dumps(
            {
                "scenarioPlan": {
                    "piping_table_profile": {
                        "targetCases": 12,
                        "queuedCases": 4,
                        "readyForEval": 0,
                        "collectionMissingCases": missing,
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def make_intake(tmp_path: Path, *, missing: int = 1) -> Path:
    closure = tmp_path / "closure.json"
    write_closure(closure, missing=missing)
    intake = tmp_path / "intake"
    build_collection_intake(
        closure,
        output_dir=intake,
        queue_output="ocr_eval/reports/new_queue.json",
        copy_to="ocr_eval/real_samples",
    )
    return intake


def test_ocr_100_collection_intake_verify_reports_placeholders(tmp_path: Path) -> None:
    intake = make_intake(tmp_path)

    report = verify_collection_intake(intake)

    assert report["ok"] is True
    assert report["readyToIngest"] is False
    assert report["summary"]["slots"] == 1
    assert report["summary"]["placeholderSlots"] == 1
    assert report["summary"]["warningCounts"]["FILE_NAME_PLACEHOLDER"] == 1


def test_ocr_100_collection_intake_verify_accepts_completed_slot(tmp_path: Path) -> None:
    intake = make_intake(tmp_path)
    sample_dir = intake / "samples" / "piping_table_profile"
    sample_file = sample_dir / "piping-list.pdf"
    sample_file.write_bytes(b"%PDF-1.4\n%fake fixture\n")
    manifest_path = intake / "manifest_template.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["samples"][0]["fileName"] = sample_file.name
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    report = verify_collection_intake(intake)

    assert report["ok"] is True
    assert report["readyToIngest"] is True
    assert report["summary"]["filledSlots"] == 1
    assert report["summary"]["placeholderSlots"] == 0
    assert report["failures"] == []


def test_ocr_100_collection_intake_verify_rejects_profile_and_type_mismatch(tmp_path: Path) -> None:
    intake = make_intake(tmp_path)
    manifest_path = intake / "manifest_template.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["samples"][0]["profileId"] = "quality_certificate_v1"
    manifest["samples"][0]["documentType"] = "quality_certificate"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    report = verify_collection_intake(intake)

    assert report["ok"] is False
    assert report["readyToIngest"] is False
    assert report["summary"]["failureCounts"]["PROFILE_ID_MISMATCH"] == 1
    assert report["summary"]["failureCounts"]["DOCUMENT_TYPE_MISMATCH"] == 1


def test_ocr_100_collection_intake_verify_rejects_missing_or_bad_files(tmp_path: Path) -> None:
    intake = make_intake(tmp_path)
    manifest_path = intake / "manifest_template.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["samples"][0]["fileName"] = "sample.txt"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    report = verify_collection_intake(intake)

    assert report["ok"] is False
    assert report["summary"]["failureCounts"]["FILE_SUFFIX_UNSUPPORTED"] == 1
    assert report["summary"]["failureCounts"]["FILE_NOT_FOUND"] == 1
