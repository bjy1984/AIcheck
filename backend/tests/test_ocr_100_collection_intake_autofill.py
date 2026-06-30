from __future__ import annotations

import json
from pathlib import Path

from scripts.ocr_100_collection_intake import build_collection_intake
from scripts.ocr_100_collection_intake_autofill import autofill_collection_intake
from scripts.ocr_100_collection_intake_verify import verify_collection_intake


def make_intake(tmp_path: Path, *, scenario: str = "piping_table_profile", missing: int = 2) -> Path:
    closure = tmp_path / "closure.json"
    closure.write_text(
        json.dumps(
            {
                "scenarioPlan": {
                    scenario: {
                        "targetCases": missing,
                        "queuedCases": 0,
                        "readyForEval": 0,
                        "collectionMissingCases": missing,
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    intake = tmp_path / "intake"
    build_collection_intake(
        closure,
        output_dir=intake,
        queue_output="ocr_eval/reports/new_queue.json",
        copy_to="ocr_eval/real_samples",
    )
    return intake


def test_ocr_100_collection_intake_autofill_assigns_files_and_verifies(tmp_path: Path) -> None:
    intake = make_intake(tmp_path, missing=2)
    sample_dir = intake / "samples" / "piping_table_profile"
    (sample_dir / "a-piping.pdf").write_bytes(b"%PDF-1.4\nsample-a\n")
    (sample_dir / "b-piping.png").write_bytes(b"png-sample")

    report = autofill_collection_intake(intake)
    output_manifest = Path(report["summary"]["outputManifest"])
    manifest = json.loads(output_manifest.read_text(encoding="utf-8"))
    verification = verify_collection_intake(intake, manifest=output_manifest)

    assert report["ok"] is True
    assert report["summary"]["assignedSlots"] == 2
    assert report["summary"]["readyToIngest"] is True
    assert [item["fileName"] for item in manifest["samples"]] == ["a-piping.pdf", "b-piping.png"]
    assert verification["readyToIngest"] is True


def test_ocr_100_collection_intake_autofill_keeps_remaining_placeholders(tmp_path: Path) -> None:
    intake = make_intake(tmp_path, missing=2)
    sample_dir = intake / "samples" / "piping_table_profile"
    (sample_dir / "only-one.pdf").write_bytes(b"%PDF-1.4\nsample\n")

    report = autofill_collection_intake(intake)

    assert report["summary"]["assignedSlots"] == 1
    assert report["summary"]["readyToIngest"] is False
    assert report["summary"]["remainingPlaceholders"] == 1


def test_ocr_100_collection_intake_autofill_skips_standards_by_default(tmp_path: Path) -> None:
    intake = make_intake(tmp_path, scenario="quality_gate_profile", missing=1)
    sample_dir = intake / "samples" / "quality_gate_profile"
    (sample_dir / "GB-T-1234-标准.pdf").write_bytes(b"%PDF-1.4\nstandard\n")

    report = autofill_collection_intake(intake)

    assert report["summary"]["assignedSlots"] == 0
    assert report["summary"]["remainingPlaceholders"] == 1
    assert report["summary"]["warningCounts"]["STANDARD_LIKE_FILE_SKIPPED"] == 1


def test_ocr_100_collection_intake_autofill_preserves_existing_filled_slot(tmp_path: Path) -> None:
    intake = make_intake(tmp_path, missing=2)
    sample_dir = intake / "samples" / "piping_table_profile"
    (sample_dir / "existing.pdf").write_bytes(b"%PDF-1.4\nexisting\n")
    (sample_dir / "new.pdf").write_bytes(b"%PDF-1.4\nnew\n")
    manifest_path = intake / "manifest_template.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["samples"][0]["fileName"] = "existing.pdf"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    report = autofill_collection_intake(intake)
    output_manifest = Path(report["summary"]["outputManifest"])
    updated = json.loads(output_manifest.read_text(encoding="utf-8"))

    assert report["summary"]["assignedSlots"] == 1
    assert [item["fileName"] for item in updated["samples"]] == ["existing.pdf", "new.pdf"]
