"""R36 plan comparison against explicit, sourced requirements; no invented standard limits."""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from libs.review_orchestrator.deterministic_tools import check, decimal, result


def _refs(record: dict[str, Any]) -> list[dict[str, Any]]:
    values = record.get("evidenceRefs")
    return values if isinstance(values, list) and values and all(
        isinstance(ref, dict) and isinstance(ref.get("documentVersionId"), str) and ref["documentVersionId"].strip()
        and type(ref.get("pageNo")) is int and ref["pageNo"] > 0 for ref in values) else []


def _percent(value: Any):
    number = None if isinstance(value, bool) else decimal(value)
    return number if number is not None and number.is_finite() and 0 <= number <= 100 else None


def evaluate_r36_ndt_plan(arguments: dict[str, Any]) -> dict[str, Any]:
    rows = []

    def add(code, status, refs=None):
        rows.append({"code": code, "result": status, "evidenceRefs": deepcopy(refs or [])})

    def finish():
        statuses = {row["result"] for row in rows}
        status = "failed" if "failed" in statuses else "evidence_insufficient" if "evidence_insufficient" in statuses else "not_applicable" if statuses == {"not_applicable"} else "passed"
        output = result("evaluate_r36_ndt_plan", status, facts={"planChecks": rows},
                        checks=[check(row["code"], row["result"] == "passed", row["result"], "passed") for row in rows],
                        rule_version="r36-explicit-ndt-plan-requirements-v1")
        output["evidenceRefs"] = [ref for row in rows for ref in row["evidenceRefs"]]
        return output

    applicability = arguments.get("applicability")
    if not isinstance(applicability, dict) or type(applicability.get("required")) is not bool or not _refs(applicability):
        add("r36_applicability_missing", "evidence_insufficient")
        return finish()
    if not applicability["required"]:
        add("r36_not_applicable", "not_applicable", _refs(applicability))
        return finish()
    add("r36_applicable", "passed", _refs(applicability))
    project_id, plan = arguments.get("projectId"), arguments.get("plan")
    if (not isinstance(project_id, str) or not project_id.strip() or not isinstance(plan, dict)
            or plan.get("projectId") != project_id or not _refs(plan)):
        add("r36_plan_identity_or_evidence_missing", "evidence_insufficient")
        return finish()
    for field in ("approved", "personnelReady", "equipmentReady"):
        value = plan.get(field)
        add("r36_" + field, "passed" if value is True else "failed" if value is False else "evidence_insufficient", _refs(plan))
    requirements, items = arguments.get("requirements"), plan.get("items")
    if not isinstance(requirements, list) or not requirements or not isinstance(items, list):
        add("r36_requirements_or_plan_items_missing", "evidence_insufficient")
        return finish()
    for index, requirement in enumerate(requirements):
        code = f"r36_requirement_{index + 1}"
        if (not isinstance(requirement, dict) or requirement.get("projectId") != project_id
                or not _refs(requirement) or type(requirement.get("required")) is not bool):
            add(code + "_basis_missing", "evidence_insufficient")
            continue
        refs = _refs(requirement)
        if requirement["required"] is False:
            add(code + "_optional", "not_applicable", refs)
            continue
        identity = (requirement.get("objectId"), requirement.get("method"))
        if any(not isinstance(value, str) or not value.strip() for value in identity):
            add(code + "_object_or_method_missing", "evidence_insufficient", refs)
            continue
        if sum(1 for row in requirements if isinstance(row, dict) and (row.get("objectId"), row.get("method")) == identity) != 1:
            add(code + "_requirement_ambiguous", "evidence_insufficient", refs)
            continue
        matches = [item for item in items if isinstance(item, dict) and (item.get("objectId"), item.get("method")) == identity]
        if len(matches) != 1:
            add(code + "_coverage_missing_or_ambiguous", "evidence_insufficient", refs)
            continue
        item = matches[0]
        if item.get("projectId") != project_id or not _refs(item):
            add(code + "_plan_item_evidence_missing", "evidence_insufficient", refs)
            continue
        refs = [*refs, *_refs(item)]
        required_ratio, actual_ratio = _percent(requirement.get("ratioPercent")), _percent(item.get("ratioPercent"))
        if required_ratio is None or actual_ratio is None:
            add(code + "_ratio_missing_or_invalid", "evidence_insufficient", refs)
        else:
            add(code + "_ratio", "passed" if actual_ratio >= required_ratio else "failed", refs)
        for field in ("timing", "acceptanceLevel"):
            expected, actual = requirement.get(field), item.get(field)
            if not isinstance(expected, str) or not expected.strip() or not isinstance(actual, str) or not actual.strip():
                add(code + "_" + field + "_missing", "evidence_insufficient", refs)
            else:
                allowed = requirement.get("allowedTiming" if field == "timing" else "allowedAcceptanceLevels")
                if allowed is not None:
                    if not isinstance(allowed, list) or not allowed or any(not isinstance(value, str) or not value.strip() for value in allowed) or expected not in allowed:
                        add(code + "_" + field + "_basis_conflict", "evidence_insufficient", refs)
                    else:
                        add(code + "_" + field, "passed" if actual in allowed else "failed", refs)
                else:
                    # Different labels may be equivalent or stricter. Without an explicit
                    # accepted set, a mismatch needs interpretation rather than a guessed failure.
                    add(code + "_" + field, "passed" if actual == expected else "evidence_insufficient", refs)
    return finish()
