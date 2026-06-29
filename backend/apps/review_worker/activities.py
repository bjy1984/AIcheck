from __future__ import annotations

from temporalio import activity

from libs.db.repository import load_state, flush_state
from libs.review_orchestrator.execution import execute_review_run_inline


@activity.defn(name="run_review_graph_activity")
async def run_review_graph_activity(review_run_id: str) -> dict:
    load_state()
    result = execute_review_run_inline(review_run_id)
    flush_state()
    return result
