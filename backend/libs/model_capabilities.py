"""按模型名的能力表：输出 token 上限、思考开关、上下文、单价（P8 H1）。

为什么要有这张表（2026-09-06 六模型实测）：
- DashScope 对 qwen-plus / qwen-flash / qwen3-30b 的 max_tokens 上限是 32768，一键分析默认要 48000，
  直接 HTTP 400；qwen3 开源系列非流式必须 enable_thinking=false，否则也是 400。
- 计费此前用全局单价（输入 2 / 输出 8 元每百万），换模型省不省钱在成本曲线上根本看不出来。

原则：运行时只做"钳到上限 + 补必需参数 + 记一笔"，不改调用方意图；表里没有的模型原样放行。
匹配按前缀，长前缀优先；表是保守值，来源于供应商文档与实测，改动要带日期。
"""

from __future__ import annotations

import json
import os
from typing import Any

PRICING_ENV = "AICHECK_MODEL_PRICING_JSON"
PRICE_VERSION_TABLE = "per-model-pricing-2026-09"

# maxOutputTokens: 供应商接受的最大 max_tokens；contextTokens: 上下文窗口（真实 token）；
# needsThinkingOff: 非流式请求必须显式 enable_thinking=false；supportsTools: 支持 function calling。
MODEL_CAPABILITIES: dict[str, dict[str, Any]] = {
    "qwen3.8-max": {
        "maxOutputTokens": 65536,
        "contextTokens": 262144,
        "needsThinkingOff": False,
        "supportsTools": True,
    },
    "qwen3.7-plus": {
        "maxOutputTokens": 65536,
        "contextTokens": 262144,
        "needsThinkingOff": False,
        "supportsTools": True,
    },
    "qwen3.7-max": {
        "maxOutputTokens": 65536,
        "contextTokens": 262144,
        "needsThinkingOff": False,
        "supportsTools": True,
    },
    "qwen3.6-flash": {
        "maxOutputTokens": 32768,
        "contextTokens": 131072,
        "needsThinkingOff": False,
        "supportsTools": True,
    },
    "qwen-plus": {
        "maxOutputTokens": 32768,
        "contextTokens": 131072,
        "needsThinkingOff": False,
        "supportsTools": True,
    },
    "qwen-flash": {
        "maxOutputTokens": 32768,
        "contextTokens": 1000000,
        "needsThinkingOff": False,
        "supportsTools": True,
    },
    "qwen-vl-max": {
        "maxOutputTokens": 8192,
        "contextTokens": 131072,
        "needsThinkingOff": False,
        "supportsTools": False,
    },
    "qwen3-30b": {
        "maxOutputTokens": 32768,
        "contextTokens": 131072,
        "needsThinkingOff": True,
        "supportsTools": True,
    },
    "qwen3-8b": {
        "maxOutputTokens": 8192,
        "contextTokens": 131072,
        "needsThinkingOff": True,
        "supportsTools": True,
    },
    "qwen3-": {
        "maxOutputTokens": 16384,
        "contextTokens": 131072,
        "needsThinkingOff": True,
        "supportsTools": True,
    },
    "deepseek-v4-pro": {
        "maxOutputTokens": 65536,
        "contextTokens": 262144,
        "needsThinkingOff": False,
        "supportsTools": True,
    },
    "deepseek-v4-flash": {
        "maxOutputTokens": 32768,
        "contextTokens": 131072,
        "needsThinkingOff": False,
        "supportsTools": True,
    },
}

# 元 / 百万 token；来源：阿里云百炼与 DeepSeek 2026-09 公开价，未核实的模型不写，回退全局单价。
DEFAULT_MODEL_PRICING_CNY: dict[str, dict[str, float]] = {
    "qwen3.8-max": {"input": 6.0, "output": 24.0},
    "qwen3.7-plus": {"input": 2.0, "output": 8.0},
    "qwen3.6-flash": {"input": 0.3, "output": 3.0},
    "qwen-plus": {"input": 0.8, "output": 2.0},
    "qwen-flash": {"input": 0.15, "output": 1.5},
    "qwen3-30b": {"input": 0.75, "output": 3.0},
    "qwen3-8b": {"input": 0.3, "output": 1.2},
    "qwen-vl-max": {"input": 3.0, "output": 9.0},
}

