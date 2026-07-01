from __future__ import annotations

import json
from pathlib import Path

from scripts.ocr_100_collection_intake import build_collection_intake
from scripts.ocr_100_collection_intake_pipeline import run_collection_pipeline


def make_intake(tmp_path: Path, *, missing: int = 1) -> Path:
    closure = tmp_path / "closure.json"
    closure.write_text(
        json.dumps(
            {
                "scenarioPlan": {
                    "piping_table_profile": {
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
        queue_output=str(tmp_path / "queue.json"),
        copy_to=str(tmp_path / "real_samples"),
    )
    return intake


def test_ocr_100_collection_intake_pipeline_blocks_execution_when_not_ready(tmp_path: Path) -> None:
    intake = make_intake(tmp_path)
    queue_output = tmp_path / "queue.json"

    report = run_collection_pipeline(
        intake,
        queue_output=queue_output,
        annotation_output_dir=tmp_path / "pack",
        ocr_result_dir=tmp_path / "ocr_results",
        base_dir=tmp_path,
        copy_to=tmp_path / "real_samples",
        execute=True,
    )

    assert report["ok"] is True
    assert report["readyToExecute"] is False
    assert report["executedSteps"] == [{"step": "execute", "status": "skipped", "reason": "intake_not_ready"}]
    assert not queue_output.exists()


def test_ocr_100_collection_intake_pipeline_dry_run_plans_without_writing_queue(tmp_path: Path) -> None:
    intake = make_intake(tmp_path)
    sample_dir = intake / "samples" / "piping_table_profile"
    (sample_dir / "piping.pdf").write_bytes(b"%PDF-1.4\nsample\n")
    queue_output = tmp_path / "queue.json"

    report = run_collection_pipeline(
        intake,
        queue_output=queue_output,
        annotation_output_dir=tmp_path / "pack",
        ocr_result_dir=tmp_path / "ocr_results",
        base_dir=tmp_path,
        copy_to=tmp_path / "real_samples",
        execute=False,
    )

    assert report["readyToExecute"] is True
    assert report["summary"]["plannedSteps"] == 2
    assert report["summary"]["executedSteps"] == 0
    assert not queue_output.exists()


def test_ocr_100_collection_intake_pipeline_executes_ingest_and_pack_when_ready(tmp_path: Path) -> None:
    intake = make_intake(tmp_path)
    sample_dir = intake / "samples" / "piping_table_profile"
    (sample_dir / "piping.pdf").write_bytes(b"%PDF-1.4\nsample\n")
    queue_output = tmp_path / "queue.json"
    pack_dir = tmp_path / "pack"

    report = run_collection_pipeline(
        intake,
        queue_output=queue_output,
        annotation_output_dir=pack_dir,
        ocr_result_dir=tmp_path / "ocr_results",
        base_dir=tmp_path,
        copy_to=tmp_path / "real_samples",
        execute=True,
        render_previews=False,
        run_prelabel=False,
    )

    queue = json.loads(queue_output.read_text(encoding="utf-8"))
    tasks = json.loads((pack_dir / "annotation_tasks.json").read_text(encoding="utf-8"))

    assert report["readyToExecute"] is True
    assert [step["step"] for step in report["executedSteps"]] == ["ingest", "annotation_pack"]
    assert queue["summary"]["cases"] == 1
    assert tasks["summary"]["tasks"] == 1
