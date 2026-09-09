"""Compare sourced, explicitly declared R40 event parameters without supplying thresholds."""
import math
from copy import deepcopy

from libs.review_orchestrator.deterministic_tools import check, result
from libs.review_tools.r39_tools import _refs, _text
from libs.review_tools.r40_records import KEYS


def evaluate_r40_parameters(arguments):
    rows, refs = [], []

    def add(code, status, evidence=()):
        rows.append({"code": code, "result": status})
        refs.extend(deepcopy(list(evidence)))

    project, inventory = arguments.get("projectId"), arguments.get("inventory")
    requirements, values = arguments.get("requirements"), arguments.get("values")
    if (not _text(project) or not isinstance(inventory, dict) or inventory.get("projectId") != project
            or inventory.get("complete") is not True or not _refs(inventory)
            or not isinstance(inventory.get("members"), list) or not inventory["members"]
            or not isinstance(requirements, list) or not isinstance(values, list)):
        add("r40_parameter_inventory_missing", "evidence_insufficient")
    else:
        refs.extend(_refs(inventory))
        used = [set(), set()]
        seen = set()
        for index, member in enumerate(inventory["members"]):
            key = tuple(member.get(field) for field in KEYS) if isinstance(member, dict) else ()
            if (not key or any(not _text(value) for value in key) or key in seen
                    or member.get("projectId") != project or not _refs(member)):
                add(f"r40_parameter_event_{index}_ambiguous", "evidence_insufficient")
                continue
            seen.add(key)
            refs.extend(_refs(member))
            event_rows = []
            for position, records in enumerate((requirements, values)):
                matched = [(i, row) for i, row in enumerate(records) if isinstance(row, dict)
                           and row.get("projectId") == project and tuple(row.get(field) for field in KEYS) == key]
                used[position].update(i for i, _ in matched)
                event_rows.append([row for _, row in matched])
            if member.get("applicable") is False:
                add(f"r40_parameter_event_{index}_excluded", "not_applicable" if not any(event_rows) else "evidence_insufficient")
                continue
            names = member.get("requiredParameters")
            if (member.get("applicable") is not True or member.get("parameterRequirementsComplete") is not True
                    or not isinstance(names, list) or not names or any(not _text(name) for name in names)
                    or len(set(names)) != len(names)):
                add(f"r40_parameter_event_{index}_requirements_unknown", "evidence_insufficient")
                continue
            if any(row.get("parameter") not in names for items in event_rows for row in items):
                add(f"r40_parameter_event_{index}_undeclared", "evidence_insufficient")
            for name in names:
                pairs = [[row for row in items if row.get("parameter") == name] for items in event_rows]
                code = f"r40_parameter_event_{index}_{name}"
                if any(len(items) != 1 for items in pairs):
                    add(code + "_missing_or_ambiguous", "evidence_insufficient")
                    continue
                required, observed = pairs[0][0], pairs[1][0]
                evidence = [*_refs(required), *_refs(observed)]
                if (not _refs(required) or not _refs(observed) or not isinstance(required.get("unit"), str)
                        or required["unit"] != observed.get("unit")):
                    add(code + "_source_or_unit_unknown", "evidence_insufficient")
                    continue
                expected, actual, operator = required.get("value"), observed.get("value"), required.get("operator")
                numeric = all((type(value) is int or type(value) is float and math.isfinite(value)) for value in (expected, actual))
                if numeric and operator in {"gte", "lte", "eq"} and _text(required["unit"]):
                    valid = actual >= expected if operator == "gte" else actual <= expected if operator == "lte" else actual == expected
                elif operator == "eq" and _text(expected) and _text(actual):
                    valid = actual == expected
                else:
                    add(code + "_comparison_unsupported", "evidence_insufficient", evidence)
                    continue
                add(code, "passed" if valid else "failed", evidence)
        if len(used[0]) != len(requirements) or len(used[1]) != len(values):
            add("r40_parameter_source_outside_event_inventory", "evidence_insufficient")
    if arguments.get("selectionIssues"):
        add("r40_parameter_selected_sources_incomplete", "evidence_insufficient")
    statuses = {row["result"] for row in rows}
    status = "failed" if "failed" in statuses else "evidence_insufficient" if "evidence_insufficient" in statuses else "not_applicable" if statuses == {"not_applicable"} else "passed"
    output = result("evaluate_r40_parameters", status,
                    facts={"scope": "declared_event_parameter_comparison_only", "wholeRuleAcceptance": "not_evaluated",
                           "parameterChecks": rows, "evidenceVerified": False},
                    checks=[check(row["code"], row["result"] == "passed", row["result"], "passed") for row in rows],
                    rule_version="r40-explicit-parameter-comparison-v1")
    output["evidenceRefs"] = refs
    return output
