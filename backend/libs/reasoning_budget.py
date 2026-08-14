"""推理模型的输出预算：别让推理把正文的额度吃光。

## 症状

2026-08-14 换成 deepseek-v4-pro（推理模型）后，监检点推荐问题，等 40 秒，
拿到一句「模型调用失败（LLM_OUTPUT_EMPTY）」。用量记的是 输出 1,200 token——
正好顶到 max_tokens。

模型没有出错，也没有拒答。它把 1200 token 全花在 reasoning_content 上，
轮到写正文时额度已经没了，于是 content 是空字符串。

OpenAI 兼容协议里 `max_tokens` 限的是**整个 completion**，推理 token 一并计入。
这个约束在非推理模型时代不存在，1200 这个值当时够用。换供应商时没人会想到
去检查一个写死了很久、一直好好的常量——这正是它值得单独成模块并写清楚的原因。

## 判定口径

`LLM_OUTPUT_EMPTY` 这个原因是真的，但没用：它告诉人「模型没输出」，
而人需要知道的是「为什么没输出、我该改什么」。区分出预算耗尽这一种，
才能给出「把 AICHECK_REVIEW_CONVERSATION_MAX_OUTPUT_TOKENS 调大」这样的下一步。
"""

from __future__ import annotations

import os
from typing import Any

# 默认给推理模型留足余量。1200 是非推理时代的值，对 deepseek-v4-pro 这类
# 模型连推理都装不下（实测简单一问就用掉 321 个推理 token，带工具调用的
# 节点核查轻松破千）。
DEFAULT_MAX_OUTPUT_TOKENS = 4000
MAX_OUTPUT_TOKENS_ENV = "AICHECK_REVIEW_CONVERSATION_MAX_OUTPUT_TOKENS"

# 预算耗尽的判定线：推理 token 占了输出的绝大部分，且总输出顶到上限。
_REASONING_DOMINANCE = 0.8


def conversation_max_output_tokens() -> int:
    """对话 Agent 单轮的输出上限。

    下限 800：再低连一段核查结论表格都写不完，调低没有意义。
    上限 32000：防止把一个笔误写进 env 变成一次昂贵的调用。
    """
    raw = os.getenv(MAX_OUTPUT_TOKENS_ENV, "").strip()
    if not raw:
        return DEFAULT_MAX_OUTPUT_TOKENS
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_MAX_OUTPUT_TOKENS
    return max(800, min(32000, value))


def reasoning_tokens_from_usage(usage: dict[str, Any] | None) -> int:
    """从 usage 里取推理 token 数。

    字段位置各家不一：DeepSeek 放在 completion_tokens_details.reasoning_tokens，
    也有直接给 reasoning_tokens 的。取不到就返回 0——**不猜**，
    猜错会把普通的空输出误判成预算耗尽，给出一个没用的处置建议。
    """
    data = usage if isinstance(usage, dict) else {}
    details = data.get("completion_tokens_details")
    if isinstance(details, dict) and details.get("reasoning_tokens") is not None:
        try:
            return max(0, int(details["reasoning_tokens"]))
        except (TypeError, ValueError):
            return 0
    for key in ("reasoning_tokens", "reasoningTokens"):
        if data.get(key) is not None:
            try:
                return max(0, int(data[key]))
            except (TypeError, ValueError):
                return 0
    return 0


def output_budget_exhausted_by_reasoning(
    usage: dict[str, Any] | None,
    max_output_tokens: int,
    finish_reason: str | None = None,
) -> bool:
    """这次空输出是不是因为推理把预算吃光了。

    两条判据取其一：
      finish_reason 明说截断（length / max_tokens）——供应商给了准信，直接采信；
      或者输出顶到上限、且推理占了八成以上——供应商没给准信时的推断。

    只有推理 token 没顶上限时不算：那是模型真的没话说，改预算解决不了。
    """
    if str(finish_reason or "").strip().lower() in {"length", "max_tokens", "token_limit"}:
        return True
    data = usage if isinstance(usage, dict) else {}
    try:
        completion = int(data.get("completion_tokens") or data.get("outputTokens") or 0)
    except (TypeError, ValueError):
        return False
    if completion <= 0 or max_output_tokens <= 0:
        return False
    reasoning = reasoning_tokens_from_usage(data)
    if reasoning <= 0:
        return False
    return completion >= max_output_tokens and reasoning >= completion * _REASONING_DOMINANCE
