"""Durable provider selection for an OCR job; callers hold the job execution lock."""
from datetime import UTC, datetime
import os
from typing import Any


class MinerUPendingTimeout(RuntimeError):
    code = "MINERU_PENDING_TIMEOUT"
    retryable = False


def pending_timeout_seconds() -> float:
    try:
        return max(0, float(os.getenv("AICHECK_MINERU_PENDING_TIMEOUT_SECONDS", "60")))
    except ValueError:
        return 60


def observe_provider(job: dict[str, Any], state: str, *, now: datetime | None = None) -> bool:
    """Return whether the current continuous pending interval exhausted its budget."""
    if job.get("activeProvider") == "qwen":
        return True
    if state != "pending":
        job.pop("pendingSince", None)
        return False
    current = now or datetime.now(UTC)
    if not job.get("pendingSince"):
        job["pendingSince"] = current.isoformat()
    try:
        since = datetime.fromisoformat(job["pendingSince"])
        if since.tzinfo is None:
            since = since.replace(tzinfo=UTC)
    except (TypeError, ValueError):
        since = current
        job["pendingSince"] = current.isoformat()
    return (current - since).total_seconds() >= pending_timeout_seconds()


def select_qwen(job: dict[str, Any]) -> None:
    if job.get("activeProvider") == "qwen":
        return
    job["activeProvider"] = "qwen"
    job["fallback"] = {
        "from": "mineru", "to": "qwen", "reason": "MINERU_PENDING_TIMEOUT",
        "switchedAt": datetime.now(UTC).isoformat(),
        "providerTaskId": job.get("providerTaskId"),
        "localWaitStopped": True, "remoteCancellation": "unsupported",
    }
