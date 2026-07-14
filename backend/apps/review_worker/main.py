from __future__ import annotations

import asyncio
import os

from temporalio.client import Client
from temporalio.worker import Worker

from apps.review_worker.activities import apply_review_workflow_command_activity, run_review_graph_activity
from apps.review_worker.outbox import database_url, run_audit_anchor_loop, run_outbox_relay, run_worker_heartbeat_loop
from apps.review_worker.workflows import ReviewRunWorkflow


async def main() -> None:
    address = os.getenv("TEMPORAL_ADDRESS", "localhost:7233")
    namespace = os.getenv("TEMPORAL_NAMESPACE", "default")
    task_queue = os.getenv("AICHECK_REVIEW_WORKFLOW_TASK_QUEUE", "review.workflow")
    client = await Client.connect(address, namespace=namespace)
    worker = Worker(
        client,
        task_queue=task_queue,
        workflows=[ReviewRunWorkflow],
        activities=[run_review_graph_activity, apply_review_workflow_command_activity],
        max_concurrent_activities=max(
            1,
            int(os.getenv("AICHECK_REVIEW_WORKER_MAX_CONCURRENT_ACTIVITIES", "1")),
        ),
    )
    if not database_url():
        await worker.run()
        return
    worker_task = asyncio.create_task(worker.run(), name="temporal-review-worker")
    relay_task = asyncio.create_task(run_outbox_relay(client), name="review-workflow-outbox-relay")
    anchor_task = asyncio.create_task(run_audit_anchor_loop(), name="audit-chain-anchor-writer")
    heartbeat_task = asyncio.create_task(run_worker_heartbeat_loop(), name="review-worker-heartbeat")
    tasks = {worker_task, relay_task, anchor_task, heartbeat_task}
    try:
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            if task.cancelled():
                raise RuntimeError(f"Supervised worker task was cancelled unexpectedly: {task.get_name()}")
            error = task.exception()
            if error is not None:
                raise error
            if task is not worker_task:
                raise RuntimeError(f"Supervised worker task stopped unexpectedly: {task.get_name()}")
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


if __name__ == "__main__":
    asyncio.run(main())
