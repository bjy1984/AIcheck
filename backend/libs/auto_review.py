from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from libs.contracts.responses import server_time
from libs.review_evidence import active_node_document_versions, build_evidence_snapshot


TRIGGER_MODES = {"ocr_mounted", "daily_schedule"}
AUTO_REVIEW_MODE = "gap_precheck"
DEFAULT_TIMEZONE = "Asia/Shanghai"
DEFAULT_DAILY_TIME = "02:00"
DEFAULT_DEBOUNCE_SECONDS = 300
MAX_DEBOUNCE_SECONDS = 3600


def _stable_id(prefix: str, value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16].upper()
    return f"{prefix}-{digest}"


def default_auto_review_policy(project_id: str, tenant_id: str) -> dict[str, Any]:
    now = server_time()
    return {
        "id": _stable_id("ARP", {"tenantId": tenant_id, "projectId": project_id}),
        "tenantId": str(tenant_id),
        "projectId": str(project_id),
        "enabled": False,
        "triggerModes": sorted(TRIGGER_MODES),
        "dailyTime": DEFAULT_DAILY_TIME,
        "timezone": DEFAULT_TIMEZONE,
        "reviewMode": AUTO_REVIEW_MODE,
        "debounceSeconds": DEFAULT_DEBOUNCE_SECONDS,
        "revision": 1,
        "createdAt": now,
        "updatedAt": now,
    }


