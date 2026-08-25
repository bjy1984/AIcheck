from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from libs.contracts.responses import server_time


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
