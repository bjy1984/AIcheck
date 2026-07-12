from __future__ import annotations

import json
from pathlib import Path

import httpx
import yaml
from fastapi.testclient import TestClient

from apps.api.main import app
from apps.ocr_service.fusion import fuse_parse_result
from apps.ocr_service.profiles import profile_for, validate_profiles
from apps.ocr_service.service import sparse_table_remediation_targets, split_bbox_along_long_axis
from apps.worker import tasks
from libs.db.repository import repo
from libs.document_ai_shadow import (
    build_evidence_prior,
    document_ai_shadow_enabled,
    estimate_json_tokens,
    sparse_table_diagnostics,
    stable_payload_hash,
    table_retry_tiles,
    validate_shadow_attribution,
)
from libs.integrations.document_ai_client import DocumentAiClient


client = TestClient(app)


def setup_function() -> None:
    repo.reset()


def sample_parse_result() -> dict:
    return {
        "id": "PARSE-SHADOW-001",
        "parseResultId": "PARSE-SHADOW-001",
        "documentId": "DOC-SHADOW-001",
        "documentVersionId": "DV-SHADOW-001",
        "status": "success",
        "pages": [
            {"pageNo": page_no, "width": 1000, "height": 1400, "imageHash": f"page-{page_no}"}
            for page_no in range(1, 9)
        ],
        "fields": [
            {
                "fieldId": "FIELD-REPORT",
                "fieldCode": "report_no",
                "fieldValue": "RT-2026-001",
                "pageNo": 7,
                "bbox": [100, 100, 300, 140],
                "confidence": 0.96,
                "sourceEngine": "paddle_ocr_subprocess",
            },
            {
                "fieldId": "FIELD-PROJECT",
                "fieldCode": "project_name",
                "fieldValue": "珠海工程",
                "pageNo": 1,
                "bbox": [100, 160, 400, 210],
                "confidence": 0.94,
                "sourceEngine": "paddle_ocr_subprocess",
            },
        ],
        "fragments": [
            {
                "fragmentId": f"FRAG-{page_no}-{index}",
                "text": f"第{page_no}页检测资料文本片段{index} " + ("内容" * 20),
                "pageNo": page_no,
                "bbox": [20, 40 + index * 18, 800, 55 + index * 18],
                "confidence": 0.9,
                "sourceEngine": "paddle_ocr_subprocess",
            }
            for page_no in range(1, 9)
            for index in range(12)
        ],
        "tables": [
            {
                "tableId": "TABLE-RT",
                "businessSchema": "weld_detection_result_table",
                "pageNo": 2,
                "bbox": [50, 200, 950, 900],
                "structureConfidence": 0.92,
                "sourceEngine": "pp_structure_v3",
                "cells": [
                    {
                        "cellId": "CELL-PROJECT-LABEL",
                        "text": "项目名称",
                        "row": 1,
                        "col": 0,
                        "bbox": [60, 220, 190, 260],
                        "pageNo": 2,
                        "confidence": 0.95,
                    },
                    {
                        "cellId": "CELL-PROJECT-VALUE",
                        "text": "珠海工程",
                        "row": 1,
                        "col": 1,
                        "bbox": [190, 220, 500, 260],
                        "pageNo": 2,
                        "confidence": 0.95,
                    },
                    {
                        "cellId": "CELL-LEVEL",
                        "text": "技术等级 AB",
                        "row": 2,
                        "col": 0,
                        "bbox": [60, 270, 260, 310],
                        "pageNo": 2,
                        "confidence": 0.93,
                    },
                    {
                        "cellId": "CELL-RATIO",
                        "text": "检测比例 10%",
                        "row": 2,
                        "col": 1,
                        "bbox": [260, 270, 480, 310],
                        "pageNo": 2,
                        "confidence": 0.93,
                    },
                ],
            }
        ],
        "seals": [
            {
                "sealId": "SEAL-1",
                "sealType": "inspection_testing_seal",
                "sealName": "检测专用章",
                "pageNo": 8,
                "bbox": [700, 1000, 920, 1260],
                "ocrConfidence": 0.88,
                "sourceEngine": "paddlex_seal_recognition",
            }
        ],
        "layoutBlocks": [
            {
                "blockId": "BLOCK-1",
                "blockType": "table",
                "text": "表格区域",
                "pageNo": 2,
                "bbox": [40, 190, 960, 920],
                "confidence": 0.98,
                "sourceEngine": "paddleocr_vl_1_6",
            }
        ],
    }


