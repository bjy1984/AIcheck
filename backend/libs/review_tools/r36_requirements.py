"""Combine explicit design/standard constraints without choosing one source as truth."""
from __future__ import annotations

from copy import deepcopy
from typing import Any


def combine_r36_requirements(design: Any, standards: Any) -> tuple[list[dict[str, Any]], list[str]]:
    if not isinstance(design, list) or standards is not None and not isinstance(standards, list):
        return [], ["r36_requirement_collections_invalid"]
    rows, issues = [], []
    for origin, records in (("design", design), ("standard", standards or [])):
        for record in records:
            if not isinstance(record, dict):
                issues.append("r36_requirement_record_invalid")
                continue
            if origin == "standard" and any(not isinstance(record.get(key), str) or not record[key].strip() for key in ("standardRef", "clauseRef")):
                issues.append("r36_standard_basis_unidentified")
            rows.append({**deepcopy(record), "requirementOrigin": origin})
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        identity = row.get("objectId"), row.get("method")
        if all(isinstance(value, str) and value.strip() for value in identity):
            groups.setdefault(identity, []).append(row)
    for records in groups.values():
        keys = [(row["requirementOrigin"],
                 *(row.get(key) if row["requirementOrigin"] == "standard" and isinstance(row.get(key), str) else None
                   for key in ("standardRef", "clauseRef"))) for row in records]
        # One design row; different named standard clauses may jointly constrain it.
        if len(keys) != len(set(keys)):
            issues.append("r36_requirement_source_ambiguous")
        required = [row for row in records if row.get("required") is True]
        for field, allowed_key in (("timing", "allowedTiming"), ("acceptanceLevel", "allowedAcceptanceLevels")):
            sets = []
            for row in required:
                values = row.get(allowed_key)
                if isinstance(values, list) and values and all(isinstance(value, str) and value for value in values):
                    sets.append(set(values))
                elif isinstance(row.get(field), str) and row[field]:
                    sets.append({row[field]})
            if sets and not set.intersection(*sets):
                # Disjoint labels without an approved equivalence/ranking mapping
                # are an unresolved basis conflict, not a defect in the plan.
                issues.append("r36_" + field + "_requirements_conflict")
    return rows, sorted(set(issues))
