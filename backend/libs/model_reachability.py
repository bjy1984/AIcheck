"""判断「模型这条路通不通」，与调用点分开，好让探针和运行时用同一套判定。

为什么要有这个：2026-09-10 查出生产的模型密钥无效，最后一次成功调用是 9 月 9 日
04:11，此后 AI 审查、一键分析、文件分类全都不能用——**而没有任何一项巡检会发现**。
密钥过期、余额耗尽、地址配错都是会反复发生的事，靠人偶然撞见不是办法。

判定要分清三件事，因为处置方式完全不同：

- `invalid_key`：密钥本身不对（HTTP 401/403）。要人去控制台重新签发。
- `no_balance`：密钥好的，账户没钱（HTTP 402，或 DeepSeek 那种 400 带
  Insufficient Balance）。要人去充值。
- `unreachable`：连不上、超时、5xx。可能是网络或供应商侧，通常会自愈。

2026-09-10 就栽在没分清上：主供应商密钥失效，但回退指着一个欠费的 DeepSeek，
错误先冒出来的是 402，看起来像「充值就好」，实际上充了也没用。
"""

from __future__ import annotations

import json
import re
from typing import Any

_BALANCE_RE = re.compile(r"insufficient[\s_-]*balance|余额不足|欠费", re.IGNORECASE)


def classify_failure(status: Any, body: Any = "") -> str:
    """把一次失败的调用归到三类之一；判不出来就说判不出来，不猜。"""
    text = body if isinstance(body, str) else str(body or "")
    if _BALANCE_RE.search(text):
        # 有的供应商用 400 报欠费，光看状态码会误判成请求写错了。
        return "no_balance"
    code = status if isinstance(status, int) else None
    if code in (401, 403):
        return "invalid_key"
    if code == 402:
        return "no_balance"
    if code is None or code >= 500 or code == 408 or code == 429:
        return "unreachable"
    return "unknown"


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    """多个供应商的探测结果合成一个结论。

    **只要还有一条路能通，整体就算通。** 但不通的那几条仍然逐条列出来——
    回退能用不代表主供应商坏了没人该管，今天正是主供应商悄悄坏掉才出的事。
    """
    healthy = [item for item in results if item.get("ok")]
    return {
        "ok": bool(healthy),
        "healthyProviders": [item.get("provider") for item in healthy],
        "failures": [
            {
                "provider": item.get("provider"),
                "reason": item.get("reason"),
                "status": item.get("status"),
                "detail": str(item.get("detail") or "")[:200],
            }
            for item in results
            if not item.get("ok")
        ],
        # 全都不通时说得直白些，好让告警文案不用再加工。
        "message": (
            "模型可用" if healthy
            else "所有已配置的模型供应商都不可用：" + "；".join(
                f"{item.get('provider')}={item.get('reason')}" for item in results
            )
        ),
    }


def probe_provider(
    provider: str,
    base_url: str,
    api_key: str,
    model: str,
    *,
    opener: Any,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """发一次最小的 chat 请求。`opener(url, data, headers, timeout)` 由调用方注入。

    刻意不用真实模型的长回复：探针要便宜，而且要能天天跑。
    """
    if not base_url or not api_key:
        return {"provider": provider, "ok": False, "reason": "not_configured",
                "status": None, "detail": "缺少地址或密钥"}
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 1,
    }).encode()
    try:
        opener(
            base_url.rstrip("/") + "/chat/completions",
            body,
            {"Authorization": "Bearer " + api_key, "Content-Type": "application/json"},
            timeout,
        )
    except Exception as exc:  # noqa: BLE001 -- 探针要把任何失败都归类，不能自己炸掉
        status = getattr(exc, "code", None)
        detail = ""
        read = getattr(exc, "read", None)
        if callable(read):
            try:
                detail = read().decode("utf-8", "replace")
            except Exception:  # noqa: BLE001
                detail = ""
        detail = detail or str(exc)
        return {"provider": provider, "ok": False, "reason": classify_failure(status, detail),
                "status": status, "detail": detail}
    return {"provider": provider, "ok": True, "reason": None, "status": 200, "detail": ""}
