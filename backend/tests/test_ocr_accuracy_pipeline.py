from __future__ import annotations

from pathlib import Path

from PIL import Image

from apps.ocr_service.profiles import profile_for
from apps.worker.celery_app import celery_app
from libs.db.repository import InMemoryRepository
from libs.ocr_accuracy_pipeline import (
    PIPELINE_STAGES,
    build_batch_prior,
    build_batch_priors,
    initial_stage_records,
    infer_preliminary_profile_id,
    merge_batch_outputs,
    normalize_qwen_structured_output,
    page_batches,
    pipeline_enabled,
    pipeline_mode,
    pipeline_run_key,
    profile_from_ocr_result,
    qwen_messages,
    required_field_blockers,
    stage_engine_summary,
    validated_ocr_fields,
    validate_batch_output,
)


def sample_parse_result() -> dict:
    return {
        "parseResultId": "PARSE-1",
        "status": "success",
        "pages": [{"pageNo": 1, "width": 1000, "height": 1400}],
        "fields": [
            {
                "fieldCode": "report_no",
                "fieldName": "报告编号",
                "fieldValue": "RT-2026-001",
                "pageNo": 1,
                "bbox": [100, 120, 300, 170],
                "confidence": 0.93,
                "sourceEngine": "paddle_ocr_subprocess",
            }
        ],
        "fragments": [
            {
                "id": "FRAG-1",
                "text": "报告编号 RT-2026-001",
                "pageNo": 1,
                "bbox": [80, 100, 360, 190],
                "confidence": 0.91,
                "sourceEngine": "paddle_ocr_subprocess",
            }
        ],
        "tables": [],
        "seals": [],
        "layoutBlocks": [],
    }


def test_pipeline_defaults_to_shadow_and_profile_allowlist(monkeypatch) -> None:
    monkeypatch.delenv("AICHECK_OCR_PIPELINE_MODE", raising=False)
    monkeypatch.delenv("AICHECK_OCR_PIPELINE_PROFILE_ALLOWLIST", raising=False)

    assert pipeline_mode() == "shadow"
    assert pipeline_enabled("ndt_rt_report_v1") is True
    assert pipeline_enabled("generic_document_v1") is False
    assert pipeline_enabled("ndt_rt_report_v1", source_type="standard") is False


def test_filename_preliminary_profile_routing_is_conservative() -> None:
    assert infer_preliminary_profile_id("钢管质量证明书.pdf", None, None) == "quality_certificate_v1"
    assert infer_preliminary_profile_id("RT检测报告R2.pdf", None, None) == "ndt_rt_report_v1"
    assert infer_preliminary_profile_id("IMG_6514.png", None, None) == "generic_document_v1"
    assert (
        infer_preliminary_profile_id("RT检测报告.pdf", "engineering_drawing_list_v1", None)
        == "engineering_drawing_list_v1"
    )


def test_ocr_detected_profile_overrides_generic_fallback() -> None:
    fallback = profile_for("generic_document_v1")
    result = {
        "profileId": "piping_characteristic_list_v1",
        "documentType": "piping_characteristic_list",
        "metadata": {"detectedProfileId": "piping_characteristic_list_v1"},
    }

    routed = profile_from_ocr_result(result, fallback)

    assert routed["profileId"] == "piping_characteristic_list_v1"


def test_pipeline_stage_records_are_queued_and_ordered() -> None:
    stages = initial_stage_records("RUN-1", now="2026-07-11T00:00:00+00:00")

    assert [item["stage"] for item in stages] == [item[0] for item in PIPELINE_STAGES]
    assert {item["status"] for item in stages} == {"queued"}
    assert stages[-1]["progress"] == 100


def test_page_batches_never_exceed_four_pages(monkeypatch) -> None:
    monkeypatch.setenv("AICHECK_OCR_QWEN_MAX_PAGES", "60")
    result = {"pages": [{"pageNo": value} for value in range(1, 11)]}

    batches = page_batches(result)

    assert batches == [[1, 2, 3, 4], [5, 6, 7, 8], [9, 10]]


def test_grounded_qwen_field_requires_real_candidate() -> None:
    profile = profile_for("ndt_rt_report_v1", "ndt_report")
    prior = build_batch_prior(sample_parse_result(), profile, [1])
    candidate = next(
        item
        for item in prior["compact"]["candidates"]
        if item.get("semanticKey") == "report_no" and item.get("formalEvidenceEligible")
    )
    output = {
        "fields": {
            "report_no": {
                "value": "RT-2026-001",
                "sourceCandidateIds": [candidate["candidateId"]],
            }
        },
        "tables": {},
        "seals": [],
    }

    validation = validate_batch_output(output, prior["compact"])
    candidates = {item["candidateId"]: item for item in prior["compact"]["candidates"]}
    fields = validated_ocr_fields(validation["structuredOutput"], profile, candidates)

    assert validation["validation"]["invalidCandidateIdCount"] == 0
    assert fields[0]["fieldCode"] == "report_no"
    assert fields[0]["bbox"] == candidate["bbox"]
    assert fields[0]["reviewStatus"] == "待确认"


