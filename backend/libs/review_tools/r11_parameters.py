"""R11 same-object, fixed-source construction/design parameter comparison."""
from __future__ import annotations

import math
from copy import deepcopy

from libs.review_orchestrator.deterministic_tools import check, result
from libs.review_tools.r39_tools import _refs, _text

SCOPE_FIELDS = ("projectId", "objectType", "objectId", "planVersionId", "designVersionId")


def evaluate_r11_project_parameters(arguments):
    if "inventory" in arguments or "objectComparisons" in arguments:
        from libs.review_tools.r11_inventory import evaluate_inventory
        return evaluate_inventory(arguments, evaluate_r11_project_parameters)
    rows = []

    def add(code, status, refs=()):
        rows.append({"code": code, "result": status, "evidenceRefs": deepcopy(list(refs))})

    def finish():
        statuses = {row["result"] for row in rows}
        status = ("failed" if "failed" in statuses else "evidence_insufficient" if "evidence_insufficient" in statuses
                  else "not_applicable" if statuses == {"not_applicable"} else "passed")
        if arguments.get("selectionIssues") and status in {"passed", "not_applicable"}:
            status = "evidence_insufficient"
        output = result("evaluate_r11_project_parameters", status,
                        facts={"parameterChecks": rows, "wholeRuleAcceptance": "not_evaluated",
                               "scope": "selected_object_required_parameters_only",
                               "selectionIssues": deepcopy(arguments.get("selectionIssues") or [])},
                        checks=[check(row["code"], row["result"] == "passed", row["result"], "passed") for row in rows],
                        rule_version="r11-project-parameter-comparison-v2")
        output["evidenceRefs"] = [ref for row in rows for ref in row["evidenceRefs"]]
        return output

    scope = arguments.get("scope")
    if (not isinstance(scope, dict) or any(not _text(scope.get(key)) for key in SCOPE_FIELDS)
            or scope["projectId"] != arguments.get("projectId") or scope["planVersionId"] == scope["designVersionId"]):
        add("r11_parameter_scope_missing", "evidence_insufficient")
        return finish()

    def matches(record):
        return isinstance(record, dict) and all(record.get(key) == scope[key] for key in SCOPE_FIELDS)

    basis = arguments.get("basis")
    if not matches(basis) or type(basis.get("applicable")) is not bool or not _refs(basis):
        add("r11_comparison_basis_missing", "evidence_insufficient")
        return finish()
    supplied = arguments.get("parameters", [])
    if not isinstance(supplied, list) or any(not matches(row) for row in supplied):
        add("r11_parameter_object_conflict", "evidence_insufficient", _refs(basis))
        return finish()
    if not basis["applicable"]:
        add("r11_comparison_not_applicable", "not_applicable", _refs(basis))
        return finish()
    names = basis.get("requiredFields")
    if (basis.get("completeRequirements") is not True or not isinstance(names, list) or not names
            or any(not _text(name) for name in names) or len(set(names)) != len(names)):
        add("r11_parameter_requirements_incomplete", "evidence_insufficient", _refs(basis))
        return finish()
    lookup = {}
    for row in supplied:
        key = (row.get("side"), row.get("field"))
        if key[0] not in {"plan", "design"} or not _text(key[1]) or key in lookup:
            add("r11_parameter_duplicate_or_unknown", "evidence_insufficient", _refs(basis))
            return finish()
        lookup[key] = row
    for name in names:
        pair = [lookup.get((side, name)) for side in ("plan", "design")]
        refs = _refs(basis)
        valid = True
        for row, version_key in zip(pair, ("planVersionId", "designVersionId"), strict=True):
            if not row or not _refs(row) or any(ref["documentVersionId"] != scope[version_key] for ref in _refs(row)):
                valid = False
                continue
            refs.extend(_refs(row))
            value = row.get("value")
            if not (_text(value) or (type(value) is int or (type(value) is float and math.isfinite(value)))):
                valid = False
            if type(value) in (int, float) and not _text(row.get("unit")):
                valid = False
            if "unit" in row and not _text(row["unit"]):
                valid = False
        if not valid:
            add(name, "evidence_insufficient", refs)
            continue
        left, right = pair
        same_type = type(left["value"]) is type(right["value"]) or (
            type(left["value"]) in (int, float) and type(right["value"]) in (int, float))
        if not same_type or left.get("unit") != right.get("unit"):
            add(name, "evidence_insufficient", refs)
        else:
            add(name, "passed" if left["value"] == right["value"] else "failed", refs)
    return finish()
