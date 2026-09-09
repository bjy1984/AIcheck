"""Pin the selected rule to a run, including its project and node identity."""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any


def _hash(value: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def freeze_effective_rule(run: dict[str, Any], rule: dict[str, Any]) -> dict[str, Any]:
    if not rule:
        raise ValueError("effective_rule_missing")
    snapshot = {
        "schemaVersion": "effective-rule-v1",
        "projectId": run.get("projectId"), "nodeId": run.get("nodeId"),
        "businessPackId": run.get("businessPackId"), "rule": deepcopy(rule),
    }
    snapshot["snapshotHash"] = _hash(snapshot)
    return snapshot


def effective_rule_snapshot(run: dict[str, Any]) -> dict[str, Any] | None:
    snapshot = run.get("effectiveRuleSnapshot")
    if snapshot is None:
        return None  # Runs created before this contract retain their original behavior.
    if not isinstance(snapshot, dict) or snapshot.get("schemaVersion") != "effective-rule-v1":
        raise ValueError("invalid_effective_rule_snapshot")
    if snapshot.get("snapshotHash") != _hash({key: value for key, value in snapshot.items() if key != "snapshotHash"}):
        raise ValueError("effective_rule_snapshot_hash_mismatch")
    if any(snapshot.get(key) != run.get(key) for key in ("projectId", "nodeId", "businessPackId")):
        raise ValueError("effective_rule_snapshot_scope_mismatch")
    if not snapshot.get("rule"):
        raise ValueError("effective_rule_missing")
    return deepcopy(snapshot["rule"])