def test_invented_candidate_never_becomes_ocr_field() -> None:
    profile = profile_for("ndt_rt_report_v1", "ndt_report")
    prior = build_batch_prior(sample_parse_result(), profile, [1])
    output = {
        "fields": {
            "report_no": {
                "value": "RT-2026-001",
                "sourceCandidateIds": ["EP2-FIELD-INVENTED"],
            }
        }
    }

    validation = validate_batch_output(output, prior["compact"])
    candidates = {item["candidateId"]: item for item in prior["compact"]["candidates"]}

    assert validation["validation"]["invalidCandidateIdCount"] == 1
    assert validated_ocr_fields(validation["structuredOutput"], profile, candidates) == []


def test_qwen_messages_include_original_page_and_candidate_contract(tmp_path: Path) -> None:
    image_path = tmp_path / "page.png"
    Image.new("RGB", (100, 140), "white").save(image_path)
    profile = profile_for("ndt_rt_report_v1", "ndt_report")
    prior = build_batch_prior(sample_parse_result(), profile, [1])

    messages = qwen_messages({1: image_path}, [], profile, prior["compact"])
    content = messages[-1]["content"]

    assert any(item.get("type") == "image_url" for item in content)
    prompt = "\n".join(str(item.get("text") or "") for item in content)
    assert "sourceCandidateIds" in prompt
    assert "禁止自行生成 bbox" in prompt


def test_merge_batch_outputs_keeps_validated_first_value() -> None:
    first = {
        "fields": {"report_no": {"value": "RT-001", "attributionStatus": "validated"}},
        "tables": {},
        "seals": [],
    }
    second = {
        "fields": {"report_no": {"value": "RT-00I", "attributionStatus": "validated"}},
        "tables": {},
        "seals": [],
    }

    merged = merge_batch_outputs([first, second])

    assert merged["fields"]["report_no"]["value"] == "RT-001"
    assert merged["conflicts"][0]["fieldCode"] == "report_no"


def test_qwen_top_level_profile_fields_are_normalized_before_validation() -> None:
    profile = profile_for("ndt_rt_report_v1", "ndt_report")
    raw = {
        "report_no": {"value": "RT-2026-001", "sourceCandidateIds": ["EP2-FIELD-1"]},
        "ndt_rt_report_table": [{"cells": {}, "sourceCandidateIds": []}],
        "seal": [{"value": "检测专用章", "sourceCandidateIds": ["EP2-SEAL-1"]}],
    }

    normalized = normalize_qwen_structured_output(raw, profile)

    assert normalized["fields"]["report_no"]["value"] == "RT-2026-001"
    assert normalized["seals"][0]["value"] == "检测专用章"


def test_required_field_blockers_accept_structured_list_values() -> None:
    profile = {"requiredFields": ["drawing_numbers"]}
    parse_result = {
        "fields": [
            {
                "fieldCode": "drawing_numbers",
                "fieldValue": ["QX-01", "QX-02"],
                "bbox": [10, 10, 100, 40],
            }
        ]
    }

    assert required_field_blockers(parse_result, profile) == []


def test_repository_pipeline_run_is_queued_until_worker_stage_starts() -> None:
    repository = InMemoryRepository()
    run = repository.create_or_resume_ocr_pipeline_run(
        run_key=pipeline_run_key("DOC-1", "VER-1", "documents/VER-1", "ndt_rt_report_v1"),
        document_id="DOC-1",
        version_id="VER-1",
        storage_key="documents/VER-1",
        storage_bucket="documents",
        file_name="report.pdf",
        profile_id="ndt_rt_report_v1",
        document_type="ndt_report",
        mode="shadow",
        pipeline_version="test@1",
    )

    assert run["status"] == "queued"
    assert repository.ocr_pipeline_stages(run["id"])[0]["documentId"] == "DOC-1"
    assert repository.ocr_pipeline_stages(run["id"])[0]["documentVersionId"] == "VER-1"
    repository.mark_ocr_pipeline_stage(run, "prepare", "running")
    assert run["status"] == "running"
    assert repository.ocr_pipeline_stages(run["id"])[0]["attempt"] == 1


