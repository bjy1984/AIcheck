from __future__ import annotations

from temporalio import activity

from libs.db.repository import flush_state_records, load_state
from libs.review_orchestrator.execution import execute_review_run_inline, review_run_state_records


@activity.defn(name="run_review_graph_activity")
async def run_review_graph_activity(review_run_id: str) -> dict:
    activity.heartbeat({"reviewRunId": review_run_id, "stage": "loading_state"})
    load_state()
    activity.heartbeat({"reviewRunId": review_run_id, "stage": "executing_graph"})
    result = execute_review_run_inline(review_run_id)
    flush_state_records(review_run_state_records(review_run_id))
    return result