def test_profiles_expose_shadow_contract_without_ambiguous_rt_field() -> None:
    assert validate_profiles() == []
    config = profile_for("ndt_rt_report_v1")["structuredExtraction"]
    assert config["mode"] == "shadow"
    assert config["maxCandidates"] == 64
    assert config["maxPriorTokens"] == 12000
    assert config["maxPages"] == 6
    assert "detection_ratio" in config["fields"]
    assert "detection_method" in profile_for("piping_characteristic_list_v1")["structuredExtraction"]["fields"]
    assert "technical_grade" in config["fields"]
    assert "evaluation_level" in config["fields"]
    assert "film_model" in config["fields"]
    assert "intensifying_screen_thickness" in config["fields"]
    assert "film_quality" not in config["fields"]


def test_shadow_queue_has_a_dedicated_single_concurrency_worker() -> None:
    compose_path = Path(__file__).resolve().parents[1] / "docker-compose.yml"
    services = yaml.safe_load(compose_path.read_text(encoding="utf-8"))["services"]
    primary_command = services["worker-service"]["command"]
    shadow_command = services["document-ai-shadow-worker-service"]["command"]

    assert "document-ai.shadow" not in primary_command
    assert "-Q document-ai.shadow" in shadow_command
    assert "--concurrency=1" in shadow_command


def test_evidence_prior_is_stable_and_enforces_candidate_page_and_token_budgets() -> None:
    parse_result = sample_parse_result()
    profile = profile_for("ndt_rt_report_v1")
    first = build_evidence_prior(parse_result, profile)
    second = build_evidence_prior(parse_result, profile)
    prior = first["compact"]

    assert first["compactPriorHash"] == second["compactPriorHash"]
    assert [item["candidateId"] for item in prior["candidates"]] == [
        item["candidateId"] for item in second["compact"]["candidates"]
    ]
    assert prior["candidateCount"] <= 64
    assert prior["estimatedTokenCount"] <= 12000
    assert estimate_json_tokens(prior) <= 12000
    assert len(prior["selectedPageNos"]) <= 6
    assert 7 in prior["selectedPageNos"]
    assert all(item["pageNo"] in prior["selectedPageNos"] for item in prior["candidates"])


def test_sparse_large_table_gets_deterministic_four_tile_retry_plan() -> None:
    result = {
        "pages": [{"pageNo": 1, "width": 1000, "height": 1000}],
        "tables": [
            {
                "tableId": "SPARSE",
                "pageNo": 1,
                "bbox": [50, 100, 950, 500],
                "cells": [{"text": "only"}],
            }
        ],
    }
    diagnostics = sparse_table_diagnostics(result)

    assert diagnostics[0]["code"] == "TABLE_CONTENT_SPARSE"
    assert diagnostics[0]["pageAreaRatio"] == 0.36
    assert diagnostics[0]["formalEvidenceEligible"] is False
    assert len(diagnostics[0]["retryPlan"]["tiles"]) == 4
    assert diagnostics[0]["retryPlan"]["tiles"] == table_retry_tiles([50, 100, 950, 500])


def test_baseline_quality_gate_blocks_sparse_large_table_and_builds_crop_targets() -> None:
    fused = fuse_parse_result(
        {
            "status": "success",
            "pages": [{"pageNo": 1, "width": 1000, "height": 1000}],
            "fields": [],
            "fragments": [],
            "seals": [],
            "tables": [
                {
                    "tableId": "SPARSE-BASELINE",
                    "businessSchema": "weld_detection_result_table",
                    "pageNo": 1,
                    "bbox": [50, 100, 950, 500],
                    "coordinateSystem": "rendered_pixels",
                    "structureConfidence": 0.95,
                    "sourceEngine": "pp_structure_v3",
                    "cells": [{"text": "only", "bbox": [60, 110, 120, 140]}],
                }
            ],
        },
        profile=profile_for("ndt_rt_report_v1"),
    )

    assert "TABLE_CONTENT_SPARSE" in fused["quality"]["reasons"]
    assert fused["formalEvidenceReady"] is False
    targets = sparse_table_remediation_targets(fused)
    assert len(targets) == 4
    assert all("table_content_sparse_tile" in target["qualityFlags"] for target in targets)
    assert [target["bbox"] for target in targets] == split_bbox_along_long_axis(
        [50, 100, 950, 500], max_tiles=4, overlap_ratio=0.1
    )