def test_repository_repairs_missing_stage_records_when_failed_run_is_resumed() -> None:
    repository = InMemoryRepository()
    run_key = pipeline_run_key("DOC-1", "VER-1", "documents/VER-1", "ndt_rt_report_v1")
    run = repository.create_or_resume_ocr_pipeline_run(
        run_key=run_key,
        document_id="DOC-1",
        version_id="VER-1",
        storage_key="documents/VER-1",
        storage_bucket="documents",
        file_name="report.pdf",
        profile_id="ndt_rt_report_v1",
        document_type="ndt_report",
        mode="shadow",
        pipeline_version="test@1",
    )
    run["status"] = "failed"
    repository.state["ocr_stage_runs"] = []

    resumed = repository.create_or_resume_ocr_pipeline_run(
        run_key=run_key,
        document_id="DOC-1",
        version_id="VER-1",
        storage_key="documents/VER-1",
        storage_bucket="documents",
        file_name="report.pdf",
        profile_id="ndt_rt_report_v1",
        document_type="ndt_report",
        mode="shadow",
        pipeline_version="test@1",
    )

    assert resumed["status"] == "queued"
    assert len(repository.ocr_pipeline_stages(resumed["id"])) == len(PIPELINE_STAGES)


def test_celery_routes_cpu_and_remote_work_are_isolated() -> None:
    routes = celery_app.conf.task_routes

    assert routes["apps.worker.tasks.parse_document"]["queue"] == "ocr.parse_document"
    assert routes["apps.worker.tasks.ocr_pipeline_structure_scan"]["queue"] == "cpu.heavy"
    assert routes["apps.worker.tasks.ocr_pipeline_seal_scan"]["queue"] == "cpu.heavy"
    assert routes["apps.worker.tasks.ocr_pipeline_evidence_fusion"]["queue"] == "business.light"
    assert routes["apps.worker.tasks.embed_knowledge"]["queue"] == "cpu.heavy"
    assert routes["apps.worker.tasks.ocr_pipeline_official_extract"]["queue"] == "ocr.remote"
    assert routes["apps.worker.tasks.ocr_pipeline_qwen_extract"]["queue"] == "llm.remote"
    assert routes["apps.worker.tasks.ocr_pipeline_finalize"]["queue"] == "business.light"


def drawing_list_parse_result(*, shared_row_bbox: bool = False) -> dict:
    cells = []
    rows = [
        ("1", "工艺图纸目录", "QX201903S-13-Y-00"),
        ("2", "工艺设计说明书", "QX201903S-13-Y-01"),
    ]
    for row_index, values in enumerate(rows):
        for col_index, value in enumerate(values):
            bbox = [100, 200 + row_index * 40, 700, 230 + row_index * 40]
            if not shared_row_bbox:
                bbox = [100 + col_index * 200, 200 + row_index * 40, 280 + col_index * 200, 230 + row_index * 40]
            cells.append(
                {
                    "cellId": f"CELL-{row_index}-{col_index}",
                    "row": row_index,
                    "col": col_index,
                    "text": value,
                    "pageNo": 1,
                    "bbox": bbox,
                    "confidence": 0.99,
                    "sourceEngine": "pp_structure_v3",
                }
            )
    return {
        "parseResultId": "PARSE-DRAWING-LIST",
        "status": "success",
        "pages": [{"pageNo": 1, "width": 1000, "height": 1400}],
        "fields": [],
        "fragments": [],
        "seals": [],
        "layoutBlocks": [],
        "tables": [
            {
                "tableId": "DRAWING-LIST",
                "businessSchema": "engineering_drawing_list_rows_v1",
                "pageNo": 1,
                "bbox": [80, 180, 740, 320],
                "sourceEngine": "pp_structure_v3",
                "structureConfidence": 0.98,
                "cells": cells,
            },
            {
                "tableId": "TITLE-BLOCK",
                "businessSchema": "engineering_drawing_title_block_v1",
                "pageNo": 1,
                "bbox": [20, 20, 900, 170],
                "sourceEngine": "heuristic_table_from_fragments",
                "cells": [{"row": 0, "col": 0, "text": "标题栏", "bbox": [20, 20, 900, 170]}],
            },
        ],
    }


def test_stage_engine_summary_does_not_treat_skipped_engine_as_executed() -> None:
    summary = stage_engine_summary(
        {
            "engineRuns": [
                {"engine": "pp_structure_v3", "status": "skipped", "reason": "fast_first"},
                {"engine": "opencv_table_grid_subprocess", "status": "success", "durationMs": 12},
            ]
        },
        {"pp_structure_v3", "opencv_table_grid_subprocess"},
    )

    assert summary["engineAttempted"] == ["opencv_table_grid_subprocess"]
    assert summary["engineExecuted"] == ["opencv_table_grid_subprocess"]
    assert summary["skipReasons"] == ["fast_first"]


