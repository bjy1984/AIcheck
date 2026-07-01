from __future__ import annotations

import json
from pathlib import Path

from scripts.ocr_100_annotation_sprint import (
    annotation_sprint_csv,
    annotation_sprint_markdown,
    build_annotation_sprint_plan,
    write_annotation_workbook,
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
    assert plan["workItems"][0]["draftSource"] == "suggestedExpected"
    assert plan["workItems"][0]["labelJsonDraft"]["expected"]["fields"][0]["value"] == "PL8301"
    assert plan["workItems"][0]["labelJsonDraft"]["expected"]["review"]["requiresHumanConfirmation"] is True
    assert plan["workItems"][1]["draftSource"] == "suggestedExpected"
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
    assert "draftSource" in csv_text


def test_ocr_100_annotation_sprint_writes_human_workbook_drafts(tmp_path: Path) -> None:
    tasks = tmp_path / "prelabelled_tasks.json"
    tasks.write_text(
        json.dumps(
            {
                "tasks": [
                    {
                        "taskId": "label-1",
                        "caseId": "case/1",
                        "scenario": "seal_text_profile",
                        "profileId": "seal_text_v1",
                        "documentType": "sealed_document",
                        "collectionStatus": "needs_labeling",
                        "sourcePath": "Scan/seal.png",
                        "previewPaths": ["previews/case-1.png"],
                        "suggestedExpected": {
                            "qualityStatus": "needs_human_review",
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

    manifest = write_annotation_workbook(plan, tmp_path / "workbook")

    assert manifest["schemaVersion"] == "aicheck-ocr-100-annotation-workbook-v1"
    assert manifest["draftCount"] == 1
    draft_path = Path(manifest["drafts"][0]["path"])
    draft = json.loads(draft_path.read_text(encoding="utf-8"))
    assert draft_path.name == "case_1.expected.json"
    assert draft["caseId"] == "case/1"
    assert draft["expected"]["seals"][0]["nameContains"] == "公司"
    assert draft["expected"]["review"]["source"] == "human_workbook_draft"
    assert draft["expected"]["review"]["requiresHumanConfirmation"] is True
    readme = (tmp_path / "workbook" / "README.md").read_text(encoding="utf-8")
    assert "machine workbook drafts are not gold labels" in readme
    assert "case/1" in readme