def test_attribution_removes_unknown_and_semantically_wrong_candidate_ids() -> None:
    prior = build_evidence_prior(sample_parse_result(), profile_for("ndt_rt_report_v1"))["compact"]
    by_semantic = {item.get("semanticKey"): item for item in prior["candidates"] if item.get("semanticKey")}
    output = {
        "fields": {
            "report_no": {
                "value": "RT-2026-001",
                "sourceCandidateIds": [by_semantic["project_name"]["candidateId"], "EP2-NOT-FOUND"],
            }
        }
    }

    validated = validate_shadow_attribution(output, prior)
    field = validated["structuredOutput"]["fields"]["report_no"]

    assert field["sourceCandidateIds"] == []
    assert field["rawSourceCandidateIds"][-1] == "EP2-NOT-FOUND"
    assert field["attributionStatus"] == "unsupported"
    assert field["advisoryOnly"] is True
    assert validated["formalEvidenceReady"] is False
    assert validated["validation"]["invalidCandidateIdCount"] == 1


def test_attribution_allows_only_same_table_same_row_composite_candidates() -> None:
    prior = build_evidence_prior(sample_parse_result(), profile_for("ndt_rt_report_v1"))["compact"]
    cells = {
        item.get("sourceId"): item
        for item in prior["candidates"]
        if item.get("candidateType") == "table_cell"
    }
    output = {
        "fields": {
            "project_name": {
                "value": "项目名称珠海工程",
                "sourceCandidateIds": [
                    cells["CELL-PROJECT-LABEL"]["candidateId"],
                    cells["CELL-PROJECT-VALUE"]["candidateId"],
                    cells["CELL-LEVEL"]["candidateId"],
                ],
            }
        }
    }

    validated = validate_shadow_attribution(output, prior)
    field = validated["structuredOutput"]["fields"]["project_name"]

    assert field["sourceCandidateIds"] == [
        cells["CELL-PROJECT-LABEL"]["candidateId"],
        cells["CELL-PROJECT-VALUE"]["candidateId"],
    ]
    assert field["evidenceBbox"] == [60.0, 220.0, 500.0, 260.0]
    assert field["evidencePageNo"] == 2
    assert field["attributionStatus"] == "validated"


def test_table_header_geometry_propagates_semantics_and_rejects_ambiguous_short_values() -> None:
    parse_result = {
        "pages": [{"pageNo": 1, "width": 1200, "height": 800}],
        "fields": [],
        "fragments": [],
        "seals": [],
        "tables": [
            {
                "tableId": "PIPE-TABLE",
                "pageNo": 1,
                "bbox": [10, 100, 1190, 700],
                "cells": [
                    {"cellId": "H-METHOD", "text": "检测方法", "row": 0, "col": 0, "bbox": [100, 120, 220, 150]},
                    {"cellId": "H-RATIO", "text": "检测比例", "row": 0, "col": 1, "bbox": [220, 120, 340, 150]},
                    {"cellId": "H-LEVEL", "text": "合格级别", "row": 0, "col": 2, "bbox": [340, 120, 460, 150]},
                    {"cellId": "H-GRADE", "text": "技术等级", "row": 0, "col": 3, "bbox": [460, 120, 580, 150]},
                    {"cellId": "V-METHOD", "text": "RT", "row": 1, "col": 0, "bbox": [100, 160, 220, 190]},
                    {"cellId": "V-RATIO", "text": "10%", "row": 1, "col": 1, "bbox": [220, 160, 340, 190]},
                    {"cellId": "V-LEVEL", "text": "III", "row": 1, "col": 2, "bbox": [340, 160, 460, 190]},
                    {"cellId": "V-GRADE", "text": "AB", "row": 1, "col": 3, "bbox": [460, 160, 580, 190]},
                ],
            }
        ],
    }
    prior = build_evidence_prior(parse_result, profile_for("piping_characteristic_list_v1"))["compact"]
    values = {
        item["text"]: item
        for item in prior["candidates"]
        if item.get("sourceId") in {"V-METHOD", "V-RATIO", "V-LEVEL", "V-GRADE"}
    }

    assert values["RT"]["semanticKey"] == "detection_method"
    assert values["10%"]["semanticKey"] == "detection_ratio"
    assert values["III"]["semanticKey"] == "evaluation_level"
    assert values["AB"]["semanticKey"] == "technical_grade"

    output = {
        "fields": {
            "detection_method": {"value": "RT", "sourceCandidateIds": [values["RT"]["candidateId"]]},
            "detection_ratio": {"value": "10%", "sourceCandidateIds": [values["10%"]["candidateId"]]},
            "evaluation_level": {"value": "III", "sourceCandidateIds": [values["III"]["candidateId"]]},
            "technical_grade": {"value": "AB", "sourceCandidateIds": [values["AB"]["candidateId"]]},
            "strength_test": {"value": "RT", "sourceCandidateIds": [values["RT"]["candidateId"]]},
        }
    }
    validated = validate_shadow_attribution(output, prior)["structuredOutput"]["fields"]

    assert validated["detection_method"]["attributionStatus"] == "validated"
    assert validated["detection_ratio"]["attributionStatus"] == "validated"
    assert validated["evaluation_level"]["attributionStatus"] == "validated"
    assert validated["technical_grade"]["attributionStatus"] == "validated"
    assert validated["strength_test"]["attributionStatus"] == "unsupported"


