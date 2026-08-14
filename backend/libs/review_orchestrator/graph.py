from __future__ import annotations

import os
from collections.abc import Callable
from contextlib import nullcontext
from typing import Any


def langgraph_disabled() -> bool:
    return os.getenv("AICHECK_LANGGRAPH_DISABLE", "false").strip().lower() == "true"


def execute_review_graph(
    review_run: dict[str, Any],
    context: dict[str, Any],
    *,
    steps: list[dict[str, Any]],
    run_step: Callable[[dict[str, Any], str, dict[str, Any]], dict[str, Any]],
    mark_graph_node: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    if langgraph_disabled():
        return execute_manual_graph(
            review_run,
            context,
            steps=steps,
            run_step=run_step,
            mark_graph_node=mark_graph_node,
            reason="AICHECK_LANGGRAPH_DISABLE=true",
        )
    try:
        from langgraph.graph import END, START, StateGraph
    except Exception as exc:
        return execute_manual_graph(
            review_run,
            context,
            steps=steps,
            run_step=run_step,
            mark_graph_node=mark_graph_node,
            reason=f"{exc.__class__.__name__}: {exc}",
        )

    graph = StateGraph(dict)
    for step in steps:
        graph.add_node(step["key"], make_langgraph_node(step["key"], review_run, run_step, mark_graph_node))
    graph.add_edge(START, steps[0]["key"])
    for index in range(len(steps) - 1):
        graph.add_edge(steps[index]["key"], steps[index + 1]["key"])
    graph.add_edge(steps[-1]["key"], END)
    checkpointer_context, checkpointer_mode, checkpointer_reason = langgraph_checkpointer_context()
    with checkpointer_context as checkpointer:
        if checkpointer is not None and os.getenv("AICHECK_LANGGRAPH_CHECKPOINT_SETUP", "false").strip().lower() == "true":
            setup = getattr(checkpointer, "setup", None)
            if callable(setup):
                setup()
        compiled = graph.compile(checkpointer=checkpointer) if checkpointer is not None else graph.compile()
        output_state = compiled.invoke(
            {
                "context": context,
                "graphNodeDetails": {},
            },
            config={"configurable": {"thread_id": review_run["reviewRunId"]}},
        )
    # 节点返回的 state["context"] 通常就是传入的同一个对象；先取副本再清空，
    # 否则 clear() 会把待回写的数据一并抹掉，调用方拿到空 context。
    final_context = dict(output_state.get("context") or {})
    context.clear()
    context.update(final_context)
    return {
        "runner": "langgraph",
        "available": True,
        "fallback": False,
        "checkpointer": checkpointer_mode,
        "checkpointerReason": checkpointer_reason,
        "nodeCount": len(steps),
    }


def make_langgraph_node(
    node_key: str,
    review_run: dict[str, Any],
    run_step: Callable[[dict[str, Any], str, dict[str, Any]], dict[str, Any]],
    mark_graph_node: Callable[..., dict[str, Any]],
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def node(state: dict[str, Any]) -> dict[str, Any]:
        context = state.setdefault("context", {})
        review_run["currentStep"] = node_key
        mark_graph_node(review_run["reviewRunId"], node_key, "running")
        try:
            details = run_step(review_run, node_key, context)
        except Exception as exc:
            mark_graph_node(
                review_run["reviewRunId"],
                node_key,
                "failed",
                details={"error": str(exc), "errorType": exc.__class__.__name__},
            )
            raise
        mark_graph_node(review_run["reviewRunId"], node_key, "succeeded", details=details)
        state.setdefault("graphNodeDetails", {})[node_key] = details
        state["context"] = context
        return state

    return node


def langgraph_checkpointer_context() -> tuple[Any, str, str | None]:
    dsn = os.getenv("LANGGRAPH_CHECKPOINT_DSN", "").strip()
    if not dsn:
        return nullcontext(None), "none", "LANGGRAPH_CHECKPOINT_DSN is not configured"
    if os.getenv("AICHECK_LANGGRAPH_CHECKPOINT_DISABLE", "false").strip().lower() == "true":
        return nullcontext(None), "disabled", "AICHECK_LANGGRAPH_CHECKPOINT_DISABLE=true"
    try:
        from langgraph.checkpoint.postgres import PostgresSaver
    except Exception as exc:
        return nullcontext(None), "unavailable", f"{exc.__class__.__name__}: {exc}"
    try:
        context = PostgresSaver.from_conn_string(dsn)
    except Exception as exc:
        return nullcontext(None), "failed_to_create", f"{exc.__class__.__name__}: {exc}"
    if not hasattr(context, "__enter__"):
        context = nullcontext(context)
    return context, "postgres", None


def execute_manual_graph(
    review_run: dict[str, Any],
    context: dict[str, Any],
    *,
    steps: list[dict[str, Any]],
    run_step: Callable[[dict[str, Any], str, dict[str, Any]], dict[str, Any]],
    mark_graph_node: Callable[..., dict[str, Any]],
    reason: str | None = None,
) -> dict[str, Any]:
    for step in steps:
        node_key = step["key"]
        review_run["currentStep"] = node_key
        mark_graph_node(review_run["reviewRunId"], node_key, "running")
        try:
            details = run_step(review_run, node_key, context)
        except Exception as exc:
            mark_graph_node(
                review_run["reviewRunId"],
                node_key,
                "failed",
                details={"error": str(exc), "errorType": exc.__class__.__name__},
            )
            raise
        mark_graph_node(review_run["reviewRunId"], node_key, "succeeded", details=details)
    return {
        "runner": "manual",
        "available": False,
        "fallback": True,
        "fallbackReason": reason or "langgraph unavailable",
        "nodeCount": len(steps),
    }
