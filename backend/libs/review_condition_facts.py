"""Build condition trial inputs from scoped OCR, retaining ambiguity and locators."""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from libs.review_grounding import _position_failures
from libs.review_orchestrator.runtime_tools import selected_parse_results
from libs.rule_conditions import _applicability_leaves, validate_conditions


def condition_facts_from_run(state: dict[str, Any], run: dict[str, Any], conditions: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    validate_conditions(conditions)
    if not (run.get("documentScopeSnapshot") or {}).get("sourceFingerprint"):
        raise ValueError("trial_requires_frozen_document_scope")
    checks = conditions["checks"] + (_applicability_leaves(conditions["applicability"]) if "applicability" in conditions else [])
    names = {check["field"] for check in checks}
    candidates: dict[str, list[dict[str, Any]]] = {name: [] for name in names}
    for parse in selected_parse_results(state, {}, context={"reviewRun": run}):
        for field in parse.get("fields") or []:
            if not isinstance(field, dict):
                continue
            name = field.get("fieldName") or field.get("name")
            if name not in names:
                continue
            ref = {"documentVersionId": parse.get("documentVersionId"), "fieldId": field.get("id"),
                   "pageNo": field.get("pageNo"), "bbox": deepcopy(field.get("bbox"))}
            if field.get("correctionId"):
                ref["correctionId"] = field["correctionId"]
            candidates[name].append({"value": deepcopy(field.get("value", field.get("fieldValue"))),
                                     "unit": field.get("unit"), "evidenceRefs": [ref]})
    facts, diagnostics = {}, {}
    for name, rows in candidates.items():
        if not rows:
            diagnostics[name] = "field_missing"
            continue
        # Multiple occurrences can describe different welds or batches even if values agree.
        if len(rows) != 1:
            diagnostics[name] = "field_ambiguous_requires_object_mapping"
            continue
        fact = rows[0]
        ref = fact["evidenceRefs"][0]
        if _position_failures(ref["pageNo"], ref["bbox"], 0):
            diagnostics[name] = "field_locator_missing_or_invalid"
            continue
        facts[name] = fact
    return facts, diagnostics