def test_whole_table_and_direct_vision_outputs_stay_advisory() -> None:
    prior = build_evidence_prior(sample_parse_result(), profile_for("ndt_rt_report_v1"))["full"]
    table = next(item for item in prior["candidates"] if item.get("candidateType") == "table_block")
    output = {
        "tables": [{"value": table["text"], "sourceCandidateIds": [table["candidateId"]]}],
        "visualFinding": {"value": "存在签名", "sourceCandidateIds": []},
    }

    validated = validate_shadow_attribution(output, prior)

    assert validated["structuredOutput"]["tables"][0]["attributionStatus"] == "advisory_only"
    assert validated["structuredOutput"]["visualFinding"]["attributionStatus"] == "unsupported"
    assert validated["advisoryOnly"] is True
    assert validated["formalEvidenceReady"] is False


def test_empty_table_containers_do_not_count_as_unsupported_claims() -> None:
    prior = build_evidence_prior(sample_parse_result(), profile_for("ndt_rt_report_v1"))["compact"]
    output = {
        "tables": {
            "rows": [
                {
                    "cells": {"missing_value": {"value": None, "sourceCandidateIds": []}},
                    "sourceCandidateIds": [],
                }
            ]
        }
    }

    validated = validate_shadow_attribution(output, prior)

    assert validated["validation"]["statusCounts"]["unsupported"] == 0
    assert validated["structuredOutput"]["tables"]["rows"][0]["attributionStatus"] == "empty"


def test_document_ai_client_uses_bearer_auth_and_hybrid_endpoint(tmp_path: Path) -> None:
    source = tmp_path / "sample.png"
    source.write_bytes(b"not-an-image-for-client-contract")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/hybrid/extract"
        assert request.headers["authorization"] == "Bearer test-secret"
        assert request.headers["x-aicheck-document-ai-metadata-b64"]
        return httpx.Response(200, json={"runId": "REMOTE-1", "structuredOutput": {"fields": {}}})

    document_ai = DocumentAiClient(
        "http://document-ai.test",
        api_key="test-secret",
        transport=httpx.MockTransport(handler),
    )
    result = document_ai.extract_upload_sync(source, {"schemaVersion": "DocumentAiHybridExtractRequest@1"})

    assert result["runId"] == "REMOTE-1"
    assert document_ai.public_config()["apiKeyConfigured"] is True
    assert "test-secret" not in json.dumps(document_ai.public_config())


