"""Build condition trial inputs from scoped OCR, retaining ambiguity and locators."""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from libs.review_grounding import _position_failures
from libs.review_orchestrator.runtime_tools import selected_parse_results
from libs.review_workstations import digest
from libs.rule_conditions import _applicability_leaves, validate_conditions


def condition_candidates_from_run(state: dict[str, Any], run: dict[str, Any], conditions: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
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
            candidate = {"value": deepcopy(field.get("value", field.get("fieldValue"))),
                         "unit": field.get("unit"), "evidenceRefs": [ref],
                         "objectType": field.get("objectType"), "objectId": field.get("objectId")}
            candidate["candidateId"] = digest({"field": name, **candidate})
            candidates[name].append(candidate)
    return candidates


def condition_facts_from_run(state: dict[str, Any], run: dict[str, Any], conditions: dict[str, Any], *,
                             object_mapping: dict[str, Any] | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    candidates = condition_candidates_from_run(state, run, conditions)
    return resolve_condition_candidates(candidates, object_mapping=object_mapping)


def resolve_condition_candidates(candidates, *, object_mapping=None):
    if object_mapping is not None:
        if (not isinstance(object_mapping, dict)
                or set(object_mapping) != {"subject", "fields", "confirmedSameObject"}
                or object_mapping["confirmedSameObject"] is not True):
            raise ValueError("condition_object_mapping_confirmation_required")
        subject, selections = object_mapping["subject"], object_mapping["fields"]
        if (not isinstance(subject, dict) or set(subject) != {"objectType", "objectId"}
                or subject["objectType"] not in {"weld", "material", "pipeline", "component", "project"}
                or not isinstance(subject["objectId"], str) or not subject["objectId"].strip()
                or len(subject["objectId"]) > 200):
            raise ValueError("condition_object_mapping_subject_invalid")
        if (not isinstance(selections, dict) or set(selections) - set(candidates)
                or any(not isinstance(value, str) or not value for value in selections.values())):
            raise ValueError("condition_object_mapping_fields_invalid")
    facts, diagnostics = {}, {}
    for name, rows in candidates.items():
        if object_mapping is not None:
            if name not in selections:
                diagnostics[name] = "field_object_mapping_required"
                continue
            rows = [row for row in rows if row["candidateId"] == selections[name]]
            if len(rows) != 1:
                raise ValueError("condition_object_mapping_candidate_missing_or_ambiguous")
            if any(rows[0].get(key) and rows[0][key] != subject[key] for key in ("objectType", "objectId")):
                raise ValueError("condition_object_mapping_subject_mismatch")
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
        facts[name] = {key: deepcopy(fact[key]) for key in ("value", "unit", "evidenceRefs")}
    return facts, diagnostics
