"""P8 H4：信封修复 → 升级模型 → 才算分片失败；全部分片失败才整次未完成。

2026-09-06 实测 qwen-plus 9 片里 6 片 LLM_OUTPUT_INVALID_ENVELOPE，整次 review_incomplete。
"""

from __future__ import annotations

import json

import pytest

from libs.db.repository import repo
from libs.integrations.errors import IntegrationServiceError
from libs.review_orchestrator import shard_recovery
from libs.review_orchestrator.shard_execution import EvidenceShardProcessingIncomplete

GOOD = json.dumps(
    {
        "findings": [
            {
                "findingType": "license_review",
                "severity": "medium",
                "title": "许可证待人工确认",
                "description": "许可证资料需要人工核对。",
                "evidenceRefs": [],
                "ruleRefs": [],
                "kbRefs": [],
                "confidence": 0.5,
                "suggestedAction": "human_confirm",
                "groundingStatus": "insufficient_evidence",
                "unsupportedClaims": [],
            }
        ]
    },
    ensure_ascii=False,
)


def setup_function() -> None:
    repo.reset()
    repo.state["model_call_attempts"] = []


def _run() -> dict:
    return {"reviewRunId": "RRUN-H4", "aiRunId": "AIRUN-H4", "projectId": "P-1", "nodeId": 2, "modelAlias": "review-chat"}


class FakeRuntime:
    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.calls: list[dict] = []

    def chat_sync(self, messages, **kwargs):
        self.calls.append({"messages": messages, **kwargs})
        content = self.replies.pop(0)
        return {"id": f"RESP-{len(self.calls)}", "model": kwargs.get("model"), "choices": [{"finish_reason": "stop", "message": {"content": content}}], "usage": {"input_tokens": 10, "output_tokens": 5}}


def _normalize(_run, _ctx, content):
    parsed = json.loads(content)
    if not isinstance(parsed, dict) or not isinstance(parsed.get("findings"), list):
        raise IntegrationServiceError("QwenRuntime", "review.chat", reason="LLM_OUTPUT_INVALID_ENVELOPE")
    return parsed["findings"]


def _generate_once_factory(outcomes: list, seen: list):
    """outcomes：每次调用要么返回 (drafts, metadata)，要么是要抛的 IntegrationServiceError。"""

    def generate_once(run, ctx):
        seen.append(dict(ctx))
        outcome = outcomes.pop(0)
        if isinstance(outcome, Exception):
            run["llmMetadata"] = {"resultText": '{"result": "not an envelope"}'}
            raise outcome
        return outcome

    return generate_once


def test_invalid_envelope_is_repaired_by_a_short_call_with_the_same_model(monkeypatch) -> None:
    runtime = FakeRuntime([GOOD])
    monkeypatch.setattr(shard_recovery, "qwen_runtime_client", lambda: runtime)
    seen: list = []
    generate_once = _generate_once_factory(
        [IntegrationServiceError("QwenRuntime", "review.chat", reason="LLM_OUTPUT_INVALID_ENVELOPE")], seen
    )
    run = _run()
    drafts, metadata = shard_recovery.generate_with_recovery(
        run, {"evidenceShardId": "ESHARD-1"}, generate_once=generate_once, normalize=_normalize
    )
    assert drafts and drafts[0]["title"] == "许可证待人工确认"
    assert metadata["recovery"]["recoveredBy"] == "envelope_repair"
    assert len(seen) == 1, "修复走的是短请求，不重跑整个提示词"
    assert runtime.calls[0]["model"] == "review-chat"
    assert runtime.calls[0]["max_tokens"] == shard_recovery.REPAIR_MAX_TOKENS
    assert "not an envelope" in runtime.calls[0]["messages"][-1]["content"]
    attempts = [row for row in repo.state["model_call_attempts"] if row.get("stage") == "envelope_repair"]
    assert attempts and attempts[0]["status"] == "success" and attempts[0]["evidenceShardId"] == "ESHARD-1"


