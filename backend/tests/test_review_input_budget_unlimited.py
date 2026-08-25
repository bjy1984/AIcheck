"""输入 token 上限默认不设——那道闸原本在替模型拒绝请求。

## 线上实测（2026-08-16）

    RRUN-CECAAFEE2C  P-2026-8FC0B5 节点 24  failed
    QwenRuntime review.chat failed: reason REVIEW_INPUT_TOKEN_BUDGET_EXCEEDED

上限写死 24000，而生产模型的上下文远大于它。节点资料一多就整次失败，
监检**一份资料都没审到**，界面只显示「执行异常」。

顺带记一次我自己的错判：此前我用「缺项预审」跑通就宣布这条已修——
那是另一条路径。**换条路验证等于没验证。**

## 判据

- 默认（不设环境变量）＝不限：不裁减、不报超预算
- 显式给正数才重新设闸
- 0 不是「上限为 0」。把 0 当上限会让每次运行都超预算，
  从「偶尔失败」变成「永远失败」——这种翻转比原问题更糟
- 不限模式下误调裁减函数要当场报错，不能算出负余量把证据全裁光
"""

from __future__ import annotations

import json

import pytest

from libs.db.repository import repo
from libs.review_orchestrator import execution as ex


def test_默认不限(monkeypatch):
    monkeypatch.delenv("AICHECK_REVIEW_MAX_INPUT_TOKENS", raising=False)
    assert ex._review_max_input_tokens() == 0


def test_旧输入上限环境变量即使为正数也被忽略(monkeypatch):
    monkeypatch.setenv("AICHECK_REVIEW_MAX_INPUT_TOKENS", "60000")
    assert ex._review_max_input_tokens() == 0


def test_零和负数都表示不限(monkeypatch):
    for raw in ("0", "-1", "", "  "):
        monkeypatch.setenv("AICHECK_REVIEW_MAX_INPUT_TOKENS", raw)
        assert ex._review_max_input_tokens() == 0, raw


def test_乱填不炸也不误设闸(monkeypatch):
    """配置写错时宁可不限，也不要设成一个莫名其妙的小数字。"""
    monkeypatch.setenv("AICHECK_REVIEW_MAX_INPUT_TOKENS", "两万四")
    assert ex._review_max_input_tokens() == 0


def test_不限时误调裁减要当场报错():
    """用 0 算余量会得到负数，把证据全裁光再报超预算——
    症状是「明明没设上限却永远超预算」，最难查的那种。"""
    with pytest.raises(ValueError, match="不应调用证据裁减"):
        ex.trim_review_input_to_budget(
            {"reviewRunId": "RRUN-TEST"},
            {"groundingInput": {}},
            {"maxInputTokens": 0},
        )


def test_legacy_positive_input_cap_never_drops_or_rejects_evidence(monkeypatch):
    """旧环境变量即使仍有正值，也只能影响后续分片目标，不能裁资料或拒绝运行。"""

    class FakeRuntime:
        def chat_sync(self, messages, **kwargs):
            assert messages == [{"role": "user", "content": "完整证据" * 1000}]
            return {
                "id": "RESP-NO-TRIM",
                "model": "review-chat",
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps(
                                {
                                    "findings": [
                                        {
                                            "findingType": "evidence_review",
                                            "severity": "medium",
                                            "title": "完整证据已送审",
                                            "description": "需人工确认。",
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
                        },
                    }
                ],
                "usage": {"input_tokens": 100000, "output_tokens": 100},
            }

    repo.reset()
    monkeypatch.setattr(ex, "review_llm_execution_mode", lambda: "litellm")
    monkeypatch.setattr(
        ex,
        "review_model_budget_policy",
        lambda _run: {
            "maxInputTokens": 1,
            "maxOutputTokens": 1000,
            "maxCostCny": 1000.0,
            "maxAttempts": 1,
        },
    )
    monkeypatch.setattr(
        ex,
        "build_review_messages",
        lambda _run, _context: [{"role": "user", "content": "完整证据" * 1000}],
    )
    monkeypatch.setattr(ex, "estimate_messages_tokens", lambda _messages: 100000)
    monkeypatch.setattr(ex, "model_cost_cny", lambda _usage: {"total": 0.0})
    monkeypatch.setattr(ex, "qwen_runtime_public_config", lambda: {"provider": "test"})
    monkeypatch.setattr(ex, "qwen_runtime_client", lambda: FakeRuntime())
    monkeypatch.setattr(
        ex,
        "trim_review_input_to_budget",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("silent trim called")),
    )
    review_run = {
        "reviewRunId": "RRUN-NO-TRIM",
        "aiRunId": "AIRUN-NO-TRIM",
        "projectId": "P-1",
        "nodeId": 1,
        "modelAlias": "review-chat",
        "promptVersion": "p1",
        "agentId": "agent",
        "agentVersion": "1",
    }
    context = {
        "promptShape": {"messagesHash": "sha256:prompt"},
        "groundingInput": {
            "groundingStatus": "insufficient_evidence",
            "documentVersionIds": ["DV-1"],
            "evidenceLinks": [],
            "evidenceTextCorpus": ["完整证据"],
        },
        "auditRuntime": {"mode": "ocr_llm"},
    }

    drafts, metadata = ex.generate_finding_drafts(review_run, context)

    assert drafts
    assert metadata["llmCalled"] is True
