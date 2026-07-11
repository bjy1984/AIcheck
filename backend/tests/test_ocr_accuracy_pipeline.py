from __future__ import annotations

from pathlib import Path

from PIL import Image

from apps.ocr_service.profiles import profile_for
from apps.worker.celery_app import celery_app
from libs.db.repository import InMemoryRepository
from libs.ocr_accuracy_pipeline import (
    PIPELINE_STAGES,
    build_batch_prior,
    initial_stage_records,
    merge_batch_outputs,
    page_batches,
    pipeline_enabled,
    pipeline_mode,
    pipeline_run_key,
    qwen_messages,
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
    repository.mark_ocr_pipeline_stage(run, "prepare", "running")
    assert run["status"] == "running"
    assert repository.ocr_pipeline_stages(run["id"])[0]["attempt"] == 1


def test_celery_routes_cpu_and_remote_work_are_isolated() -> None:
    routes = celery_app.conf.task_routes

    assert routes["apps.worker.tasks.parse_document"]["queue"] == "cpu.heavy"
    assert routes["apps.worker.tasks.embed_knowledge"]["queue"] == "cpu.heavy"
    assert routes["apps.worker.tasks.ocr_pipeline_qwen_extract"]["queue"] == "llm.remote"
    assert routes["apps.worker.tasks.ocr_pipeline_finalize"]["queue"] == "business.light"
