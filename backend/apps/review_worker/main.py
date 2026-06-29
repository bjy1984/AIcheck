from __future__ import annotations

import asyncio
import os

from temporalio.client import Client
from temporalio.worker import Worker

from apps.review_worker.activities import run_review_graph_activity
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
        activities=[run_review_graph_activity],
    )
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
