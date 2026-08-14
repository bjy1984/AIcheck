from __future__ import annotations

from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError

with workflow.unsafe.imports_passed_through():
    from apps.review_worker.activities import (
        apply_review_workflow_command_activity,
        run_review_graph_activity,
    )


@workflow.defn(name="ReviewRunWorkflow")
class ReviewRunWorkflow:
    def __init__(self) -> None:
        self._state: dict[str, Any] = {"status": "created", "currentStep": "created"}
        self._tenant_id: str | None = None
        self._review_run_id: str | None = None
        self._human_input_command: dict[str, Any] | None = None
        self._human_decision: dict[str, Any] | None = None
        self._cancel_command: dict[str, Any] | None = None
        self._processed_command_ids: set[str] = set()

    @workflow.run
    async def run(self, execution: dict[str, Any] | str) -> dict[str, Any]:
        legacy_execution = not isinstance(execution, dict)
        if isinstance(execution, dict):
            tenant_id = str(execution.get("tenantId") or "")
            review_run_id = str(execution.get("reviewRunId") or "")
        else:
            # Backward compatibility for workflows started before tenant envelopes were introduced.
            tenant_id = "TENANT-DEFAULT"
            review_run_id = str(execution or "")
        if not tenant_id or not review_run_id:
            raise ApplicationError(
                "ReviewRun workflow input is missing tenantId or reviewRunId.",
                type="REVIEW_WORKFLOW_INPUT_INVALID",
                non_retryable=True,
            )
        self._tenant_id = tenant_id
        self._review_run_id = review_run_id
        activity_input = {"tenantId": tenant_id, "reviewRunId": review_run_id}
        graph_activity_input: dict[str, str] | str = review_run_id if legacy_execution else activity_input
        self._state = {
            **activity_input,
            "status": "running",
            "currentStep": "run_review_graph",
        }
        graph_result = await workflow.execute_activity(
            run_review_graph_activity,
            graph_activity_input,
            start_to_close_timeout=timedelta(minutes=20),
            retry_policy=RetryPolicy(
                initial_interval=timedelta(seconds=10),
                backoff_coefficient=2.0,
                maximum_interval=timedelta(minutes=2),
                maximum_attempts=3,
                non_retryable_error_types=[
                    "ReviewValidationError",
                    "ReviewBudgetExceeded",
                    "ReviewGroundingError",
                ],
            ),
            task_queue=workflow.info().task_queue,
        )
        while graph_result.get("status") == "waiting_human_input":
            self._state = {
                **activity_input,
                "status": "waiting_human_input",
                "currentStep": "waiting_human_input",
                "humanInputTaskId": graph_result.get("humanInputTaskId"),
            }
            await workflow.wait_condition(
                lambda: self._human_input_command is not None or self._cancel_command is not None
            )
            command = dict(self._cancel_command or self._human_input_command or {})
            application = await self._apply_workflow_command(
                command,
                tenant_id=tenant_id,
                review_run_id=review_run_id,
                legacy_execution=legacy_execution,
            )
            if self._cancel_command is not None:
                self._state["status"] = str(application.get("reviewRunStatus") or "cancelled")
                self._state["currentStep"] = "completed"
                return {
                    "reviewRunId": review_run_id,
                    "status": self._state["status"],
                    "application": application,
                    "graph": graph_result,
                }
            self._human_input_command = None
            self._state = {
                **activity_input,
                "status": "resuming",
                "currentStep": "run_review_graph",
            }
            graph_result = await workflow.execute_activity(
                run_review_graph_activity,
                graph_activity_input,
                start_to_close_timeout=timedelta(minutes=20),
                retry_policy=RetryPolicy(
                    initial_interval=timedelta(seconds=10),
                    backoff_coefficient=2.0,
                    maximum_interval=timedelta(minutes=2),
                    maximum_attempts=3,
                    non_retryable_error_types=[
                        "ReviewValidationError",
                        "ReviewBudgetExceeded",
                        "ReviewGroundingError",
                    ],
                ),
                task_queue=workflow.info().task_queue,
            )
        if graph_result.get("status") != "waiting_human_review":
            raise ApplicationError(
                "ReviewRun activity returned without reaching human review.",
                type="REVIEW_ACTIVITY_INCOMPLETE",
                non_retryable=True,
            )
        self._state = {
            **activity_input,
            "status": "waiting_human_review",
            "currentStep": "waiting_human_review",
        }
        await workflow.wait_condition(lambda: self._human_decision is not None or self._cancel_command is not None)
        command = dict(self._cancel_command or self._human_decision or {})
        application = await self._apply_workflow_command(
            command,
            tenant_id=tenant_id,
            review_run_id=review_run_id,
            legacy_execution=legacy_execution,
        )
        self._state["status"] = str(application.get("reviewRunStatus") or application.get("status") or "applied")
        self._state["currentStep"] = "completed"
        return {
            "reviewRunId": review_run_id,
            "status": self._state["status"],
            "application": application,
            "graph": graph_result,
        }

    async def _apply_workflow_command(
        self,
        command: dict[str, Any],
        *,
        tenant_id: str,
        review_run_id: str,
        legacy_execution: bool,
    ) -> dict[str, Any]:
        if not legacy_execution:
            command_tenant_id = str(command.get("tenantId") or tenant_id)
            command_review_run_id = str(command.get("reviewRunId") or review_run_id)
            if command_tenant_id != tenant_id or command_review_run_id != review_run_id:
                raise ApplicationError(
                    "ReviewRun workflow command does not match the workflow tenant or aggregate.",
                    type="REVIEW_WORKFLOW_COMMAND_SCOPE_MISMATCH",
                    non_retryable=True,
                )
            command["tenantId"] = tenant_id
            command["reviewRunId"] = review_run_id
        self._state["currentStep"] = "apply_workflow_command"
        return await workflow.execute_activity(
            apply_review_workflow_command_activity,
            command,
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=RetryPolicy(
                initial_interval=timedelta(seconds=5),
                backoff_coefficient=2.0,
                maximum_interval=timedelta(seconds=30),
                maximum_attempts=5,
                non_retryable_error_types=[
                    "REVIEW_WORKFLOW_COMMAND_INVALID",
                    "REVIEW_WORKFLOW_COMMAND_REJECTED",
                    "REVIEW_RUN_NOT_FOUND",
                ],
            ),
            task_queue=workflow.info().task_queue,
        )

    @workflow.signal
    async def submit_human_input(self, human_input: dict[str, Any]) -> None:
        command_id = str(human_input.get("commandId") or "")
        if command_id and command_id in self._processed_command_ids:
            return
        if command_id:
            self._processed_command_ids.add(command_id)
        if (
            self._human_input_command is None
            and self._human_decision is None
            and self._cancel_command is None
        ):
            self._human_input_command = human_input

    @workflow.signal
    async def submit_human_decision(self, decision: dict[str, Any]) -> None:
        command_id = str(decision.get("commandId") or "")
        if command_id and command_id in self._processed_command_ids:
            return
        if command_id:
            self._processed_command_ids.add(command_id)
        if self._human_input_command is None and self._human_decision is None and self._cancel_command is None:
            self._human_decision = decision

    @workflow.signal
    async def cancel_review(self, reason: Any = None) -> None:
        payload = reason if isinstance(reason, dict) else {"reasonHash": reason}
        command_id = str(payload.get("commandId") or "")
        if command_id and command_id in self._processed_command_ids:
            return
        if command_id:
            self._processed_command_ids.add(command_id)
        if self._human_decision is None and self._cancel_command is None:
            self._cancel_command = payload
            self._state["cancelReasonHash"] = payload.get("reasonHash")

    @workflow.query
    def get_review_state(self) -> dict[str, Any]:
        return dict(self._state)

    @workflow.query
    def get_current_step(self) -> str:
        return str(self._state.get("currentStep") or "unknown")
