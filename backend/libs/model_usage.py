from __future__ import annotations

import os
from typing import Any


def _integer(value: Any) -> int:
    try:
        return max(int(value or 0), 0)
    except (TypeError, ValueError):
        return 0


def normalize_model_usage(raw: dict[str, Any] | None) -> dict[str, int | str]:
    usage = raw if isinstance(raw, dict) else {}
    prompt_details = usage.get("prompt_tokens_details") if isinstance(usage.get("prompt_tokens_details"), dict) else {}
    completion_details = usage.get("completion_tokens_details") if isinstance(usage.get("completion_tokens_details"), dict) else {}
    input_tokens = _integer(usage.get("input_tokens") or usage.get("inputTokens") or usage.get("prompt_tokens"))
    output_tokens = _integer(usage.get("output_tokens") or usage.get("outputTokens") or usage.get("completion_tokens"))
    cache_creation = _integer(
        usage.get("cache_creation_input_tokens")
        or usage.get("cacheCreationInputTokens")
        or prompt_details.get("cache_creation_tokens")
    )
    cache_read = _integer(
        usage.get("cache_read_input_tokens")
        or usage.get("cacheReadInputTokens")
        or prompt_details.get("cached_tokens")
    )
    reasoning = _integer(
        usage.get("reasoning_tokens")
        or usage.get("reasoningTokens")
        or completion_details.get("reasoning_tokens")
    )
    reported_total = _integer(usage.get("total_tokens") or usage.get("totalTokens"))
    return {
        "inputTokens": input_tokens,
        "outputTokens": output_tokens,
        "cacheCreationInputTokens": cache_creation,
        "cacheReadInputTokens": cache_read,
        "reasoningTokens": reasoning,
        "totalTokens": max(reported_total, input_tokens + output_tokens),
        "measurement": "provider_reported" if usage else "unknown",
    }


def model_cost_cny(
    usage: dict[str, Any] | None,
    *,
    model: str | None = None,
    input_rate: float | None = None,
    output_rate: float | None = None,
    cache_write_rate: float | None = None,
    cache_read_rate: float | None = None,
) -> dict[str, Any]:
    """按模型单价计费；没传 model 或表里没有时回退全局单价并标 priceSource=default。"""
    from libs.model_capabilities import PRICE_VERSION_TABLE, pricing_for
    from libs.model_capabilities import unpriced_reason as _unpriced_reason

    normalized = normalize_model_usage(usage)
    price_source = "default"
    price_version = "env-configured-model-pricing-2026-07"
    matched = pricing_for(model) if (input_rate is None and output_rate is None) else None
    if matched:
        input_rate = matched["input"]
        output_rate = matched["output"]
        price_source = "table"
        price_version = PRICE_VERSION_TABLE
    input_rate = float(input_rate if input_rate is not None else os.getenv("AICHECK_QWEN_INPUT_CNY_PER_MILLION", "2"))
    output_rate = float(output_rate if output_rate is not None else os.getenv("AICHECK_QWEN_OUTPUT_CNY_PER_MILLION", "8"))
    cache_write_rate = float(
        cache_write_rate
        if cache_write_rate is not None
        else os.getenv("AICHECK_QWEN_CACHE_WRITE_CNY_PER_MILLION", str(input_rate))
    )
    cache_read_rate = float(
        cache_read_rate
        if cache_read_rate is not None
        else os.getenv("AICHECK_QWEN_CACHE_READ_CNY_PER_MILLION", str(input_rate))
    )
    input_cost = normalized["inputTokens"] * input_rate / 1_000_000
    output_cost = normalized["outputTokens"] * output_rate / 1_000_000
    cache_write_cost = normalized["cacheCreationInputTokens"] * cache_write_rate / 1_000_000
    cache_read_cost = normalized["cacheReadInputTokens"] * cache_read_rate / 1_000_000
    total = input_cost + output_cost + cache_write_cost + cache_read_cost
    return {
        "currency": "CNY",
        "input": round(input_cost, 6),
        "output": round(output_cost, 6),
        "cacheWrite": round(cache_write_cost, 6),
        "cacheRead": round(cache_read_cost, 6),
        "ocrApi": 0.0,
        "total": round(total, 6),
        "priceVersion": price_version,
        "priceSource": price_source,
        "model": model or None,
        # 没命中价目表时说清为什么——回退单价是按 qwen 定的，用在别家模型上金额是错的，
        # 光看 priceSource=default 看不出这层含义（2026-09-07 线上审计发现）。
        "unpricedReason": _unpriced_reason(model) if price_source != "table" else None,
    }


def is_cjk_char(char: str) -> bool:
    code = ord(char)
    return (
        0x3000 <= code <= 0x9FFF  # CJK 标点、日文假名、统一汉字
        or 0xF900 <= code <= 0xFAFF  # 兼容汉字
        or 0xFF00 <= code <= 0xFFEF  # 全角标点与字母
        or 0x20000 <= code <= 0x2FFFF  # 扩展 B–F
    )


def estimate_text_tokens(text: str) -> int:
    """中文感知的 token 估算：CJK 字符按 1 token，其余按 4 字符 1 token。

    2026-09-06 审计实测（P8 H2）：按 len/4 估的 5,849 token 分片，模型计费 26,756 token，
    比例 4.6——通义千问对中文基本是一字一 token。按 utf-8 字节 /4 也偏低（一个汉字 3 字节
    只算 0.75）。估算偏低的后果不是省钱，是分片被切得远大于目标、9 片 52 万 token。
    """
    if not text:
        return 0
    cjk = sum(1 for char in text if is_cjk_char(char))
    other = len(text) - cjk
    return max(1, cjk + (other + 3) // 4)


def estimate_messages_tokens(messages: list[dict[str, Any]]) -> int:
    total = 0
    for message in messages:
        total += 4
        content = message.get("content")
        if isinstance(content, str):
            total += estimate_text_tokens(content)
        else:
            total += estimate_text_tokens(str(content or ""))
    return total