def test_shadow_schedule_is_idempotent_and_never_mutates_baseline(monkeypatch) -> None:
    monkeypatch.setenv("AICHECK_DOCUMENT_AI_MODE", "shadow")
    monkeypatch.setenv("AICHECK_DOCUMENT_AI_PROFILE_ALLOWLIST", "ndt_rt_report_v1")
    monkeypatch.setattr(
        tasks.task_dispatcher,
        "dispatch_document_ai_shadow",
        lambda run_id: {"mode": "celery", "taskId": "TASK-SHADOW-1", "statusReason": "shadow_queued"},
    )
    repo.state["versions"].append(
        {
            "id": "DV-SHADOW-001",
            "documentId": "DOC-SHADOW-001",
            "storageKey": "source.pdf",
            "storageBucket": "documents",
        }
    )
    parse_result = sample_parse_result()
    baseline_hash = stable_payload_hash(parse_result)

    first = tasks.schedule_document_ai_shadow(
        document_id="DOC-SHADOW-001",
        version_id="DV-SHADOW-001",
        storage_key="source.pdf",
        file_name="source.pdf",
        profile_id="ndt_rt_report_v1",
        parse_result=parse_result,
        operation_id="OCR-TASK-1",
    )
    second = tasks.schedule_document_ai_shadow(
        document_id="DOC-SHADOW-001",
        version_id="DV-SHADOW-001",
        storage_key="source.pdf",
        file_name="source.pdf",
        profile_id="ndt_rt_report_v1",
        parse_result=parse_result,
        operation_id="OCR-TASK-1",
    )

    assert document_ai_shadow_enabled("ndt_rt_report_v1") is True
    assert first["taskId"] == "TASK-SHADOW-1"
    assert second["alreadyScheduled"] is True
    assert len(repo.state["document_ai_shadow_runs"]) == 1
    assert repo.state["document_ai_shadow_runs"][0]["advisoryOnly"] is True
    assert repo.state["document_ai_shadow_runs"][0]["businessImpact"] == "none"
    assert stable_payload_hash(parse_result) == baseline_hash


def test_shadow_task_failure_records_failure_without_changing_parse_result(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "source.png"
    source.write_bytes(b"image-placeholder")
    parse_result = sample_parse_result()
    baseline_hash = stable_payload_hash(parse_result)
    run_id = tasks.document_ai_shadow_run_id(parse_result["parseResultId"], "ndt_rt_report_v1")
    run = {
        "id": run_id,
        "runId": run_id,
        "status": "queued",
        "advisoryOnly": True,
        "businessImpact": "none",
        "documentId": parse_result["documentId"],
        "documentVersionId": parse_result["documentVersionId"],
        "parseResultId": parse_result["parseResultId"],
        "profileId": "ndt_rt_report_v1",
        "fileName": "source.png",
        "baselineHash": baseline_hash,
    }
    repo.state["ocr_parse_results"].append(parse_result)
    repo.state["document_ai_shadow_runs"].append(run)
    monkeypatch.setattr(tasks, "refresh_worker_state", lambda selected=None: None)
    monkeypatch.setattr(tasks, "persist_document_ai_shadow_run", lambda record: None)
    monkeypatch.setattr(tasks, "document_ai_source_path", lambda record: (source, None))

    class FailingClient:
        def extract_upload_sync(self, path, payload):
            raise RuntimeError("remote_failed")

    monkeypatch.setattr(tasks, "DocumentAiClient", FailingClient)
    result = tasks.document_ai_shadow_extract.run(run_id)

    assert result["status"] == "failed"
    assert result["advisoryOnly"] is True
    assert run["businessImpact"] == "none"
    assert run["formalEvidenceReady"] is False
    assert stable_payload_hash(parse_result) == baseline_hash


def test_fde_shadow_run_endpoints_are_read_only_and_permission_guarded() -> None:
    repo.state["document_ai_shadow_runs"].append(
        {
            "id": "DOCSH-FDE-1",
            "runId": "DOCSH-FDE-1",
            "status": "success",
            "advisoryOnly": True,
            "businessImpact": "none",
            "profileId": "ndt_rt_report_v1",
            "documentId": "DOC-1",
            "formalEvidenceReady": True,
            "createdAt": "2026-07-11 10:00:00",
            "evidencePrior": {"candidates": []},
        }
    )

    page_response = client.get("/api/fde/document-ai/shadow-runs", headers={"X-Role": "fde"})
    assert page_response.status_code == 200
    page_payload = page_response.json()["data"]
    assert page_payload["total"] == 1
    assert "evidencePrior" not in page_payload["items"][0]

    detail_response = client.get("/api/fde/document-ai/shadow-runs/DOCSH-FDE-1", headers={"X-Role": "fde"})
    detail = detail_response.json()["data"]
    assert detail["advisoryOnly"] is True
    assert detail["formalEvidenceReady"] is False
    assert detail["businessImpact"] == "none"

    forbidden = client.get("/api/fde/document-ai/shadow-runs", headers={"X-Role": "contractor"})
    assert forbidden.json()["data"]["reason"] == "FORBIDDEN"
