"""Freeze explicit object selections for new runs; never alter historical inputs."""
from __future__ import annotations

from copy import deepcopy

from libs.review_condition_facts import condition_facts_from_run
from libs.review_document_scope import validate_document_sources
from libs.review_rule_snapshot import _hash, effective_rule_snapshot

REQUEST_FIELDS = {"selection", "ruleVersionId", "ruleRevision", "sourceSnapshotHash"}


def freeze_condition_mapping(run, state, request):
    if (not isinstance(request, dict) or set(request) != REQUEST_FIELDS
            or not isinstance(request["selection"], dict)
            or type(request["ruleRevision"]) is not int or request["ruleRevision"] < 1):
        raise ValueError("condition_mapping_request_invalid")
    rule = effective_rule_snapshot(run)
    if (not rule or not rule.get("executionConditions") or request["ruleVersionId"] != rule.get("id")
            or request["ruleRevision"] != rule.get("revision")):
        raise ValueError("condition_mapping_rule_changed_retry_trial")
    source = run.get("documentScopeSnapshot") or {}
    if request["sourceSnapshotHash"] != source.get("snapshotHash") or not source.get("sourceFingerprint"):
        raise ValueError("condition_mapping_sources_changed_retry_trial")
    validate_document_sources(run, state)
    condition_facts_from_run(state, run, rule["executionConditions"], object_mapping=request["selection"])
    snapshot = {"schemaVersion": "review-condition-object-mapping-v1", "selection": deepcopy(request["selection"]),
                "projectId": run.get("projectId"), "tenantId": run.get("tenantId"), "nodeId": run.get("nodeId"),
                "ruleSnapshotHash": run["effectiveRuleSnapshot"]["snapshotHash"],
                "sourceSnapshotHash": source["snapshotHash"]}
    snapshot["snapshotHash"] = _hash(snapshot)
    return snapshot


def effective_condition_mapping(run, state):
    snapshot = run.get("conditionObjectMappingSnapshot")
    if "conditionObjectMappingSnapshot" not in run:
        if "conditionObjectMapping" in run:
            raise ValueError("condition_mapping_snapshot_required")
        return None
    if (not isinstance(snapshot, dict) or snapshot.get("schemaVersion") != "review-condition-object-mapping-v1"
            or snapshot.get("snapshotHash") != _hash({key: value for key, value in snapshot.items() if key != "snapshotHash"})):
        raise ValueError("condition_mapping_snapshot_changed")
    if any(snapshot.get(key) != run.get(key) for key in ("tenantId", "projectId", "nodeId")):
        raise ValueError("condition_mapping_scope_changed")
    effective_rule_snapshot(run)
    if (snapshot.get("ruleSnapshotHash") != (run.get("effectiveRuleSnapshot") or {}).get("snapshotHash")
            or snapshot.get("sourceSnapshotHash") != (run.get("documentScopeSnapshot") or {}).get("snapshotHash")):
        raise ValueError("condition_mapping_inputs_changed")
    validate_document_sources(run, state)
    return deepcopy(snapshot["selection"])


def initialize_condition_mapping(record, state):
    if "conditionObjectMapping" not in record:
        return
    request = record.pop("conditionObjectMapping")
    record["conditionObjectMappingSnapshot"] = freeze_condition_mapping(record, state, request)
    record["inputHash"] = _hash({"legacyInputHash": record["inputHash"],
                                "conditionObjectMapping": record["conditionObjectMappingSnapshot"]["snapshotHash"]})


def assert_mapping_reuse(ai_run, existing, state):
    request = ai_run.get("conditionObjectMapping")
    snapshot = existing.get("conditionObjectMappingSnapshot")
    if request is None and snapshot is None:
        return
    if request is None or snapshot is None:
        raise ValueError("condition_mapping_existing_run_mismatch")
    effective_condition_mapping(existing, state)
    if freeze_condition_mapping(existing, state, request)["snapshotHash"] != snapshot["snapshotHash"]:
        raise ValueError("condition_mapping_existing_run_mismatch")
