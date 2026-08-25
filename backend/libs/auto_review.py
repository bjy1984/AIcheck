from __future__ import annotations

import hashlib
import json
from datetime import datetime
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
        if ai_run_id:
            project_run["childAiRunIds"].append(ai_run_id)
        if review_run_id:
            project_run["childReviewRunIds"].append(review_run_id)
    project_run["failedNodeIds"] = sorted(set(failed_node_ids))
    if failed_node_ids:
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
            if str(row.get("status") or "") in {"failed", "failed_to_start", "cancelled", "失败"}
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
