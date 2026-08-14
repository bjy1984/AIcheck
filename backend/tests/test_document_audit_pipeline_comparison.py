from __future__ import annotations

import json
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from apps.api.main import app
from apps.worker import tasks
from libs.db.repository import repo
from libs.deepseek_runtime import (
    DeepSeekAuditClient,
    deepseek_runtime_config,
    deepseek_runtime_public_config,
)
from libs.document_audit_pipeline_comparison import (
    QwenVisionAuditClient,
    build_deepseek_messages,
    collect_source_candidate_ids,
    compare_pipeline_results,
    normalize_pipeline_result,
    schedule_pipeline_comparison,
    stable_hash_payload,
    unwrap_pipeline_payload,
)

client = TestClient(app)


def setup_function() -> None:
    repo.reset()


def comparison_env() -> dict[str, str]:
    return {
        "AICHECK_AUDIT_MODEL_COMPARISON_MODE": "shadow",
        "QWEN_API_BASE": "http://qwen.example/v1",
        "QWEN_API_KEY": "qwen-test-secret",
        "DEEPSEEK_API_BASE": "http://deepseek.example",
        "DEEPSEEK_API_KEY": "deepseek-test-secret",
    }


def test_runtime_uses_current_explicit_models_and_redacts_both_keys() -> None:
    runtime = deepseek_runtime_config(env=comparison_env())
    public = deepseek_runtime_public_config(env=comparison_env())

    assert runtime["primaryModel"] == "qwen3.7-plus"
    assert runtime["model"] == "deepseek-v4-pro"
    assert runtime["allowChallengerToReplacePrimary"] is False
    assert runtime["allowProviderFallback"] is False
    assert "qwen-test-secret" not in json.dumps(public)
    assert "deepseek-test-secret" not in json.dumps(public)


def test_clients_send_distinct_visual_and_structured_audit_requests() -> None:
    runtime = deepseek_runtime_config(env=comparison_env())

    def qwen_handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert request.url.path == "/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer qwen-test-secret"
        assert payload["model"] == "qwen3.7-plus"
        assert payload["enable_thinking"] is False
        assert payload["response_format"] == {"type": "json_object"}
        assert isinstance(payload["messages"][1]["content"], list)
        return httpx.Response(200, json={"model": "qwen3.7-plus", "choices": [{"message": {"content": "{}"}}]})

    qwen = QwenVisionAuditClient(config=runtime, transport=httpx.MockTransport(qwen_handler))
    qwen.chat_sync(
        [
            {"role": "system", "content": "audit"},
            {"role": "user", "content": [{"type": "text", "text": "json"}]},
        ]
    )

    def deepseek_handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert request.url.path == "/chat/completions"
        assert request.headers["authorization"] == "Bearer deepseek-test-secret"
        assert payload["model"] == "deepseek-v4-pro"
        assert payload["thinking"] == {"type": "enabled"}
        assert payload["reasoning_effort"] == "high"
        assert "temperature" not in payload
        return httpx.Response(200, json={"model": "deepseek-v4-pro", "choices": [{"message": {"content": "{}"}}]})

    deepseek = DeepSeekAuditClient(config=runtime, transport=httpx.MockTransport(deepseek_handler))
    deepseek.chat_sync([{"role": "user", "content": "json"}])


def test_normalization_strips_invented_candidates_and_standard_references() -> None:
    context = {
        "rules": [{"ruleCode": "R40", "sources": [{"standardNo": "NB/T 47013.2-2015"}]}],
        "retrieval": [],
    }
    payload = {
        "documentFields": {"detection_ratio": {"value": "10%"}},
        "findings": [
            {
                "findingType": "ndt_ratio",
                "severity": "high",
                "title": "检测比例",
                "description": "需核验",
                "sourceCandidateIds": ["EP2-VALID", "EP2-INVENTED"],
                "standardRefs": ["NB/T 47013.2-2015", "FAKE-STANDARD"],
                "suggestedAction": "request_correction",
                "confidence": 0.97,
            }
        ],
    }

    normalized = normalize_pipeline_result(
        payload,
        pipeline_id="paddle_nuextract_deepseek_v1",
        industry_context=context,
        allowed_candidate_ids={"EP2-VALID"},
        fixed_document_fields={"detection_ratio": {"value": "10%", "sourceCandidateIds": ["EP2-VALID"]}},
    )

    finding = normalized["findings"][0]
    assert finding["sourceCandidateIds"] == ["EP2-VALID"]
    assert finding["standardRefs"] == ["NB/T 47013.2-2015"]
    assert normalized["validation"]["invalidReferenceCount"] == 2
    assert normalized["formalEvidenceReady"] is False


