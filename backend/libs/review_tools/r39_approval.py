"""Compare one R39 document approval cycle with explicit sourced QMS requirements."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any

from libs.review_orchestrator.deterministic_tools import check, result
from libs.review_tools.r39_tools import _refs, _text

SCOPE_FIELDS = ("projectId", "organizationId", "documentId", "documentVersionId", "documentKind",
                "method", "approvalCycleId", "procedureId", "procedureVersion")


def _timestamp(value):
    if not _text(value):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None and parsed.utcoffset() is not None else None


def _names(value):
    return isinstance(value, list) and all(_text(item) for item in value) and len(set(value)) == len(value)


def evaluate_r39_approval_chain(arguments: dict[str, Any]) -> dict[str, Any]:
    rows = []

    def add(code, status, refs=None):
        rows.append({"code": code, "result": status, "evidenceRefs": deepcopy(refs or [])})

    def finish():
        statuses = {row["result"] for row in rows}
        status = "failed" if "failed" in statuses else "evidence_insufficient" if "evidence_insufficient" in statuses else "not_applicable" if statuses == {"not_applicable"} else "passed"
        output = result("evaluate_r39_approval_chain", status,
                        facts={"approvalChecks": rows, "wholeRuleAcceptance": "not_evaluated", "evidenceVerified": False},
                        checks=[check(row["code"], row["result"] == "passed", row["result"], "passed") for row in rows],
                        rule_version="r39-explicit-qms-approval-chain-v1")
        output["evidenceRefs"] = [ref for row in rows for ref in row["evidenceRefs"]]
        return output

    scope = arguments.get("scope")
    if (not isinstance(scope, dict) or any(not _text(scope.get(field)) for field in SCOPE_FIELDS)
            or scope.get("documentKind") not in {"procedure", "instruction"}
            or arguments.get("projectId") != scope["projectId"]):
        add("r39_approval_scope_missing", "evidence_insufficient")
        return finish()

    def matches(record):
        return isinstance(record, dict) and all(record.get(field) == scope[field] for field in SCOPE_FIELDS)

    requirement_fields = {*SCOPE_FIELDS, "complete", "applicable", "steps", "evidenceRefs"}
    requirements = arguments.get("requirements")
    if (not matches(requirements) or set(requirements) - requirement_fields or requirements.get("complete") is not True
            or requirements.get("applicable") is not True or not _refs(requirements)):
        add("r39_qms_requirements_missing", "evidence_insufficient")
        return finish()
    steps = requirements.get("steps")
    if not isinstance(steps, list) or not steps:
        add("r39_qms_steps_missing", "evidence_insufficient", _refs(requirements))
        return finish()
    step_fields = {"stepId", "role", "required", "evidenceRefs", "after", "distinctFrom", "authorizedSignerIds", "authorizationComplete"}
    by_id = {}
    for step in steps:
        if (not isinstance(step, dict) or set(step) - step_fields or not _text(step.get("stepId")) or step["stepId"] in by_id
                or not _text(step.get("role")) or type(step.get("required")) is not bool
                or not _refs(step) or not _names(step.get("after")) or not _names(step.get("distinctFrom"))
                or (step["required"] and (not _names(step.get("authorizedSignerIds"))
                                          or not step["authorizedSignerIds"] or step.get("authorizationComplete") is not True))):
            add("r39_qms_step_invalid_or_ambiguous", "evidence_insufficient", _refs(requirements))
            return finish()
        by_id[step["stepId"]] = step
    # Validate the whole requirement set before an optional branch can return N/A.
    for step in steps:
        for dependency in [*step["after"], *step["distinctFrom"]]:
            if dependency == step["stepId"] or dependency not in by_id or not by_id[dependency]["required"]:
                add("r39_qms_dependency_invalid", "evidence_insufficient", _refs(step))
                return finish()
    pending = {key: set(step["after"]) for key, step in by_id.items()}
    while pending:
        ready = {key for key, dependencies in pending.items() if not dependencies}
        if not ready:
            add("r39_qms_dependency_cycle", "evidence_insufficient", _refs(requirements))
            return finish()
        pending = {key: dependencies - ready for key, dependencies in pending.items() if key not in ready}
    inventory = arguments.get("signatureInventory")
    if not matches(inventory) or inventory.get("complete") is not True or not _refs(inventory):
        add("r39_signature_inventory_missing", "evidence_insufficient", _refs(requirements))
        return finish()
    signatures = inventory.get("signatures")
    if not isinstance(signatures, list):
        add("r39_signatures_invalid", "evidence_insufficient", _refs(inventory))
        return finish()
    records = {}
    for signature in signatures:
        if (not matches(signature) or not _text(signature.get("stepId")) or signature["stepId"] not in by_id
                or signature["stepId"] in records or not _refs(signature)):
            add("r39_signature_orphan_duplicate_or_mismatched", "evidence_insufficient", _refs(inventory))
            return finish()
        records[signature["stepId"]] = signature
    for step_id, step in by_id.items():
        refs = [*_refs(requirements), *_refs(step), *_refs(inventory)]
        if not step["required"]:
            add(step_id + "_optional", "not_applicable", refs)
            continue
        signature = records.get(step_id)
        if (signature is None or not _text(signature.get("signerId")) or not _text(signature.get("role"))
                or type(signature.get("approved")) is not bool or _timestamp(signature.get("signedAt")) is None):
            add(step_id + "_signature_fact_missing", "evidence_insufficient", refs)
            continue
        refs.extend(_refs(signature))
        add(step_id + "_approved", "passed" if signature["approved"] else "failed", refs)
        add(step_id + "_role", "passed" if signature["role"] == step["role"] else "failed", refs)
        add(step_id + "_authorized_signer", "passed" if signature["signerId"] in step["authorizedSignerIds"] else "failed", refs)
        for dependency in step["after"]:
            previous = records.get(dependency, {})
            previous_time = _timestamp(previous.get("signedAt"))
            if previous_time is None or type(previous.get("approved")) is not bool:
                status = "evidence_insufficient"
            else:
                status = "passed" if previous["approved"] and previous_time <= _timestamp(signature["signedAt"]) else "failed"
            add(step_id + "_after_" + dependency, status, [*refs, *_refs(previous)])
        for dependency in step["distinctFrom"]:
            previous = records.get(dependency, {})
            status = "evidence_insufficient" if not _text(previous.get("signerId")) else "failed" if previous["signerId"] == signature["signerId"] else "passed"
            add(step_id + "_distinct_from_" + dependency, status, [*refs, *_refs(previous)])
    return finish()