def validate_auto_review_policy(
    payload: dict[str, Any], existing: dict[str, Any]
) -> dict[str, Any]:
    enabled = bool(payload.get("enabled", existing.get("enabled", False)))
    raw_modes = payload.get("triggerModes", existing.get("triggerModes") or sorted(TRIGGER_MODES))
    trigger_modes = sorted({str(item) for item in raw_modes or [] if str(item)})
    if any(mode not in TRIGGER_MODES for mode in trigger_modes) or (enabled and not trigger_modes):
        raise ValueError("unsupported or empty trigger mode")

    daily_time = str(payload.get("dailyTime", existing.get("dailyTime") or DEFAULT_DAILY_TIME))
    try:
        datetime.strptime(daily_time, "%H:%M")
    except ValueError as exc:
        raise ValueError("dailyTime must use HH:MM") from exc

    timezone = str(payload.get("timezone", existing.get("timezone") or DEFAULT_TIMEZONE))
    try:
        ZoneInfo(timezone)
    except ZoneInfoNotFoundError as exc:
        raise ValueError("timezone is invalid") from exc

    try:
        debounce_seconds = int(
            payload.get("debounceSeconds", existing.get("debounceSeconds", DEFAULT_DEBOUNCE_SECONDS))
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("debounceSeconds must be an integer") from exc
    if debounce_seconds < 0 or debounce_seconds > MAX_DEBOUNCE_SECONDS:
        raise ValueError("debounceSeconds must be between 0 and 3600")

    now = server_time()
    return {
        **existing,
        "tenantId": str(existing.get("tenantId") or ""),
        "projectId": str(existing.get("projectId") or ""),
        "enabled": enabled,
        "triggerModes": trigger_modes,
        "dailyTime": daily_time,
        "timezone": timezone,
        "reviewMode": AUTO_REVIEW_MODE,
        "debounceSeconds": debounce_seconds,
        "revision": int(existing.get("revision") or 0) + 1,
        "updatedAt": now,
    }


def policy_allows_trigger(policy: dict[str, Any], trigger_type: str) -> bool:
    return bool(
        policy.get("enabled") is True
        and str(trigger_type) in TRIGGER_MODES
        and str(trigger_type) in {str(item) for item in policy.get("triggerModes") or []}
    )


def auto_review_candidate_key(
    tenant_id: str,
    project_id: str,
    node_id: int,
    evidence_snapshot_hash: str,
    policy_revision: int,
) -> str:
    return _stable_id(
        "ARCKEY",
        {
            "tenantId": str(tenant_id),
            "projectId": str(project_id),
            "nodeId": int(node_id),
            "evidenceSnapshotHash": str(evidence_snapshot_hash),
            "policyRevision": int(policy_revision),
        },
    )


def upsert_auto_review_candidate(
    state: dict[str, Any],
    *,
    tenant_id: str,
    project_id: str,
    node_id: int,
    evidence_snapshot_hash: str,
    policy_revision: int,
    trigger_type: str,
) -> tuple[dict[str, Any], bool]:
    if str(trigger_type) not in TRIGGER_MODES:
        raise ValueError("unsupported trigger mode")
    candidate_key = auto_review_candidate_key(
        tenant_id,
        project_id,
        node_id,
        evidence_snapshot_hash,
        policy_revision,
    )
    rows = state.setdefault("auto_review_candidates", [])
    existing = next(
        (row for row in rows if str(row.get("candidateKey") or "") == candidate_key),
        None,
    )
    if existing:
        trigger_types = {str(item) for item in existing.get("triggerTypes") or [] if item}
        trigger_types.add(str(trigger_type))
        existing["triggerTypes"] = sorted(trigger_types)
        existing["updatedAt"] = server_time()
        return existing, False

    now = server_time()
    candidate = {
        "id": candidate_key.replace("ARCKEY-", "ARC-", 1),
        "candidateKey": candidate_key,
        "tenantId": str(tenant_id),
        "projectId": str(project_id),
        "nodeId": int(node_id),
        "evidenceSnapshotHash": str(evidence_snapshot_hash),
        "policyRevision": int(policy_revision),
        "triggerType": str(trigger_type),
        "triggerTypes": [str(trigger_type)],
        "status": "pending",
        "attemptCount": 0,
        "availableAt": now,
        "createdAt": now,
        "updatedAt": now,
    }
    rows.append(candidate)
    return candidate, True


def active_mounted_node_ids(state: dict[str, Any], project_id: str) -> list[int]:
    candidate_ids = sorted(
        {
            int(row.get("nodeId") or 0)
            for row in state.get("node_evidence_links") or []
            if isinstance(row, dict)
            and str(row.get("projectId") or "") == str(project_id)
            and str(row.get("manualStatus") or "").lower() != "rejected"
            and int(row.get("nodeId") or 0) > 0
        }
    )
    return [
        node_id
        for node_id in candidate_ids
        if active_node_document_versions(state, project_id, node_id)
    ]


def current_node_snapshot(
    state: dict[str, Any],
    project_id: str,
    node_id: int,
    *,
    rule_version: str = "auto-review-rule-v1",
    clause_package_version: str = "auto-review-clauses-v1",
    prompt_version: str = "project-auto-review-v1",
    strategy_version: str = "node-review-strategy-v1",
) -> dict[str, Any]:
    return build_evidence_snapshot(
        state,
        project_id,
        node_id,
        rule_version=rule_version,
        clause_package_version=clause_package_version,
        prompt_version=prompt_version,
        strategy_version=strategy_version,
    )


SUCCESSFUL_NODE_REVIEW_STATUSES = {
    "waiting_human_review",
    "accepted_by_human",
    "edited_by_human",
    "rejected_by_human",
    "completed",
    "完成",
}


def _latest_successful_snapshot_hash(
    state: dict[str, Any], project_id: str, node_id: int
) -> str | None:
    rows = [
        row
        for collection in ("review_runs", "ai_runs")
        for row in state.get(collection) or []
        if isinstance(row, dict)
        and str(row.get("projectId") or "") == str(project_id)
        and int(row.get("nodeId") or 0) == int(node_id)
        and str(row.get("status") or "") in SUCCESSFUL_NODE_REVIEW_STATUSES
        and row.get("evidenceSnapshotHash")
    ]
    if not rows:
        return None
    rows.sort(
        key=lambda row: str(
            row.get("finishedAt") or row.get("updatedAt") or row.get("createdAt") or ""
        ),
        reverse=True,
    )
    return str(rows[0].get("evidenceSnapshotHash") or "") or None


def dirty_nodes_for_project(
    state: dict[str, Any],
    project_id: str,
    *,
    node_ids: list[int] | None = None,
) -> list[dict[str, Any]]:
    selected_ids = sorted(
        set(node_ids if node_ids is not None else active_mounted_node_ids(state, project_id))
    )
    dirty: list[dict[str, Any]] = []
    for node_id in selected_ids:
        snapshot = current_node_snapshot(state, project_id, int(node_id))
        if not snapshot.get("documentVersions"):
            continue
        previous_hash = _latest_successful_snapshot_hash(state, project_id, int(node_id))
        if previous_hash == snapshot["snapshotHash"]:
            continue
        dirty.append(
            {
                "nodeId": int(node_id),
                "evidenceSnapshotId": snapshot["evidenceSnapshotId"],
                "evidenceSnapshotHash": snapshot["snapshotHash"],
                "previousEvidenceSnapshotHash": previous_hash,
                "snapshot": snapshot,
            }
        )
    return dirty


def create_project_review_run(
    state: dict[str, Any],
    *,
    tenant_id: str,
    project_id: str,
    trigger_type: str,
    policy: dict[str, Any],
    node_ids: list[int],
) -> dict[str, Any]:
    now = server_time()
    project_run_id = f"PRRUN-{uuid4().hex[:12].upper()}"
    record = {
        "id": project_run_id,
        "projectReviewRunId": project_run_id,
        "tenantId": str(tenant_id),
        "projectId": str(project_id),
        "triggerType": str(trigger_type),
        "policySnapshot": json.loads(json.dumps(policy, ensure_ascii=False, default=str)),
        "autoReviewPolicyRevision": int(policy.get("revision") or 1),
        "expectedNodeIds": sorted({int(node_id) for node_id in node_ids if int(node_id) > 0}),
        "childAiRunIds": [],
        "childReviewRunIds": [],
        "nodeSnapshotHashes": {},
        "completedNodeIds": [],
        "failedNodeIds": [],
        "status": "queued",
        "createdAt": now,
        "updatedAt": now,
        "revision": 1,
    }
    state.setdefault("project_review_runs", []).insert(0, record)
    return record


def dispatch_project_review_run(
    state: dict[str, Any],
    project_run: dict[str, Any],
    *,
    start_node_review,
) -> dict[str, Any]:
    project_run["status"] = "running"
    project_run["startedAt"] = project_run.get("startedAt") or server_time()
    failed_node_ids: list[int] = []
    for node_id in project_run.get("expectedNodeIds") or []:
        snapshot = current_node_snapshot(
            state,
            str(project_run["projectId"]),
            int(node_id),
        )
        project_run.setdefault("nodeSnapshotHashes", {})[str(int(node_id))] = snapshot[
            "snapshotHash"
        ]
        metadata = {
            "projectReviewRunId": project_run["projectReviewRunId"],
            "triggerType": project_run.get("triggerType"),
            "autoReviewPolicyRevision": project_run.get("autoReviewPolicyRevision"),
            "reviewMode": AUTO_REVIEW_MODE,
            "advisoryOnly": True,
        }
        try:
            child = start_node_review(str(project_run["projectId"]), int(node_id), metadata)
        except Exception as exc:
            failed_node_ids.append(int(node_id))
            project_run.setdefault("dispatchFailures", []).append(
                {"nodeId": int(node_id), "errorType": exc.__class__.__name__}
            )
            continue
        ai_run_id = str(child.get("aiRunId") or child.get("runId") or "")
        review_run_id = str(child.get("reviewRunId") or "")
        child_snapshot_hash = str(child.get("evidenceSnapshotHash") or "")
        if child_snapshot_hash:
            project_run["nodeSnapshotHashes"][str(int(node_id))] = child_snapshot_hash
        if ai_run_id:
            project_run["childAiRunIds"].append(ai_run_id)
        if review_run_id:
            project_run["childReviewRunIds"].append(review_run_id)
    project_run["failedNodeIds"] = sorted(set(failed_node_ids))
    if not project_run.get("expectedNodeIds"):
        project_run["status"] = "completed"
        project_run["finishedAt"] = server_time()
    elif failed_node_ids:
        project_run["status"] = "partial" if project_run["childAiRunIds"] else "failed"
    project_run["updatedAt"] = server_time()
    project_run["revision"] = int(project_run.get("revision") or 0) + 1
    return project_run


def finalize_project_review_run(
    state: dict[str, Any], project_run: dict[str, Any]
) -> dict[str, Any]:
    child_ids = {str(item) for item in project_run.get("childReviewRunIds") or [] if item}
    child_rows = [
        row
        for row in state.get("review_runs") or []
        if isinstance(row, dict)
        and str(row.get("reviewRunId") or row.get("id") or "") in child_ids
    ]
    completed = sorted(
        {
            int(row.get("nodeId") or 0)
            for row in child_rows
            if str(row.get("status") or "") in SUCCESSFUL_NODE_REVIEW_STATUSES
            and int(row.get("nodeId") or 0) > 0
        }
    )
    failed = sorted(
        set(int(item) for item in project_run.get("failedNodeIds") or [])
        | {
            int(row.get("nodeId") or 0)
            for row in child_rows
            if str(row.get("status") or "")
            in {
                "failed",
                "failed_to_start",
                "cancelled",
                "review_incomplete",
                "失败",
            }
            and int(row.get("nodeId") or 0) > 0
        }
    )
    expected = {int(item) for item in project_run.get("expectedNodeIds") or []}
    pending = sorted(expected - set(completed) - set(failed))
    project_run["completedNodeIds"] = completed
    project_run["failedNodeIds"] = failed
    project_run["pendingNodeIds"] = pending
    if pending:
        project_run["status"] = "running"
    elif failed:
        project_run["status"] = "partial" if completed else "failed"
        project_run["finishedAt"] = server_time()
    else:
        project_run["status"] = "completed"
        project_run["finishedAt"] = server_time()
    project_run["updatedAt"] = server_time()
    project_run["revision"] = int(project_run.get("revision") or 0) + 1
    return project_run


_SEVERITY_RANK = {
    "low": 1,
    "medium": 2,
    "high": 3,
    "critical": 4,
}


def _highest_finding_severity(findings: list[dict[str, Any]]) -> str | None:
    severities = [
        str(row.get("severity") or "").lower()
        for row in findings
        if isinstance(row, dict)
        and str(row.get("severity") or "").lower() in _SEVERITY_RANK
    ]
    return max(severities, key=lambda value: _SEVERITY_RANK[value]) if severities else None


def build_project_review_summary(
    state: dict[str, Any], project_run: dict[str, Any]
) -> dict[str, Any]:
    child_ids = [
        str(item) for item in project_run.get("childReviewRunIds") or [] if item
    ]
    child_map = {
        str(row.get("reviewRunId") or row.get("id") or ""): row
        for row in state.get("review_runs") or []
        if isinstance(row, dict)
        and str(row.get("reviewRunId") or row.get("id") or "") in child_ids
    }
    node_summaries: list[dict[str, Any]] = []
    completed_node_ids: list[int] = []
    failed_node_ids = {
        int(item) for item in project_run.get("failedNodeIds") or [] if int(item) > 0
    }
    common_risks: list[str] = []
    priority_node_ids: set[int] = set()
    for child_id in child_ids:
        child = child_map.get(child_id)
        if not child:
            continue
        node_id = int(child.get("nodeId") or 0)
        status = str(child.get("status") or "")
        findings = [
            row
            for row in child.get("findingDrafts") or []
            if isinstance(row, dict)
        ]
        highest_severity = _highest_finding_severity(findings)
        if status in SUCCESSFUL_NODE_REVIEW_STATUSES and node_id > 0:
            completed_node_ids.append(node_id)
        if status in {
            "failed",
            "failed_to_start",
            "cancelled",
            "review_incomplete",
            "失败",
        } and node_id > 0:
            failed_node_ids.add(node_id)
        source_model_attempt_ids = sorted(
            {
                str(attempt_id)
                for finding in findings
                for attempt_id in finding.get("sourceModelAttemptIds") or []
                if attempt_id
            }
            | {
                str(attempt_id)
                for attempt_id in child.get("modelCallAttemptIds") or []
                if attempt_id
            }
        )
        for finding in findings:
            severity = str(finding.get("severity") or "").lower()
            title = str(finding.get("title") or "").strip()
            if severity in {"high", "critical"} and title and title not in common_risks:
                common_risks.append(title)
        if node_id > 0 and (
            highest_severity in {"high", "critical"}
            or status
            in {
                "failed",
                "failed_to_start",
                "review_incomplete",
                "失败",
            }
        ):
            priority_node_ids.add(node_id)
        node_summaries.append(
            {
                "nodeId": node_id,
                "reviewRunId": child_id,
                "status": status,
                "findingCount": len(findings),
                "highestSeverity": highest_severity,
                "evidenceSnapshotId": child.get("evidenceSnapshotId"),
                "evidenceSnapshotHash": child.get("evidenceSnapshotHash"),
                "evidenceManifestId": child.get("evidenceManifestId"),
                "sourceEvidenceShardIds": sorted(
                    {
                        str(item)
                        for item in child.get("evidenceShardIds") or []
                        if item
                    }
                    | {
                        str(item)
                        for finding in findings
                        for item in finding.get("sourceEvidenceShardIds") or []
                        if item
                    }
                ),
                "sourceModelAttemptIds": source_model_attempt_ids,
                "evidenceCoverage": json.loads(
                    json.dumps(child.get("evidenceCoverage") or {}, default=str)
                ),
                "failedEvidenceShardIds": sorted(
                    {
                        str(item)
                        for item in child.get("failedEvidenceShardIds") or []
                        if item
                    }
                ),
                "errorCode": child.get("errorCode"),
            }
        )

    expected_node_ids = {
        int(item) for item in project_run.get("expectedNodeIds") or [] if int(item) > 0
    }
    completed = set(completed_node_ids)
    failed = failed_node_ids
    pending = expected_node_ids - completed - failed
    return {
        "schemaVersion": "ProjectReviewSummary@1.0.0",
        "projectReviewRunId": project_run.get("projectReviewRunId")
        or project_run.get("id"),
        "projectId": project_run.get("projectId"),
        "triggerType": project_run.get("triggerType"),
        "status": project_run.get("status"),
        "nodeSummaries": node_summaries,
        "commonRisks": common_risks,
        "priorityReviewNodeIds": sorted(priority_node_ids),
        "completion": {
            "expectedNodeCount": len(expected_node_ids),
            "completedNodeCount": len(completed),
            "failedNodeCount": len(failed),
            "pendingNodeCount": len(pending),
        },
    }


def finalize_running_project_review_runs(state: dict[str, Any]) -> dict[str, Any]:
    finalized_ids: list[str] = []
    running_ids: list[str] = []
    summaries = state.setdefault("project_review_summaries", [])
    for project_run in state.get("project_review_runs") or []:
        if not isinstance(project_run, dict):
            continue
        status = str(project_run.get("status") or "")
        if status not in {"running", "partial"} or project_run.get("finishedAt"):
            continue
        finalize_project_review_run(state, project_run)
        project_run_id = str(
            project_run.get("projectReviewRunId") or project_run.get("id") or ""
        )
        if str(project_run.get("status") or "") == "running":
            running_ids.append(project_run_id)
            continue
        summary = {
            "id": f"PRSUM-{project_run_id.removeprefix('PRRUN-')}",
            "tenantId": project_run.get("tenantId"),
            **build_project_review_summary(state, project_run),
            "createdAt": server_time(),
        }
        summaries[:] = [
            row
            for row in summaries
            if str(row.get("projectReviewRunId") or "") != project_run_id
        ]
        summaries.append(summary)
        project_run["projectReviewSummaryId"] = summary["id"]
        finalized_ids.append(project_run_id)
    return {
        "finalizedProjectReviewRunIds": sorted(finalized_ids),
        "runningProjectReviewRunIds": sorted(running_ids),
    }


def enqueue_auto_review_evidence_event(
    state: dict[str, Any],
    *,
    tenant_id: str,
    project_id: str,
    document_version_id: str,
    node_ids: list[int],
    mount_revision: int,
) -> tuple[dict[str, Any] | None, bool]:
    policy = next(
        (
            row
            for row in state.get("auto_review_policies") or []
            if isinstance(row, dict)
            and str(row.get("tenantId") or "") == str(tenant_id)
            and str(row.get("projectId") or "") == str(project_id)
        ),
        None,
    )
    if not policy or not policy_allows_trigger(policy, "ocr_mounted"):
        return None, False
    normalized_node_ids = sorted({int(node_id) for node_id in node_ids if int(node_id) > 0})
    if not normalized_node_ids:
        return None, False
    event_id = _stable_id(
        "AREVT",
        {
            "tenantId": str(tenant_id),
            "projectId": str(project_id),
            "documentVersionId": str(document_version_id),
            "nodeIds": normalized_node_ids,
            "mountRevision": int(mount_revision),
        },
    )
    rows = state.setdefault("auto_review_outbox", [])
    existing = next((row for row in rows if str(row.get("id") or "") == event_id), None)
    if existing:
        return existing, False
    now = server_time()
    event = {
        "id": event_id,
        "eventType": "node.evidence.mounted",
        "tenantId": str(tenant_id),
        "projectId": str(project_id),
        "documentVersionId": str(document_version_id),
        "nodeIds": normalized_node_ids,
        "mountRevision": int(mount_revision),
        "policyRevision": int(policy.get("revision") or 1),
        "status": "pending",
        "attemptCount": 0,
        "availableAt": now,
        "createdAt": now,
        "updatedAt": now,
    }
    rows.append(event)
    return event, True


def policy_due_for_daily_scan(policy: dict[str, Any], now: datetime) -> bool:
    if not policy_allows_trigger(policy, "daily_schedule"):
        return False
    timezone = ZoneInfo(str(policy.get("timezone") or DEFAULT_TIMEZONE))
    effective_now = now if now.tzinfo is not None else now.replace(tzinfo=UTC)
    local_now = effective_now.astimezone(timezone)
    daily_time = datetime.strptime(
        str(policy.get("dailyTime") or DEFAULT_DAILY_TIME), "%H:%M"
    ).time()
    if local_now.time().replace(tzinfo=None) < daily_time:
        return False
    return str(policy.get("lastDailyRunLocalDate") or "") != local_now.date().isoformat()


def scan_due_auto_review_policies(
    state: dict[str, Any], *, now: datetime
) -> dict[str, Any]:
    due_project_ids: list[str] = []
    created_candidate_ids: list[str] = []
    for policy in state.get("auto_review_policies") or []:
        if not isinstance(policy, dict) or not policy_due_for_daily_scan(policy, now):
            continue
        project_id = str(policy.get("projectId") or "")
        tenant_id = str(policy.get("tenantId") or "")
        if not project_id or not tenant_id:
            continue
        due_project_ids.append(project_id)
        for dirty in dirty_nodes_for_project(state, project_id):
            candidate, created = upsert_auto_review_candidate(
                state,
                tenant_id=tenant_id,
                project_id=project_id,
                node_id=int(dirty["nodeId"]),
                evidence_snapshot_hash=str(dirty["evidenceSnapshotHash"]),
                policy_revision=int(policy.get("revision") or 1),
                trigger_type="daily_schedule",
            )
            if created:
                created_candidate_ids.append(str(candidate["id"]))
        local_date = (now if now.tzinfo is not None else now.replace(tzinfo=UTC)).astimezone(
            ZoneInfo(str(policy.get("timezone") or DEFAULT_TIMEZONE))
        ).date().isoformat()
        policy["lastDailyRunLocalDate"] = local_date
        policy["lastDailyScanAt"] = now.isoformat()
        policy["updatedAt"] = server_time()
    return {
        "dueProjectIds": sorted(set(due_project_ids)),
        "createdCandidateIds": created_candidate_ids,
    }


def consume_auto_review_evidence_events(
    state: dict[str, Any], *, now: datetime, limit: int = 100
) -> dict[str, Any]:
    completed_event_ids: list[str] = []
    skipped_event_ids: list[str] = []
    created_candidate_ids: list[str] = []
    events = [
        row
        for row in state.get("auto_review_outbox") or []
        if isinstance(row, dict) and str(row.get("status") or "") in {"pending", "retry_pending"}
    ][: max(1, min(int(limit), 500))]
    for event in events:
        tenant_id = str(event.get("tenantId") or "")
        project_id = str(event.get("projectId") or "")
        policy = next(
            (
                row
                for row in state.get("auto_review_policies") or []
                if isinstance(row, dict)
                and str(row.get("tenantId") or "") == tenant_id
                and str(row.get("projectId") or "") == project_id
            ),
            None,
        )
        event["attemptCount"] = int(event.get("attemptCount") or 0) + 1
        if not policy or not policy_allows_trigger(policy, "ocr_mounted"):
            event["status"] = "skipped"
            event["skipReason"] = "policy_disabled_or_trigger_not_configured"
            event["updatedAt"] = server_time()
            skipped_event_ids.append(str(event.get("id") or ""))
            continue
        for node_id in sorted({int(item) for item in event.get("nodeIds") or [] if int(item) > 0}):
            snapshot = current_node_snapshot(state, project_id, node_id)
            if not snapshot.get("documentVersions"):
                continue
            candidate, created = upsert_auto_review_candidate(
                state,
                tenant_id=tenant_id,
                project_id=project_id,
                node_id=node_id,
                evidence_snapshot_hash=str(snapshot["snapshotHash"]),
                policy_revision=int(policy.get("revision") or 1),
                trigger_type="ocr_mounted",
            )
            if created:
                created_candidate_ids.append(str(candidate["id"]))
        event["status"] = "completed"
        event["completedAt"] = now.isoformat()
        event["updatedAt"] = server_time()
        completed_event_ids.append(str(event.get("id") or ""))
    return {
        "completedEventIds": completed_event_ids,
        "skippedEventIds": skipped_event_ids,
        "createdCandidateIds": created_candidate_ids,
    }


def dispatch_pending_auto_review_candidates(
    state: dict[str, Any],
    *,
    start_node_review,
    limit: int = 100,
) -> dict[str, Any]:
    pending = [
        row
        for row in state.get("auto_review_candidates") or []
        if isinstance(row, dict) and str(row.get("status") or "") == "pending"
    ][: max(1, min(int(limit), 500))]
    groups: dict[tuple[str, str, int], list[dict[str, Any]]] = {}
    for candidate in pending:
        key = (
            str(candidate.get("tenantId") or ""),
            str(candidate.get("projectId") or ""),
            int(candidate.get("policyRevision") or 1),
        )
        groups.setdefault(key, []).append(candidate)

    project_run_ids: list[str] = []
    skipped_candidate_ids: list[str] = []
    for (tenant_id, project_id, policy_revision), candidates in groups.items():
        policy = next(
            (
                row
                for row in state.get("auto_review_policies") or []
                if isinstance(row, dict)
                and str(row.get("tenantId") or "") == tenant_id
                and str(row.get("projectId") or "") == project_id
            ),
            None,
        )
        if not policy or policy.get("enabled") is not True:
            for candidate in candidates:
                candidate["status"] = "skipped"
                candidate["skipReason"] = "policy_disabled"
                candidate["updatedAt"] = server_time()
                skipped_candidate_ids.append(str(candidate.get("id") or ""))
            continue
        trigger_types = {
            str(candidate.get("triggerType") or "ocr_mounted")
            for candidate in candidates
        }
        trigger_type = next(iter(trigger_types)) if len(trigger_types) == 1 else "mixed"
        parent = create_project_review_run(
            state,
            tenant_id=tenant_id,
            project_id=project_id,
            trigger_type=trigger_type,
            policy={**policy, "revision": policy_revision},
            node_ids=[int(candidate.get("nodeId") or 0) for candidate in candidates],
        )
        dispatch_project_review_run(
            state,
            parent,
            start_node_review=start_node_review,
        )
        failed_nodes = {int(item) for item in parent.get("failedNodeIds") or []}
        for candidate in candidates:
            candidate["projectReviewRunId"] = parent["projectReviewRunId"]
            candidate["status"] = (
                "failed" if int(candidate.get("nodeId") or 0) in failed_nodes else "dispatched"
            )
            candidate["dispatchedAt"] = server_time()
            candidate["updatedAt"] = candidate["dispatchedAt"]
        project_run_ids.append(str(parent["projectReviewRunId"]))
    return {
        "projectReviewRunIds": project_run_ids,
        "skippedCandidateIds": skipped_candidate_ids,
    }