def test_drawing_list_prior_excludes_title_block_and_marks_row_bbox_only() -> None:
    profile = profile_for("engineering_drawing_list_v1")
    priors = build_batch_priors(drawing_list_parse_result(shared_row_bbox=True), profile, [1])
    candidates = priors[0]["compact"]["candidates"]
    table_cells = [item for item in candidates if item.get("candidateType") == "table_cell"]

    assert table_cells
    assert {item.get("tableSchema") for item in table_cells} == {"engineering_drawing_list_rows_v1"}
    assert {item.get("cellBboxQuality") for item in table_cells} == {"row_bbox_only"}
    assert not any(item.get("formalEvidenceEligible") for item in table_cells)


def test_prior_keeps_only_highest_quality_overlapping_table_representation() -> None:
    profile = profile_for("engineering_drawing_list_v1")
    parse_result = drawing_list_parse_result()
    canonical = parse_result["tables"][0]
    parse_result["tables"].append(
        {
            **canonical,
            "tableId": "DRAWING-LIST-HEURISTIC",
            "sourceEngine": "heuristic_table_from_fragments",
            "structureConfidence": 0.7,
            "cells": [dict(item) for item in canonical["cells"]],
        }
    )

    candidates = build_batch_priors(parse_result, profile, [1])[0]["compact"]["candidates"]
    table_ids = {
        item.get("tableId")
        for item in candidates
        if item.get("candidateType") == "table_cell"
    }

    assert table_ids == {"DRAWING-LIST"}


def test_table_cell_wrong_candidate_is_repaired_by_row_and_column() -> None:
    profile = profile_for("engineering_drawing_list_v1")
    compact = build_batch_priors(drawing_list_parse_result(), profile, [1])[0]["compact"]
    row_zero = [item for item in compact["candidates"] if item.get("candidateType") == "table_cell" and item.get("row") == 0]
    wrong = next(item for item in row_zero if item.get("columnKey") == "drawing_no")
    correct = next(item for item in row_zero if item.get("columnKey") == "drawing_name")
    output = {
        "tables": {
            "engineering_drawing_list_rows_v1": [
                {
                    "tableId": "DRAWING-LIST",
                    "rowKey": "0",
                    "cells": {
                        "drawing_name": {
                            "value": "工艺图纸目录",
                            "sourceCandidateIds": [wrong["candidateId"]],
                        }
                    }
                }
            ]
        }
    }

    validation = validate_batch_output(output, compact)
    item = validation["structuredOutput"]["tables"]["engineering_drawing_list_rows_v1"][0]["cells"]["drawing_name"]

    assert item["sourceCandidateIds"] == [correct["candidateId"]]
    assert item["attributionStatus"] == "validated"
    assert item["attributionRepair"] == "deterministic_row_column_repair"
    assert validation["validation"]["candidateRepairCount"] == 1


def test_table_cell_candidate_from_another_row_is_rejected() -> None:
    profile = profile_for("engineering_drawing_list_v1")
    compact = build_batch_priors(drawing_list_parse_result(), profile, [1])[0]["compact"]
    wrong_row = next(
        item
        for item in compact["candidates"]
        if item.get("candidateType") == "table_cell"
        and item.get("row") == 1
        and item.get("columnKey") == "drawing_no"
    )
    output = {
        "tables": {
            "engineering_drawing_list_rows_v1": [
                {
                    "tableId": "DRAWING-LIST",
                    "rowKey": "0",
                    "cells": {
                        "drawing_no": {
                            "value": wrong_row["text"],
                            "sourceCandidateIds": [wrong_row["candidateId"]],
                        }
                    },
                }
            ]
        }
    }

    validation = validate_batch_output(output, compact)
    item = validation["structuredOutput"]["tables"]["engineering_drawing_list_rows_v1"][0]["cells"][
        "drawing_no"
    ]

    assert item["sourceCandidateIds"] == []
    assert item["attributionStatus"] == "dropped_unsupported"
    assert item["value"] is None


def test_table_cell_scalar_without_candidate_is_dropped_with_diagnostics() -> None:
    profile = profile_for("engineering_drawing_list_v1")
    compact = build_batch_priors(drawing_list_parse_result(), profile, [1])[0]["compact"]
    output = {
        "tables": {
            "engineering_drawing_list_rows_v1": [
                {
                    "tableId": "DRAWING-LIST",
                    "rowKey": "0",
                    "cells": {"drawing_name": "工艺图纸目录"},
                }
            ]
        }
    }

    validation = validate_batch_output(output, compact)
    item = validation["structuredOutput"]["tables"]["engineering_drawing_list_rows_v1"][0]["cells"][
        "drawing_name"
    ]

    assert item["sourceCandidateIds"] == []
    assert item["value"] is None
    assert item["attributionStatus"] == "dropped_unsupported"
    assert validation["validation"]["statusCounts"]["unsupported"] == 0
    assert validation["validation"]["statusCounts"]["dropped_unsupported"] == 1
    assert validation["validation"]["droppedUnsupportedAttributionCount"] == 1
    assert validation["validation"]["items"][0]["observedValue"] == "工艺图纸目录"
