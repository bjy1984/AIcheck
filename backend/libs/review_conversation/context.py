"""对话 Agent 上下文组装：检索词切分（ASCII 词 + CJK bigram）、相关性排序、LLM payload 压缩。

从 apps/api/routes.py 纯搬移抽离（B1 重构）；对 routes 命名空间的引用
统一经 _r() 晚绑定，保持 monkeypatch 与运行语义不变。
"""

from __future__ import annotations

import re
from typing import Any, Iterable


def _r():
    """晚绑定访问 apps.api.routes 命名空间。

    抽离前这些引用都是 routes 模块全局名（晚绑定）；统一经 _r() 访问保持
    完全相同的语义 —— 测试对 routes 属性的 monkeypatch（如 qwen_runtime_client、
    review_conversation_agent_tool_output）依然对本模块内部调用生效。
    """
    from apps.api import routes

    return routes


_CONTEXT_ASCII_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_.\-/]+")
_CONTEXT_CJK_RUN_RE = re.compile(r"[一-鿿]{2,}")


def review_context_match_tokens(text: str) -> set[str]:
    source = str(text or "").lower()
    tokens: set[str] = set(_r()._CONTEXT_ASCII_TOKEN_RE.findall(source))
    for run in _r()._CONTEXT_CJK_RUN_RE.findall(source):
        for index in range(len(run) - 1):
            tokens.add(run[index : index + 2])
    return tokens


def rank_context_items(
    items: list[Any],
    *,
    query_tokens: set[str],
    text_of: Any,
    limit: int,
    prioritize: Any = None,
) -> list[Any]:
    """按相关性截取候选：优先项（如冲突事实）恒在前，其余按匹配分与原序。"""
    scored: list[tuple[bool, int, int, Any]] = []
    for index, item in enumerate(items):
        score = len(query_tokens & _r().review_context_match_tokens(text_of(item)))
        scored.append((bool(prioritize(item)) if prioritize else False, score, index, item))
    if not any(entry[0] or entry[1] for entry in scored):
        return list(items)[:limit]
    scored.sort(key=lambda entry: (not entry[0], -entry[1], entry[2]))
    return [entry[3] for entry in scored][:limit]


# ---- 事实台账（Fact Ledger） ----
# 记忆单元从「工具调用输出」升级为「带出处的事实三元组」：
# (entity=文档版本, attribute=字段, value) + 证据定位 + 来源工具 + 依赖标记。
# 只从结构化工具输出确定性抽取——模型自由文本永不入账（防记忆投毒）。
# 事实级去重跨越工具签名：不同工具产出同一事实时累计佐证数；同一实体同一
# 属性出现不同取值时标记 conflict 并发事件（多方证据不一致是审查关注点）。


def compact_llm_payload(payload: Any, *, max_string: int = 600, max_items: int = 40) -> Any:
    """递归压缩进入模型上下文的工具结果，控制长字符串和超长列表。"""
    if isinstance(payload, str):
        return payload if len(payload) <= max_string else payload[:max_string] + "…(截断)"
    if isinstance(payload, dict):
        return {
            key: _r().compact_llm_payload(value, max_string=max_string, max_items=max_items)
            for key, value in payload.items()
        }
    if isinstance(payload, list):
        compacted = [
            _r().compact_llm_payload(item, max_string=max_string, max_items=max_items)
            for item in payload[:max_items]
        ]
        if len(payload) > max_items:
            compacted.append(f"…(共 {len(payload)} 项，已截断)")
        return compacted
    return payload

