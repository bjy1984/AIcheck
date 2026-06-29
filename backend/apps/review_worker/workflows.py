from __future__ import annotations

from datetime import timedelta
from typing import Any

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from apps.review_worker.activities import run_review_graph_activity


@workflow.defn(name="ReviewRunWorkflow")
class ReviewRunWorkflow:
    def __init__(self) -> None:
        self._state: dict[str, Any] = {"status": "created", "currentStep": "created"}
        self._human_decision: dict[str, Any] | None = None
        self._cancel_requested = False

    @workflow.run
    async def run(self, review_run_id: str) -> dict[str, Any]:
        self._state = {"reviewRunId": review_run_id, "status": "running", "currentStep": "run_review_graph"}
        graph_result = await workflow.execute_activity(
            run_review_graph_activity,
            review_run_id,
            start_to_close_timeout=timedelta(minutes=20),
            retry_policy=None,
            task_queue=workflow.info().task_queue,
        )
        self._state = {"reviewRunId": review_run_id, "status": "waiting_human_review", "currentStep": "waiting_human_review"}
        await workflow.wait_condition(lambda: self._human_decision is not None or self._cancel_requested)
        if self._cancel_requested:
            self._state["status"] = "cancelled"
            return {"reviewRunId": review_run_id, "status": "cancelled", "graph": graph_result}
        decision = self._human_decision or {}
        self._state["status"] = decision.get("status") or "human_decision_received"
        return {"reviewRunId": review_run_id, "status": self._state["status"], "decision": decision, "graph": graph_result}

    @workflow.signal
    async def submit_human_decision(self, decision: dict[str, Any]) -> None:
        self._human_decision = decision

    @workflow.signal
    async def cancel_review(self, reason: str | None = None) -> None:
        self._cancel_requested = True
        self._state["cancelReason"] = reason

    @workflow.query
    def get_review_state(self) -> dict[str, Any]:
        return dict(self._state)

    @workflow.query
    def get_current_step(self) -> str:
        return str(self._state.get("currentStep") or "unknown")
