from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any

from libs.contracts.responses import server_time


def _stable_id(prefix: str, value: Any) -> str:
    raw = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        default=str,
        separators=(",", ":"),
    )
    return f"{prefix}-{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:16].upper()}"


def persist_project_analysis_node_results(
    state: dict[str, Any],
    project_run: dict[str, Any],
    validated_output: dict[str, Any],
) -> list[dict[str, Any]]:
    project_run_id = str(project_run.get("projectAnalysisRunId") or "")
    rows = state.setdefault("review_runs", [])
    persisted: list[dict[str, Any]] = []
    for review in validated_output.get("nodeReviews") or []:
        node_id = int(review.get("nodeId") or 0)
        review_run_id = _stable_id(
            "RRUN-PA",
            {"projectAnalysisRunId": project_run_id, "nodeId": node_id},
        )
        existing = next(
            (
                row
                for row in rows
                if str(row.get("reviewRunId") or row.get("id") or "")
                == review_run_id
            ),
            None,
        )
        if existing:
            persisted.append(existing)
            continue
        finding_drafts: list[dict[str, Any]] = []
        for index, source_finding in enumerate(review.get("findings") or [], start=1):
            finding_drafts.append(
                {
                    **deepcopy(source_finding),
                    "id": _stable_id(
                        "FND-DRAFT-PA",
                        {"reviewRunId": review_run_id, "index": index},
                    ),
                    "reviewRunId": review_run_id,
                    "projectAnalysisRunId": project_run_id,
                    "projectId": project_run.get("projectId"),
                    "nodeId": node_id,
                    "requiresHumanConfirmation": True,
                    "status": "pending_human_review",
                    "createdAt": server_time(),
                }
            )
        record = {
            "id": review_run_id,
            "reviewRunId": review_run_id,
            "tenantId": project_run.get("tenantId"),
            "projectId": project_run.get("projectId"),
            "nodeId": node_id,
            "projectAnalysisRunId": project_run_id,
            "projectAnalysisSnapshotId": project_run.get(
                "projectAnalysisSnapshotId"
            ),
            "sharedModelAttemptId": project_run.get("modelAttemptId"),
            "triggerType": "manual_full_project_analysis",
            "reviewMode": "gap_precheck",
            "advisoryOnly": True,
            "status": "waiting_human_review",
            "currentStep": "waiting_human_review",
            "reviewResult": review.get("reviewResult"),
            "findingDrafts": finding_drafts,
            "outputHash": _stable_id("OUTPUT", finding_drafts).replace("OUTPUT-", "sha256:"),
            "createdAt": server_time(),
            "finishedAt": server_time(),
            "updatedAt": server_time(),
            "revision": 1,
        }
        rows.append(record)
        persisted.append(record)
    project_run["derivedReviewRunIds"] = [row["reviewRunId"] for row in persisted]
    project_run["persistedNodeCount"] = len(persisted)
    project_run["updatedAt"] = server_time()
    return persisted