def test_deepseek_prompt_separates_grounded_and_ungrounded_fields() -> None:
    run = {
        "structuredOutput": {
            "fields": {
                "detection_ratio": {"value": "10%", "sourceCandidateIds": ["EP2-RATIO"]},
                "strength_test": {"value": "0.1 MPa", "sourceCandidateIds": []},
            },
            "tables": {
                "piping_characteristic_table": [
                    {
                        "cells": {"pipe_no": ["PL-1"], "detection_ratio": ["10%", "20%"]},
                        "sourceCandidateIds": ["EP2-TABLE"],
                    }
                ]
            },
        },
        "attributionValidation": {"invalidCandidateIdCount": 0},
    }

    messages = build_deepseek_messages(run, {"rules": [], "retrieval": []})
    payload = json.loads(messages[1]["content"])

    assert payload["groundedFieldCodes"] == ["detection_ratio"]
    assert payload["ungroundedFieldCodes"] == ["strength_test"]
    assert payload["allowedSourceCandidateIds"] == ["EP2-RATIO", "EP2-TABLE"]
    assert payload["tableEvidenceQualification"]["inconsistentTableCount"] == 1
    assert any("cannot support a compliance" in requirement for requirement in payload["requirements"])


def test_ungrounded_substantive_deepseek_finding_is_downgraded() -> None:
    normalized = normalize_pipeline_result(
        {
            "findings": [
                {
                    "findingType": "NON_COMPLIANCE",
                    "severity": "high",
                    "title": "检测比例不符合",
                    "sourceCandidateIds": ["EP2-RATIO?row=5"],
                    "suggestedAction": "request_correction",
                    "confidence": 0.98,
                }
            ]
        },
        pipeline_id="paddle_nuextract_deepseek_v1",
        industry_context={"rules": [], "retrieval": []},
        allowed_candidate_ids={"EP2-RATIO"},
    )

    finding = normalized["findings"][0]
    assert finding["sourceCandidateIds"] == []
    assert finding["groundingStatus"] == "unsupported_substantive_claim"
    assert finding["suggestedAction"] == "human_confirm"
    assert finding["confidence"] == 0.45
    assert normalized["validation"]["ungroundedSubstantiveFindingCount"] == 1


def test_candidate_collection_and_table_quality_include_nested_cells() -> None:
    structured = {
        "fields": {"report_no": {"sourceCandidateIds": ["EP2-FIELD"]}},
        "tables": {
            "rows": [
                {
                    "cells": {
                        "ratio": {"value": "10%", "sourceCandidateIds": ["EP2-CELL"]},
                    }
                }
            ]
        },
    }

    assert collect_source_candidate_ids(structured) == {"EP2-FIELD", "EP2-CELL"}


def test_pipeline_comparison_reports_agreement_without_claiming_accuracy() -> None:
    baseline = {
        "documentFields": {"ratio": {"value": "10%"}, "grade": {"value": "AB"}},
        "findings": [{"severity": "high", "suggestedAction": "request_correction", "standardRefs": ["R40"]}],
    }
    challenger = {
        "documentFields": {"ratio": {"value": "10%"}, "grade": {"value": "A"}},
        "findings": [{"severity": "high", "suggestedAction": "human_confirm", "standardRefs": ["R40"]}],
    }

    metrics = compare_pipeline_results(baseline, challenger)

    assert metrics["fieldExactAgreement"] == 0.5
    assert metrics["differentValueFields"] == ["grade"]
    assert metrics["standardReferenceAgreement"] == 1.0
    assert metrics["accuracyClaimed"] is False
    assert metrics["goldEvaluationRequired"] is True


