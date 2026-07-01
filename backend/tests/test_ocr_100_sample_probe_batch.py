from __future__ import annotations

import json
from pathlib import Path

from scripts.ocr_100_sample_probe_batch import build_probe_batch_report, resolve_case_source


def test_ocr_100_sample_probe_batch_builds_scorecard_ready_items(tmp_path: Path) -> None:
    scan = tmp_path / "Scan"
    scan.mkdir()
    sample = scan / "IMG_6509.png"
    sample.write_bytes(b"fake-image")
    queue = tmp_path / "queue.json"
    queue.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "caseId": "real-piping-001",
                        "scenario": "piping_table_profile",
                        "profileId": "piping_characteristic_list_v1",
                        "documentType": "engineering_table_photo",
                        "source": {"path": "Scan/IMG_6509.png", "fileName": "IMG_6509.png"},
                    },
                    {
                        "caseId": "real-quality-001",
                        "scenario": "quality_certificate_profile",
                        "profileId": "quality_certificate_v1",
                        "documentType": "quality_certificate",
                        "source": {"path": "Scan/missing.png", "fileName": "missing.png"},
                    },
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    def fake_parse(source: Path, case: dict, options: dict) -> dict:
        assert source == sample
        assert options == {"disableResultCache": True}
        return {
            "status": "success",
            "parseResultId": "parse-1",
            "profileId": case["profileId"],
            "documentType": case["documentType"],
            "fragments": [{"text": "压力管道设计许可", "confidence": 0.9, "bbox": [1, 1, 10, 10]}],
            "fields": [
                {"fieldCode": code, "fieldValue": code, "confidence": 0.9, "bbox": [1, 1, 10, 10]}
                for code in ["company_name", "project_name", "document_title", "drawing_no", "design_phase"]
            ],
            "tables": [
                {
                    "tableId": "t1",
                    "sourceEngine": "opencv_grid_text_aligned",
                    "structureConfidence": 0.9,
                    "bbox": [1, 1, 100, 100],
                    "businessRows": [{"row": i} for i in range(5)],
                }
            ],
            "seals": [
                {
                    "sealId": "seal-1",
                    "sealType": "design_license_seal",
                    "sealName": "压力管道设计许可",
                    "sourceEngine": "fragment_seal_text_fusion",
                    "ocrConfidence": 0.9,
                    "bbox": [1, 1, 100, 100],
                    "qualityFlags": ["fragment_seal_text"],
                }
            ],
            "quality": {
                "status": "auto_usable",
                "evidenceCompleteness": 1.0,
                "missingExpectedSealTypes": [],
            },
            "engineRuns": [],
        }

    report = build_probe_batch_report(
        queue,
        base_dir=tmp_path,
        case_ids={"real-piping-001"},
        options={"disableResultCache": True},
        scorecard_sample_gate=True,
        parse_runner=fake_parse,
    )

    assert report["summary"]["cases"] == 1
    assert report["summary"]["gatePassed"] is True
    assert report["summary"]["scenarioCounts"] == {"piping_table_profile": 1}
    assert report["items"][0]["caseId"] == "real-piping-001"
    assert report["items"][0]["gatePassed"] is True
    assert report["items"][0]["fields"] == 5
    assert report["items"][0]["formalTables"] == 1
    assert report["items"][0]["businessRows"] == 5
    assert report["items"][0]["readableSeals"] == 1
    assert report["items"][0]["fragmentSeals"] == 1


def test_ocr_100_sample_probe_batch_reports_gate_failures(tmp_path: Path) -> None:
    sample = tmp_path / "sample.png"
    sample.write_bytes(b"fake")
    queue = tmp_path / "queue.json"
    queue.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "caseId": "case-1",
                        "scenario": "piping_table_profile",
                        "profileId": "piping_characteristic_list_v1",
                        "documentType": "engineering_table_photo",
                        "source": {"path": "sample.png"},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    report = build_probe_batch_report(
        queue,
        base_dir=tmp_path,
        scorecard_sample_gate=True,
        parse_runner=lambda source, case, options: {
            "status": "success",
            "fragments": [{"text": "only text", "bbox": [1, 1, 2, 2]}],
            "fields": [],
            "tables": [],
            "seals": [],
            "quality": {"status": "needs_human_review", "evidenceCompleteness": 0.5},
            "engineRuns": [],
        },
    )

    assert report["summary"]["gatePassed"] is False
    assert report["summary"]["failed"] == 1
    assert report["summary"]["gateFailureCounts"]["FIELDS_BELOW_MIN"] == 1
    assert report["items"][0]["gatePassed"] is False


def test_ocr_100_sample_probe_batch_filters_and_writes_per_case_summaries(tmp_path: Path) -> None:
    queue_dir = tmp_path / "queue"
    sample_dir = queue_dir / "samples"
    output_dir = tmp_path / "summaries"
    sample_dir.mkdir(parents=True)
    selected = sample_dir / "selected.png"
    skipped = sample_dir / "skipped.png"
    selected.write_bytes(b"selected")
    skipped.write_bytes(b"skipped")
    queue = queue_dir / "queue.json"
    queue.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "caseId": "selected/case",
                        "scenario": "piping_table_profile",
                        "profileId": "piping_characteristic_list_v1",
                        "documentType": "engineering_table_photo",
                        "source": {"path": "samples/selected.png"},
                    },
                    {
                        "caseId": "skipped-case",
                        "scenario": "quality_certificate_profile",
                        "profileId": "quality_certificate_v1",
                        "documentType": "quality_certificate",
                        "source": {"path": "samples/skipped.png"},
                    },
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    def fake_parse(source: Path, case: dict, options: dict) -> dict:
        assert source == selected
        return {
            "status": "success",
            "parseResultId": "parse-selected",
            "profileId": case["profileId"],
            "documentType": case["documentType"],
            "fragments": [{"text": "ok", "confidence": 0.9, "bbox": [1, 1, 2, 2]}],
            "fields": [],
            "tables": [],
            "seals": [],
            "quality": {"status": "needs_human_review"},
            "engineRuns": [],
        }

    report = build_probe_batch_report(
        queue,
        base_dir=tmp_path / "missing-base",
        output_dir=output_dir,
        scenarios={"piping_table_profile"},
        parse_runner=fake_parse,
    )

    assert resolve_case_source(
        {"source": {"path": "samples/selected.png"}},
        queue_path=queue,
        base_dir=tmp_path / "missing-base",
    ) == selected
    assert report["summary"]["cases"] == 1
    assert report["summary"]["outputDir"] == str(output_dir)
    assert report["items"][0]["caseId"] == "selected/case"
    assert (output_dir / "selected-case.json").exists()
