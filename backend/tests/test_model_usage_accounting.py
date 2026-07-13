from __future__ import annotations

import json

from fastapi.testclient import TestClient

from apps.api.main import app
from libs.db.repository import repo
from libs.model_usage import estimate_messages_tokens, model_cost_cny, normalize_model_usage
from libs.review_orchestrator.execution import generate_finding_drafts


client = TestClient(app)


def setup_function() -> None:
    repo.reset()


def valid_finding() -> dict:
    return {
        "findingType": "ai_review_suggestion",
        "severity": "medium",
        "title": "待人工复核",
        "description": "请人工核对材料。",
        "evidenceRefs": [],
        "ruleRefs": [],
        "kbRefs": [],
        "confidence": 0.5,
        "suggestedAction": "human_confirm",
        "groundingStatus": "insufficient_evidence",
        "unsupportedClaims": [],
    }


def test_model_usage_normalizes_provider_fields_and_cache_tokens() -> None:
    usage = normalize_model_usage(
        {
            "prompt_tokens": 100,
            "completion_tokens": 20,
            "total_tokens": 120,
            "prompt_tokens_details": {"cached_tokens": 40, "cache_creation_tokens": 10},
            "completion_tokens_details": {"reasoning_tokens": 5},
        }
    )

    assert usage == {
        "inputTokens": 100,
        "outputTokens": 20,
        "cacheCreationInputTokens": 10,
        "cacheReadInputTokens": 40,
        "reasoningTokens": 5,
        "totalTokens": 120,
        "measurement": "provider_reported",
    }
    assert model_cost_cny({"prompt_tokens": 1_000_000, "completion_tokens": 1_000_000})["total"] == 10.0
    assert estimate_messages_tokens([{"role": "user", "content": "测试 prompt"}]) > 0


def test_review_provider_call_is_recorded_in_model_attempt_ledger(monkeypatch) -> None:
    class FakeClient:
        def chat_sync(self, messages, **kwargs):
            return {
                "id": "review-call-1",
                "provider": "Model Studio / DashScope",
                "model": "qwen3.7-plus",
                "choices": [{"finish_reason": "stop", "message": {"content": json.dumps({"findings": [valid_finding()]})}}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
            }

    monkeypatch.setattr("libs.review_orchestrator.execution.review_llm_execution_mode", lambda: "litellm")
    monkeypatch.setattr("libs.review_orchestrator.execution.build_review_messages", lambda review_run, context: [{"role": "user", "content": "review"}])
    monkeypatch.setattr("libs.review_orchestrator.execution.build_review_prompt_shape", lambda review_run, context: {})
    monkeypatch.setattr("libs.review_orchestrator.execution.qwen_runtime_public_config", lambda: {"provider": "Model Studio / DashScope"})
    monkeypatch.setattr("libs.review_orchestrator.execution.qwen_runtime_client", lambda: FakeClient())
    run = {
        "reviewRunId": "RRUN-COST-001",
        "aiRunId": "AIRUN-COST-001",
        "projectId": "P-2026-HDCP-001",
        "nodeId": 24,
        "modelAlias": "review-chat",
    }
    context = {
        "groundingInput": {
            "groundingStatus": "insufficient_evidence",
            "groundingPolicy": "evidence_only",
            "documentVersionIds": [],
            "evidenceLinks": [],
            "evidenceTextCorpus": [],
        }
    }

    drafts, metadata = generate_finding_drafts(run, context)

    attempt = next(item for item in repo.state["model_call_attempts"] if item["reviewRunId"] == run["reviewRunId"])
    assert drafts
    assert metadata["usageNormalized"]["totalTokens"] == 120
    assert attempt["status"] == "success"
    assert attempt["logicalCallId"] == "review:RRUN-COST-001:generate_findings"
    assert attempt["usageNormalized"]["inputTokens"] == 100
    assert attempt["costNormalized"]["total"] > 0


def test_fde_cost_budget_uses_normalized_attempts_and_marks_unknown_costs() -> None:
    repo.state["model_call_attempts"] = [
        {
            "id": "MCALL-1",
            "stage": "review_generate_findings",
            "usageNormalized": {"totalTokens": 120},
            "costNormalized": {"total": 0.001},
        },
        {"id": "MCALL-LEGACY", "stage": "official_ocr", "estimatedCostCny": 0.2},
    ]

    response = client.get("/api/fde/cost-budgets", headers={"X-Role": "fde"})
    payload = response.json()["data"]["usage"]

    assert payload["tokenEstimate"] == 120
    assert payload["estimatedPrice"] == 0.001
    assert payload["modelAttemptCount"] == 2
    assert payload["normalizedAttemptCount"] == 1
    assert payload["unknownCostAttemptCount"] == 1
    assert payload["complete"] is False