def test_qwen_schema_wrapper_is_unwrapped_before_comparison() -> None:
    payload = {
        "industryContext": {"profileId": "piping_characteristic_list_v1"},
        "outputSchema": {
            "documentFields": {"drawing_no": {"value": "QX-001"}},
            "findings": [{"severity": "low"}],
        },
    }

    unwrapped = unwrap_pipeline_payload(payload)

    assert unwrapped["documentFields"]["drawing_no"]["value"] == "QX-001"
    assert len(unwrapped["findings"]) == 1


def test_schedule_is_idempotent_and_requires_shadow_mode(monkeypatch) -> None:
    source_run = {
        "id": "DOCSH-PIPE-1",
        "runId": "DOCSH-PIPE-1",
        "status": "success",
        "profileId": "piping_characteristic_list_v1",
        "priorHash": "sha256:prior",
        "documentId": "DOC-1",
        "documentVersionId": "DV-1",
        "structuredOutput": {"fields": {}},
    }
    monkeypatch.setenv("AICHECK_AUDIT_MODEL_COMPARISON_MODE", "shadow")
    monkeypatch.setenv("QWEN_API_KEY", "qwen-test-secret")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-test-secret")
    monkeypatch.setattr(
        "libs.document_audit_pipeline_comparison.task_dispatcher.dispatch_document_audit_pipeline_comparison",
        lambda run_id: {"mode": "celery", "taskId": "TASK-COMP-1", "statusReason": "pipeline_comparison_queued"},
    )
    monkeypatch.setattr("libs.document_audit_pipeline_comparison.persist_pipeline_comparison_run", lambda run: None)

    first = schedule_pipeline_comparison(source_run)
    second = schedule_pipeline_comparison(source_run)

    assert first["taskId"] == "TASK-COMP-1"
    assert second["alreadyScheduled"] is True
    assert len(repo.state["document_audit_pipeline_comparison_runs"]) == 1
    assert repo.state["document_audit_pipeline_comparison_runs"][0]["businessImpact"] == "none"


