from __future__ import annotations

import json
from pathlib import Path

from scripts.ocr_100_collection_intake import build_collection_intake


def test_ocr_100_collection_intake_creates_scenario_folders_and_manifest(tmp_path: Path) -> None:
    closure = tmp_path / "closure.json"
    closure.write_text(
        json.dumps(
            {
                "scenarioPlan": {
                    "piping_table_profile": {
                        "targetCases": 12,
                        "queuedCases": 10,
                        "readyForEval": 0,
                        "collectionMissingCases": 2,
                        "collectionHint": "Collect piping lists.",
                    },
                    "quality_certificate_profile": {
                        "targetCases": 10,
                        "queuedCases": 10,
                        "readyForEval": 0,
                        "collectionMissingCases": 0,
                    },
                    "ndt_rt_profile": {
                        "targetCases": 10,
                        "queuedCases": 9,
                        "readyForEval": 0,
                        "collectionMissingCases": 1,
                    },
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    out = tmp_path / "intake"

    report = build_collection_intake(
        closure,
        output_dir=out,
        queue_output="ocr_eval/reports/new_queue.json",
        copy_to="ocr_eval/real_samples",
    )
    manifest = json.loads((out / "manifest_template.json").read_text(encoding="utf-8"))
    readme = (out / "README.md").read_text(encoding="utf-8")

    assert report["ok"] is True
    assert report["summary"]["slots"] == 3
    assert report["summary"]["scenarios"] == 2
    assert (out / "samples" / "piping_table_profile" / ".gitkeep").exists()
    assert (out / "samples" / "ndt_rt_profile" / "README.md").exists()
    assert len(manifest["samples"]) == 3
    assert any(item["fileName"].startswith("replace-with-piping_table_profile") for item in manifest["samples"])
    assert {item["scenario"] for item in manifest["samples"]} == {"piping_table_profile", "ndt_rt_profile"}
    assert "ocr_100_collection_intake_autofill.py" in report["summary"]["commands"]["autofillManifest"]
    assert "manifest_autofilled.json" in report["summary"]["commands"]["verifyAutofilledManifest"]
    assert "ocr_100_ingest_samples.py" in report["summary"]["commands"]["ingestAll"]
    assert "manifest_autofilled.json" in report["summary"]["commands"]["ingestAll"]
    assert "Scenario Gaps" in readme
    assert "quality_certificate_profile" not in {item["scenario"] for item in report["summary"]["scenarioItems"]}


def test_ocr_100_collection_intake_handles_no_missing_slots(tmp_path: Path) -> None:
    closure = tmp_path / "closure.json"
    closure.write_text(
        json.dumps({"scenarioPlan": {"quality_certificate_profile": {"collectionMissingCases": 0}}}, ensure_ascii=False),
        encoding="utf-8",
    )

    report = build_collection_intake(
        closure,
        output_dir=tmp_path / "intake",
        queue_output="queue.json",
        copy_to="samples",
    )

    assert report["summary"]["slots"] == 0
    assert json.loads((tmp_path / "intake" / "manifest_template.json").read_text(encoding="utf-8"))["samples"] == []
