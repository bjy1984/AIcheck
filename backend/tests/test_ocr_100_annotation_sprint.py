from __future__ import annotations

import json
from pathlib import Path

from scripts.ocr_100_annotation_sprint import (
    annotation_sprint_csv,
    annotation_sprint_markdown,
    build_annotation_sprint_plan,
)


def test_ocr_100_annotation_sprint_prioritizes_reviewable_machine_suggestions(tmp_path: Path) -> None:
    tasks = tmp_path / "prelabelled_tasks.json"
    tasks.write_text(
        json.dumps(
            {
                "tasks": [
                    {
                        "taskId": "label-ready-ish",
                        "caseId": "real-piping-001",
                        "scenario": "piping_table_profile",
                        "profileId": "piping_characteristic_list_v1",
                        "documentType": "engineering_table_photo",
                        "collectionStatus": "needs_labeling",
                        "sourcePath": "Scan/IMG_6509.heic",
                        "previewPaths": ["previews/real-piping-001_p1.png"],
                        "expectedTemplate": {
                            "fields": [{"fieldCode": "pipe_no", "value": "replace-with-label", "bbox": [0, 0, 0, 0]}],
                            "tables": [{"businessSchema": "piping_characteristic_table", "bbox": [0, 0, 0, 0]}],
                        },
                        "suggestedExpected": {
                            "qualityStatus": "auto_usable",
                            "minEvidenceCompleteness": 1.0,
                            "fields": [{"fieldCode": "pipe_no", "value": "PL8301", "bbox": [10, 10, 100, 30]}],
                            "tables": [{"businessSchema": "piping_characteristic_table", "bbox": [10, 40, 300, 200]}],
                            "seals": [{"sealType": "design_license_seal", "nameContains": "压力管道", "bbox": [200, 210, 320, 320]}],
                        },
                    },
                    {
                        "taskId": "label-empty",
                        "caseId": "real-ndt-001",
                        "scenario": "ndt_rt_profile",
                        "profileId": "ndt_rt_report_v1",
                        "documentType": "ndt_report",
                        "collectionStatus": "needs_labeling",
                        "sourcePath": "Scan/20260623105636.pdf",
                        "expectedTemplate": {
                            "fields": [{"fieldCode": "report_no", "value": "replace-with-label", "bbox": [0, 0, 0, 0]}],
                            "tables": [{"businessSchema": "weld_detection_result_table", "bbox": [0, 0, 0, 0]}],
                        },
                        "suggestedExpected": {"qualityStatus": "failed", "minEvidenceCompleteness": 0.0},
                    },
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    plan = build_annotation_sprint_plan(tasks, limit=2)

    assert plan["summary"]["tasks"] == 2
    assert plan["summary"]["readyForEval"] == 0
    assert plan["summary"]["scenarioTargetGaps"]["piping_table_profile"] == 12
    assert plan["summary"]["scenarioTargetGaps"]["ndt_rt_profile"] == 10
    assert plan["workItems"][0]["caseId"] == "real-piping-001"
    assert plan["workItems"][0]["suggestedCounts"] == {"fields": 1, "tables": 1, "seals": 1, "diagnostics": 0}
    assert plan["workItems"][0]["suggestedPositiveEvidenceCounts"] == {"fields": 1, "tables": 1, "seals": 1}
    assert "Review suggestedExpected" in " ".join(plan["workItems"][0]["humanActions"])
    assert "missing_human_label" in plan["workItems"][0]["blockers"]


def test_ocr_100_annotation_sprint_exports_markdown_and_csv(tmp_path: Path) -> None:
    tasks = tmp_path / "labeled_tasks.json"
    tasks.write_text(
        json.dumps(
            {
                "tasks": [
                    {
                        "taskId": "label-1",
                        "caseId": "case-1",
                        "scenario": "seal_text_profile",
                        "collectionStatus": "needs_labeling",
                        "sourcePath": "Scan/seal.png",
                        "suggestedExpected": {
                            "seals": [{"nameContains": "公司", "bbox": [1, 1, 10, 10]}],
                        },
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    plan = build_annotation_sprint_plan(tasks, limit=1)

    markdown = annotation_sprint_markdown(plan)
    csv_text = annotation_sprint_csv(plan)

    assert "# OCR 100 Annotation Sprint" in markdown
    assert "seal_text_profile" in markdown
    assert "case-1" in csv_text
    assert "missing_human_label" in csv_text