def test_comparison_task_never_mutates_document_ai_source(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    source.write_bytes(b"placeholder")
    document_ai_run = {
        "id": "DOCSH-TASK-1",
        "runId": "DOCSH-TASK-1",
        "status": "success",
        "profileId": "piping_characteristic_list_v1",
        "selectedPageNos": [1],
        "totalTimeMs": 55_000,
        "structuredOutput": {
            "fields": {
                "detection_ratio": {
                    "value": "10%",
                    "sourceCandidateIds": ["EP2-RATIO"],
                }
            }
        },
        "attributionValidation": {"invalidCandidateIdCount": 0},
    }
    comparison = {
        "id": "DAPCOMP-TASK-1",
        "runId": "DAPCOMP-TASK-1",
        "status": "queued",
        "documentAiShadowRunId": "DOCSH-TASK-1",
        "baselinePipelineId": "qwen_vl_audit_v1",
        "challengerPipelineId": "paddle_nuextract_deepseek_v1",
    }
    repo.state["document_ai_shadow_runs"].append(document_ai_run)
    repo.state["document_audit_pipeline_comparison_runs"].append(comparison)
    source_hash = stable_hash_payload(document_ai_run)
    monkeypatch.setattr(tasks, "refresh_worker_state", lambda selected=None: None)
    monkeypatch.setattr(tasks, "persist_pipeline_comparison_run", lambda run: None)
    monkeypatch.setattr(tasks, "document_ai_source_path", lambda run: (source, None))
    monkeypatch.setattr(tasks, "render_pipeline_comparison_pages", lambda source_path, pages, target: [source])
    monkeypatch.setattr(tasks, "build_shared_industry_context", lambda run: {"rules": [], "retrieval": []})

    qwen_json = {
        "documentFields": {"detection_ratio": {"value": "10%"}},
        "findings": [{"severity": "medium", "title": "比例", "suggestedAction": "human_confirm"}],
    }
    deepseek_json = {
        "findings": [
            {
                "severity": "medium",
                "title": "比例",
                "sourceCandidateIds": ["EP2-RATIO"],
                "suggestedAction": "human_confirm",
            }
        ]
    }

    class FakeQwen:
        def chat_sync(self, messages):
            return {"model": "qwen3.7-plus", "choices": [{"message": {"content": json.dumps(qwen_json)}}]}

    class FakeDeepSeek:
        def chat_sync(self, messages, **kwargs):
            return {
                "model": "deepseek-v4-pro",
                "choices": [{"message": {"content": json.dumps(deepseek_json), "reasoning_content": "hidden"}}],
            }

    monkeypatch.setattr(tasks, "QwenVisionAuditClient", FakeQwen)
    monkeypatch.setattr(tasks, "DeepSeekAuditClient", FakeDeepSeek)

    result = tasks.document_audit_pipeline_comparison.run("DAPCOMP-TASK-1")

    assert result["status"] == "success"
    assert comparison["challengerEndToEndTimeMs"] >= 55_000
    assert comparison["rawReasoningStored"] is False
    assert comparison["formalEvidenceReady"] is False
    assert stable_hash_payload(document_ai_run) == source_hash


def test_fde_pipeline_comparison_endpoints_remain_advisory_and_scoped(monkeypatch) -> None:
    repo.state["document_audit_pipeline_comparison_runs"].append(
        {
            "id": "DAPCOMP-FDE-1",
            "runId": "DAPCOMP-FDE-1",
            "status": "success",
            "profileId": "piping_characteristic_list_v1",
            "comparisonMetrics": {"accuracyClaimed": False},
            "formalEvidenceReady": True,
        }
    )

    listing = client.get("/api/fde/document-audit/pipeline-comparisons", headers={"X-Role": "fde"})
    detail = client.get("/api/fde/document-audit/pipeline-comparisons/DAPCOMP-FDE-1", headers={"X-Role": "fde"})
    forbidden = client.get("/api/fde/document-audit/pipeline-comparisons", headers={"X-Role": "contractor"})

    assert listing.status_code == 200
    assert listing.json()["data"]["total"] == 1
    assert detail.json()["data"]["advisoryOnly"] is True
    assert detail.json()["data"]["formalEvidenceReady"] is False
    assert detail.json()["data"]["accuracyClaimed"] is False
    assert forbidden.json()["data"]["reason"] == "FORBIDDEN"


def test_fde_can_queue_comparison_only_for_successful_document_ai_run(monkeypatch) -> None:
    source_run = {
        "id": "DOCSH-FDE-SOURCE",
        "runId": "DOCSH-FDE-SOURCE",
        "status": "success",
        "profileId": "piping_characteristic_list_v1",
        "priorHash": "sha256:prior",
        "structuredOutput": {"fields": {}},
    }
    repo.state["document_ai_shadow_runs"].append(source_run)
    monkeypatch.setenv("AICHECK_AUDIT_MODEL_COMPARISON_MODE", "shadow")
    dispatched = []

    def dispatch(run_id):
        dispatched.append(run_id)
        return {"mode": "celery", "taskId": "TASK-FDE-COMP", "statusReason": "pipeline_comparison_queued"}

    monkeypatch.setattr(
        "libs.document_audit_pipeline_comparison.task_dispatcher.dispatch_document_audit_pipeline_comparison",
        dispatch,
    )
    monkeypatch.setattr("libs.document_audit_pipeline_comparison.persist_pipeline_comparison_run", lambda run: None)

    response = client.post(
        "/api/fde/document-ai/shadow-runs/DOCSH-FDE-SOURCE/pipeline-comparison",
        headers={"X-Role": "fde", "Idempotency-Key": "pipeline-comparison-fde-1"},
    )
    replay = client.post(
        "/api/fde/document-ai/shadow-runs/DOCSH-FDE-SOURCE/pipeline-comparison",
        headers={"X-Role": "fde", "Idempotency-Key": "pipeline-comparison-fde-1"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["taskId"] == "TASK-FDE-COMP"
    assert replay.json() == response.json()
    assert dispatched == [response.json()["data"]["runId"]]


def test_compose_keeps_pipeline_comparison_off_formal_workers() -> None:
    import yaml

    compose_path = Path(__file__).resolve().parents[1] / "docker-compose.yml"
    services = yaml.safe_load(compose_path.read_text(encoding="utf-8"))["services"]
    primary_command = services["worker-service"]["command"]
    comparison_command = services["audit-pipeline-comparison-worker-service"]["command"]

    assert "audit-pipeline.compare" not in primary_command
    assert "-Q audit-pipeline.compare" in comparison_command
    assert "--concurrency=1" in comparison_command