# 能力表里有、但故意不写价的模型，以及不写的理由。
#
# 为什么要显式列出来：没有价目的模型会回退到全局 env 单价（按 qwen 定的），
# 金额是错的却看不出来。2026-09-07 线上审计实测——deepseek-v4-pro 占历史模型调用的 55%
# （113/204），一直按 qwen 单价计费。列在这里 + 配套用例，保证以后新增模型要么补价，
# 要么明确写清为什么不补，不会再悄悄漏掉。
UNPRICED_MODELS: dict[str, str] = {
    "deepseek-v4-pro": "DeepSeek 2026-09 公开价未核实；用它计费前必须补价，否则按 qwen 全局单价错算",
    "deepseek-v4-flash": "同上",
    "qwen3.7-max": "百炼价目未核实",
    "qwen3-": "前缀占位条目，不是真实模型",
}


def _match_prefix(model: str, table: dict[str, Any]) -> tuple[str | None, Any]:
    name = str(model or "").strip().lower()
    if not name:
        return None, None
    # 去掉 provider 前缀（official_api:qwen-plus）与版本后缀（qwen-plus-2025-07-14）
    if ":" in name:
        name = name.rsplit(":", 1)[-1]
    best_key, best_value = None, None
    for key, value in table.items():
        if name.startswith(key.lower()) and (best_key is None or len(key) > len(best_key)):
            best_key, best_value = key, value
    return best_key, best_value


def capabilities_for(model: str) -> dict[str, Any] | None:
    key, value = _match_prefix(model, MODEL_CAPABILITIES)
    return dict(value, matchedPrefix=key) if value else None


def apply_model_capabilities(
    model: str, kwargs: dict[str, Any], *, streaming: bool = False
) -> tuple[dict[str, Any], dict[str, Any]]:
    """返回 (调整后的 kwargs, 变更记录)。变更记录为空表示原样放行。"""
    caps = capabilities_for(model)
    adjusted = dict(kwargs)
    changes: dict[str, Any] = {}
    if not caps:
        return adjusted, changes
    limit = int(caps.get("maxOutputTokens") or 0)
    requested = adjusted.get("max_tokens")
    if limit and isinstance(requested, int | float) and int(requested) > limit:
        adjusted["max_tokens"] = limit
        changes["maxTokens"] = {"requested": int(requested), "applied": limit}
    if caps.get("needsThinkingOff") and not streaming and "enable_thinking" not in adjusted:
        adjusted["enable_thinking"] = False
        changes["enableThinking"] = {
            "applied": False,
            "reason": "model requires explicit enable_thinking=false for non-stream",
        }
    if changes:
        changes["matchedPrefix"] = caps.get("matchedPrefix")
        changes["model"] = model
    return adjusted, changes


def _pricing_table() -> dict[str, dict[str, float]]:
    table = dict(DEFAULT_MODEL_PRICING_CNY)
    raw = os.getenv(PRICING_ENV, "").strip()
    if raw:
        try:
            loaded = json.loads(raw)
        except json.JSONDecodeError:
            loaded = {}
        if isinstance(loaded, dict):
            for key, value in loaded.items():
                if isinstance(value, dict) and "input" in value and "output" in value:
                    table[str(key)] = {
                        "input": float(value["input"]),
                        "output": float(value["output"]),
                    }
    return table


def unpriced_reason(model: str | None) -> str | None:
    """这个模型为什么没有单价；能定价时返回 None。给成本记录与审计用。"""
    if pricing_for(model):
        return None
    key, reason = _match_prefix(str(model or ""), UNPRICED_MODELS)
    return reason if key else "不在能力表与价目表里"


def pricing_for(model: str | None) -> dict[str, Any] | None:
    """命中返回 {input, output, matchedPrefix}，单位 元/百万 token；未命中返回 None（调用方回退全局单价）。"""
    if not model:
        return None
    key, value = _match_prefix(model, _pricing_table())
    if not value:
        return None
    return {"input": float(value["input"]), "output": float(value["output"]), "matchedPrefix": key}
