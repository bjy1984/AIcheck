"""审查编排包的公开 API。

这里用 PEP 562 惰性导出，而不是在 __init__ 顶部直接 from .dispatcher import ...。
原因是急切导入会让「导入一个叶子子模块」变成「导入整个包」：

    libs.review_tools.r13_tools
      → from libs.review_orchestrator.deterministic_tools import check
        → 先执行 libs/review_orchestrator/__init__.py
          → dispatcher → execution → runtime_tools
            → from libs.review_tools import BUSINESS_TOOL_DESCRIPTORS  ← 此时它还没初始化完

结果是单独 `import libs.review_tools` 直接 ImportError，调用方必须先 import
libs.review_orchestrator 才能用——一个没有任何提示的隐式顺序依赖。测试文件里
为此写过 `import libs.review_orchestrator  # noqa` 的规避行。

惰性导出后 from libs.review_orchestrator import X 的用法完全不变，
变的只是「拿 X 时才真正导入它所在的子模块」。
"""

from __future__ import annotations

from typing import Any

# 名字 → 所在子模块。新增导出时同步这张表。
_EXPORTS: dict[str, str] = {
    "with_certificate_fact_builders": "certificate_facts",
    "ALLOWED_AGENT_TOOLS": "execution",
    "REVIEW_GRAPH_EDGES": "execution",
    "REVIEW_GRAPH_STEPS": "execution",
    "apply_r12_human_input_for_review_run": "execution",
    "apply_review_human_input_for_review_run": "execution",
    "build_review_orchestration_scorecard": "readiness",
    "clone_review_run_for_replay": "execution",
    "create_review_run_from_ai_run": "execution",
    "dispatch_existing_review_run": "dispatcher",
    "dispatch_review_run": "dispatcher",
    "dispatch_runtime_tool": "runtime_tools",
    "execute_agent_tool": "execution",
    "execute_review_run_inline": "execution",
    "graph_view_for_review_run": "execution",
    "human_decision_for_review_run": "execution",
    "review_orchestration_mode": "dispatcher",
    "review_run_audit_trace": "execution",
    "review_run_state_records": "execution",
    "review_run_timeline": "execution",
    "review_run_view": "execution",
    "runtime_tool_catalog": "runtime_tools",
    "signal_review_run_cancel": "dispatcher",
    "signal_review_run_human_decision": "dispatcher",
    "signal_review_run_human_input": "dispatcher",
}

__all__ = [
    "with_certificate_fact_builders",
    "ALLOWED_AGENT_TOOLS",
    "REVIEW_GRAPH_EDGES",
    "REVIEW_GRAPH_STEPS",
    "apply_r12_human_input_for_review_run",
    "apply_review_human_input_for_review_run",
    "build_review_orchestration_scorecard",
    "clone_review_run_for_replay",
    "create_review_run_from_ai_run",
    "dispatch_existing_review_run",
    "dispatch_review_run",
    "dispatch_runtime_tool",
    "execute_agent_tool",
    "execute_review_run_inline",
    "graph_view_for_review_run",
    "human_decision_for_review_run",
    "review_orchestration_mode",
    "review_run_audit_trace",
    "review_run_state_records",
    "review_run_timeline",
    "review_run_view",
    "runtime_tool_catalog",
    "signal_review_run_cancel",
    "signal_review_run_human_decision",
    "signal_review_run_human_input",
]


def __getattr__(name: str) -> Any:
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from importlib import import_module

    return getattr(import_module(f".{module_name}", __name__), name)


def __dir__() -> list[str]:
    return sorted(__all__)
