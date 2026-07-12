from __future__ import annotations


MAX_TASK_PRIORITY = 10


def broker_priority(semantic_priority: int) -> int:
    """Map larger-is-sooner business priorities to Kombu Redis priorities."""
    value = int(semantic_priority)
    if value < 0 or value > MAX_TASK_PRIORITY:
        raise ValueError(
            f"semantic task priority must be between 0 and {MAX_TASK_PRIORITY}: {value}"
        )
    # Kombu's Redis transport consumes lower numeric priorities first.
    return MAX_TASK_PRIORITY - value
