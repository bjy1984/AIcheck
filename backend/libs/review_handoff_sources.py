"""Inspect both endpoints' frozen source freshness without rewriting handoff history."""

from __future__ import annotations

from typing import Any

from libs.review_document_scope import validate_document_sources


def inspect_handoff_sources(runs: list[dict[str, Any]], state: dict[str, Any]) -> dict[str, Any]:
    if len(runs) != 2:
        raise ValueError("handoff_two_endpoints_required")
    checks = []
    for endpoint, run in zip(("source", "target"), runs, strict=True):
        item = {"endpoint": endpoint, "runId": run.get("reviewRunId") or run.get("id")}
        try:
            validate_document_sources(run, state)
            snapshot = run.get("documentScopeSnapshot") or {}
            item["status"] = (
                "current" if snapshot.get("sourceFingerprint") is not None else "unverified"
            )
        except (TypeError, ValueError) as exc:
            item.update(status="stale_or_invalid", reason=str(exc))
        checks.append(item)
    stale = any(item["status"] == "stale_or_invalid" for item in checks)
    return {
        "status": "stale_or_invalid"
        if stale
        else "current"
        if all(item["status"] == "current" for item in checks)
        else "unverified",
        "endpoints": checks,
        "requiresRevalidation": stale,
        "affectedTargetRunId": (runs[1].get("reviewRunId") or runs[1].get("id")) if stale else None,
        "authoritative": False,
    }
