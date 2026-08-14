"""推理模型的输出预算。

2026-08-14 线上：监检点推荐问题，等 40 秒拿到「模型调用失败（LLM_OUTPUT_EMPTY）」。
用量是 输出 1,200 token——正好顶到写死的 max_tokens。模型没出错也没拒答，
它把额度全花在 reasoning_content 上，轮到写正文时没余量了。
"""

from __future__ import annotations

import pytest

from libs.reasoning_budget import (
    DEFAULT_MAX_OUTPUT_TOKENS,
    conversation_max_output_tokens,
    output_budget_exhausted_by_reasoning,
    reasoning_tokens_from_usage,
)

# 线上真实用量（deepseek-v4-pro，节点 24）
ONLINE_USAGE = {
    "prompt_tokens": 5187,
    "completion_tokens": 1200,
    "completion_tokens_details": {"reasoning_tokens": 1200},
}


def test_默认额度够推理模型用():
    """1200 是非推理时代的值，对 deepseek-v4-pro 连推理都装不下。"""
    assert DEFAULT_MAX_OUTPUT_TOKENS >= 4000
    assert conversation_max_output_tokens() == DEFAULT_MAX_OUTPUT_TOKENS


def test_额度可按环境调整(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AICHECK_REVIEW_CONVERSATION_MAX_OUTPUT_TOKENS", "8000")
    assert conversation_max_output_tokens() == 8000


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("100", 800),  # 下限：再低连一段结论表格都写不完
        ("999999", 32000),  # 上限：拦住 env 里的笔误，别变成一次昂贵调用
        ("不是数字", DEFAULT_MAX_OUTPUT_TOKENS),
        ("", DEFAULT_MAX_OUTPUT_TOKENS),
    ],
)
def test_额度取值有边界(monkeypatch: pytest.MonkeyPatch, raw: str, expected: int):
    monkeypatch.setenv("AICHECK_REVIEW_CONVERSATION_MAX_OUTPUT_TOKENS", raw)
    assert conversation_max_output_tokens() == expected


def test_取推理token数():
    assert reasoning_tokens_from_usage(ONLINE_USAGE) == 1200
    assert reasoning_tokens_from_usage({"reasoning_tokens": 42}) == 42
    # 取不到就是 0，不猜——猜错会把普通空输出误判成预算耗尽，给出没用的建议
    assert reasoning_tokens_from_usage({"completion_tokens": 100}) == 0
    assert reasoning_tokens_from_usage(None) == 0
    assert reasoning_tokens_from_usage({"completion_tokens_details": {}}) == 0
    assert reasoning_tokens_from_usage({"reasoning_tokens": "坏数据"}) == 0


def test_线上那次确实判为预算耗尽():
    assert output_budget_exhausted_by_reasoning(ONLINE_USAGE, 1200) is True


def test_供应商明说截断时直接采信():
    """finish_reason 是准信，比按比例推断可靠。"""
    assert output_budget_exhausted_by_reasoning({}, 4000, finish_reason="length") is True
    assert output_budget_exhausted_by_reasoning({}, 4000, finish_reason="max_tokens") is True


def test_没顶上限就不算预算问题():
    """模型真的没话说，调大预算解决不了——不能给一个没用的处置建议。"""
    usage = {"completion_tokens": 300, "completion_tokens_details": {"reasoning_tokens": 290}}
    assert output_budget_exhausted_by_reasoning(usage, 4000) is False


def test_没有推理token就不算():
    """非推理模型输出为空是另一回事。"""
    usage = {"completion_tokens": 4000}
    assert output_budget_exhausted_by_reasoning(usage, 4000) is False


def test_推理占比不高时不算():
    """顶到上限但正文也写了不少，那是正文太长被截，不是推理吃光的。"""
    usage = {"completion_tokens": 4000, "completion_tokens_details": {"reasoning_tokens": 500}}
    assert output_budget_exhausted_by_reasoning(usage, 4000) is False


def test_脏数据不炸():
    assert output_budget_exhausted_by_reasoning(None, 4000) is False
    assert output_budget_exhausted_by_reasoning({"completion_tokens": "x"}, 4000) is False
    assert output_budget_exhausted_by_reasoning(ONLINE_USAGE, 0) is False


def test_降级文案把两种情况分开说():
    """「模型没输出」是真的，但没用——人需要知道该改什么。"""
    from libs.review_conversation_fallback import failure_cause_text

    exhausted = failure_cause_text("LLM_OUTPUT_BUDGET_EXHAUSTED_BY_REASONING")
    assert "推理过程占满" in exhausted
    assert "MAX_OUTPUT_TOKENS" in exhausted, "要给出下一步，不能只报现象"
    assert failure_cause_text("LLM_OUTPUT_EMPTY") != exhausted