def test_failed_repair_escalates_the_shard_to_the_escalation_model(monkeypatch) -> None:
    runtime = FakeRuntime(['{"still": "broken"}'])
    monkeypatch.setattr(shard_recovery, "qwen_runtime_client", lambda: runtime)
    monkeypatch.setenv("AICHECK_LLM_MODEL_REVIEW_ESCALATION", "qwen3.8-max")
    seen: list = []
    generate_once = _generate_once_factory(
        [
            IntegrationServiceError("QwenRuntime", "review.chat", reason="LLM_OUTPUT_INVALID_JSON"),
            ([{"title": "升级模型给出的发现"}], {"llmCalled": True}),
        ],
        seen,
    )
    drafts, metadata = shard_recovery.generate_with_recovery(
        _run(), {"evidenceShardId": "ESHARD-2"}, generate_once=generate_once, normalize=_normalize
    )
    assert drafts[0]["title"] == "升级模型给出的发现"
    assert metadata["recovery"] == {
        "firstFailure": "LLM_OUTPUT_INVALID_JSON",
        "envelopeRepair": "failed",
        "recoveredBy": "shard_escalation",
        "escalationModel": "qwen3.8-max",
    }
    assert seen[1]["modelOverride"] == "qwen3.8-max"
    assert seen[1]["modelAttemptStage"] == "shard_escalation"
    repair = next(row for row in repo.state["model_call_attempts"] if row.get("stage") == "envelope_repair")
    assert repair["status"] == "invalid_output"


def test_both_recoveries_failing_raises_the_original_error(monkeypatch) -> None:
    runtime = FakeRuntime(['{"still": "broken"}'])
    monkeypatch.setattr(shard_recovery, "qwen_runtime_client", lambda: runtime)
    seen: list = []
    generate_once = _generate_once_factory(
        [
            IntegrationServiceError("QwenRuntime", "review.chat", reason="LLM_OUTPUT_INVALID_ENVELOPE"),
            IntegrationServiceError("QwenRuntime", "review.chat", reason="LLM_OUTPUT_EMPTY_FINDINGS"),
        ],
        seen,
    )
    with pytest.raises(IntegrationServiceError) as error:
        shard_recovery.generate_with_recovery(_run(), {}, generate_once=generate_once, normalize=_normalize)
    assert error.value.reason == "LLM_OUTPUT_INVALID_ENVELOPE"
    assert len(seen) == 2


def test_provider_failures_are_not_escalated(monkeypatch) -> None:
    runtime = FakeRuntime([])
    monkeypatch.setattr(shard_recovery, "qwen_runtime_client", lambda: runtime)
    seen: list = []
    generate_once = _generate_once_factory(
        [IntegrationServiceError("QwenRuntime", "review.chat", reason="REVIEW_COST_BUDGET_EXCEEDED")], seen
    )
    with pytest.raises(IntegrationServiceError) as error:
        shard_recovery.generate_with_recovery(_run(), {}, generate_once=generate_once, normalize=_normalize)
    assert error.value.reason == "REVIEW_COST_BUDGET_EXCEEDED"
    assert len(seen) == 1 and runtime.calls == []


def test_all_shards_failing_still_marks_the_run_incomplete(monkeypatch) -> None:
    from libs.review_orchestrator import shard_execution

    state = {"model_call_attempts": []}
    review_run = {**_run(), "evidenceShardIds": ["ESHARD-1", "ESHARD-2"]}
    shards = [
        {"evidenceShardId": sid, "status": "pending", "artifactSegments": []} for sid in ("ESHARD-1", "ESHARD-2")
    ]
    monkeypatch.setattr(shard_execution, "review_run_evidence_package", lambda _state, _run: ({"artifacts": []}, shards))
    monkeypatch.setattr(shard_execution, "_replace_node_finding_aggregate", lambda _state, _aggregate: None)

    def always_fail(_run, _ctx):
        raise IntegrationServiceError("QwenRuntime", "review.chat", reason="LLM_OUTPUT_INVALID_ENVELOPE")

    with pytest.raises(EvidenceShardProcessingIncomplete) as error:
        shard_execution.generate_sharded_finding_drafts(state, review_run, {}, mode="litellm", generate_once=always_fail)
    assert error.value.failed_shard_ids == ["ESHARD-1", "ESHARD-2"]
