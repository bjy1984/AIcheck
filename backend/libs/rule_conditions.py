"""Validated draft conditions. No generated code or implicit unit conversions."""
from __future__ import annotations

import math
import operator
from copy import deepcopy
from typing import Any

OPERATORS = {"eq": operator.eq, "ne": operator.ne, "gt": operator.gt, "gte": operator.ge, "lt": operator.lt, "lte": operator.le, "in": lambda actual, expected: actual in expected}


def validate_conditions(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or (set(value) - {"schemaVersion", "checks", "applicability"} or not {"schemaVersion", "checks"} <= set(value)) or value.get("schemaVersion") != "rule-conditions-v1":
        raise ValueError("invalid_conditions_schema")
    checks = value["checks"]
    if not isinstance(checks, list) or not 1 <= len(checks) <= 200:
        raise ValueError("conditions_require_1_to_200_checks")
    validation_checks = checks + ([value["applicability"]] if "applicability" in value else [])
    seen = set()
    for check in validation_checks:
        if not isinstance(check, dict) or set(check) - {"id", "field", "operator", "expected", "unit"}:
            raise ValueError("invalid_condition_fields")
        if not all(isinstance(check.get(key), str) and check[key].strip() for key in ("id", "field", "operator")):
            raise ValueError("condition_identity_missing")
        if check["id"] in seen:
            raise ValueError("duplicate_condition_id")
        seen.add(check["id"])
        if check["operator"] not in OPERATORS or "expected" not in check:
            raise ValueError("unsupported_condition_operator")
        expected = check["expected"]
        if check["operator"] in {"gt", "gte", "lt", "lte"}:
            if not _number(expected):
                raise ValueError("numeric_condition_requires_finite_number")
        elif check["operator"] == "in":
            if not isinstance(expected, list) or not expected or not all(_scalar(item) for item in expected):
                raise ValueError("membership_condition_requires_values")
        elif not _scalar(expected):
            raise ValueError("condition_requires_scalar")
        if "unit" in check and (not isinstance(check["unit"], str) or not check["unit"].strip()):
            raise ValueError("invalid_condition_unit")
    return value


def _number(value: Any) -> bool:
    try:
        return type(value) in {int, float} and math.isfinite(value)
    except OverflowError:
        return False


def _scalar(value: Any) -> bool:
    return isinstance(value, (str, bool)) or _number(value)


def evaluate_conditions(conditions: dict[str, Any], facts: dict[str, Any]) -> dict[str, Any]:
    validate_conditions(conditions)
    if not isinstance(facts, dict):
        raise TypeError("condition_facts_must_be_object")
    applicability = None
    if "applicability" in conditions:
        applicability = evaluate_conditions(
            {"schemaVersion": "rule-conditions-v1", "checks": [conditions["applicability"]]}, facts,
        )["checks"][0]
        if applicability["result"] != "pass":
            not_applicable = applicability["result"] == "fail"
            return {
                "result": "not_applicable" if not_applicable else "evidence_insufficient",
                "reason": "applicability_not_met" if not_applicable else "applicability_unknown",
                "applicability": applicability,
                "checks": [{"id": check["id"], "field": check["field"],
                            "result": "not_applicable" if not_applicable else "evidence_insufficient",
                            "reason": "applicability_not_met" if not_applicable else "applicability_unknown",
                            "evidenceRefs": deepcopy(applicability["evidenceRefs"])} for check in conditions["checks"]],
            }
    results = []
    for check in conditions["checks"]:
        fact = facts.get(check["field"])
        result = {"id": check["id"], "field": check["field"], "result": "evidence_insufficient", "evidenceRefs": []}
        if not isinstance(fact, dict) or "value" not in fact or fact["value"] is None:
            result["reason"] = "fact_missing"
        elif not isinstance(fact.get("evidenceRefs"), list) or not fact["evidenceRefs"]:
            result["reason"] = "evidence_reference_missing"
        elif fact.get("unit") != check.get("unit"):
            result["reason"] = "unit_mismatch"
        else:
            actual, expected, operator = fact["value"], check["expected"], check["operator"]
            compatible = _number(actual) if operator in {"gt", "gte", "lt", "lte"} else _scalar(actual)
            candidates = expected if operator == "in" else [expected]
            compatible = compatible and all(type(actual) is type(item) or (_number(actual) and _number(item)) for item in candidates)
            if not compatible:
                result["reason"] = "fact_type_mismatch"
            else:
                passed = OPERATORS[operator](actual, expected)
                result.update(result="pass" if passed else "fail", reason="condition_evaluated", evidenceRefs=deepcopy(fact["evidenceRefs"]))
        results.append(result)
    statuses = {item["result"] for item in results}
    return {"result": "fail" if "fail" in statuses else "evidence_insufficient" if "evidence_insufficient" in statuses else "pass", "checks": results, **({"applicability": applicability} if applicability else {})}
