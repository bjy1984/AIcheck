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
    input_rate: float | None = None,
    output_rate: float | None = None,
    cache_write_rate: float | None = None,
    cache_read_rate: float | None = None,
) -> dict[str, Any]:
    normalized = normalize_model_usage(usage)
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
        "priceVersion": "env-configured-model-pricing-2026-07",
    }


def estimate_text_tokens(text: str) -> int:
    if not text:
        return 0
    utf8_bytes = len(text.encode("utf-8"))
    return max(1, (utf8_bytes + 3) // 4)


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
