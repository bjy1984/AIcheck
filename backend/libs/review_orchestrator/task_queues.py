from __future__ import annotations

import os


def review_task_queues() -> dict[str, str]:
    return {
        "workflow": os.getenv("AICHECK_REVIEW_WORKFLOW_TASK_QUEUE", "review.workflow"),
        "graph": os.getenv("AICHECK_REVIEW_GRAPH_TASK_QUEUE", "review.graph"),
        "llm": os.getenv("AICHECK_REVIEW_LLM_TASK_QUEUE", "review.llm"),
        "retrieval": os.getenv("AICHECK_REVIEW_RETRIEVAL_TASK_QUEUE", "review.retrieval"),
        "validation": os.getenv("AICHECK_REVIEW_VALIDATION_TASK_QUEUE", "review.validation"),
    }
