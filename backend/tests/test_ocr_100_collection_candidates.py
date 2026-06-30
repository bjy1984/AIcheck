from __future__ import annotations

import json
from pathlib import Path

from scripts.ocr_100_collection_candidates import build_collection_candidate_report
from scripts.ocr_100_ingest_samples import sha256_file


def test_collection_candidates_classifies_new_files(tmp_path: Path) -> None:
    sample = tmp_path / "RT-report.pdf"
    sample.write_bytes(b"%PDF-1.4\nrt report\n")

    report = build_collection_candidate_report([tmp_path])

    assert report["ok"] is True
    assert report["summary"]["inputFiles"] == 1
    assert report["summary"]["newCandidates"] == 1
    assert report["candidates"][0]["scenario"] == "ndt_rt_profile"
    assert report["candidates"][0]["profileId"] == "ndt_rt_report_v1"


def test_collection_candidates_marks_existing_queue_hashes_as_duplicates(tmp_path: Path) -> None:
    sample = tmp_path / "RT-report.pdf"
    sample.write_bytes(b"%PDF-1.4\nrt report\n")
    queue = tmp_path / "queue.json"
    queue.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "caseId": "existing-1",
                        "scenario": "ndt_rt_profile",
                        "source": {"fileName": sample.name, "sha256": sha256_file(sample)},
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = build_collection_candidate_report([tmp_path], existing_queues=[queue])

    assert report["summary"]["newCandidates"] == 0
    assert report["summary"]["duplicates"] == 1
    assert report["candidates"][0]["duplicateOf"]["caseId"] == "existing-1"
    assert report["candidates"][0]["effectiveScenario"] == "ndt_rt_profile"
    assert report["summary"]["duplicateScenarioCounts"] == {"ndt_rt_profile": 1}


def test_collection_candidates_copies_new_files_to_intake_scenario_folder(tmp_path: Path) -> None:
    source_dir = tmp_path / "incoming"
    source_dir.mkdir()
    sample = source_dir / "UT-report.pdf"
    sample.write_bytes(b"%PDF-1.4\nut report\n")
    intake = tmp_path / "intake"

    report = build_collection_candidate_report(
        [source_dir],
        intake_dir=intake,
        copy_to_intake=True,
    )

    copied = Path(report["copied"][0]["destination"])
    assert report["summary"]["copied"] == 1
    assert copied.exists()
    assert copied.parent == intake / "samples" / "ndt_ut_profile"
    assert copied.name.endswith("UT-report.pdf")


def test_collection_candidates_requires_intake_dir_when_copying(tmp_path: Path) -> None:
    sample = tmp_path / "RT-report.pdf"
    sample.write_bytes(b"%PDF-1.4\nrt report\n")

    report = build_collection_candidate_report([tmp_path], copy_to_intake=True)

    assert report["ok"] is False
    assert report["summary"]["failureCount"] == 1
    assert report["failures"][0]["code"] == "INTAKE_DIR_REQUIRED"
