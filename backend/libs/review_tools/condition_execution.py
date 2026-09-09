"""Execute frozen structured replacements and retain all untouched atomic checks."""
from __future__ import annotations

from copy import deepcopy
from typing import Any
from uuid import uuid4

from libs.integrations.errors import IntegrationServiceError
from libs.raw_vault import (
    RawCaptureFailure,
    capture_tool_error,
    capture_tool_request,
    capture_tool_result,
    raw_capture_from_environment,
    raw_context_from_record,
)
from libs.review_condition_facts import condition_facts_from_run
from libs.review_condition_mapping import effective_condition_mapping
from libs.review_rule_snapshot import effective_rule_snapshot
from libs.review_tools.executor import aggregate_atomic_results, resolve_atomic_arguments, summarize
from libs.rule_condition_bindings import compile_condition_bindings
from libs.rule_conditions import evaluate_conditions


def prepare_condition_results(state: dict[str, Any], run: dict[str, Any], pack: dict[str, Any], *, raw_capture=None) -> dict[str, dict[str, Any]]:
    rule = effective_rule_snapshot(run)
    if not rule or rule.get("executionConditions") is None:
        return {}
    plan = compile_condition_bindings(rule, pack)
    if str(plan["nodeId"]) != str(run.get("nodeId")) or plan["businessPackId"] != run.get("businessPackId"):
        raise ValueError("condition_execution_scope_mismatch")
    facts, diagnostics = condition_facts_from_run(state, run, rule["executionConditions"], object_mapping=effective_condition_mapping(run, state))
    capture = raw_capture if raw_capture is not None else raw_capture_from_environment()
    capture_context = raw_context_from_record(run, stage="condition_evaluation") if capture is not None else None
    results = {}
    for replacement in plan["replacements"]:
        tool_call_id = f"TOOL-{uuid4().hex[:16].upper()}"
        request_event = None
        if capture_context is not None:
            request_event = capture_tool_request(capture, capture_context, "evaluate_saved_conditions",
                {"atomicCheckId": replacement["atomicCheckId"], "conditions": replacement["conditions"],
                 "facts": facts, "factDiagnostics": diagnostics, "conditionPlanHash": plan["planHash"]},
                provider_tool_call_id=tool_call_id)
            require_capture_success(request_event)
        try:
            evaluated = evaluate_conditions(replacement["conditions"], facts)
        except Exception as exc:
            if capture_context is not None:
                capture_tool_error(capture, capture_context, "evaluate_saved_conditions", exc, provider_tool_call_id=tool_call_id)
            raise
        refs = []
        for check in evaluated["checks"]:
            for ref in check["evidenceRefs"]:
                if ref not in refs:
                    refs.append(deepcopy(ref))
        output = {"toolName": "evaluate_saved_conditions", "toolCallId": tool_call_id, "status": "succeeded",
                  "result": {"pass": "passed", "fail": "failed"}.get(evaluated["result"], evaluated["result"]),
                  "conditionResults": evaluated, "factDiagnostics": diagnostics, "evidenceRefs": refs,
                  "conditionPlanHash": plan["planHash"], "ruleSnapshotHash": run["effectiveRuleSnapshot"]["snapshotHash"],
                  "sourceSnapshotHash": run["documentScopeSnapshot"]["snapshotHash"],
                  "conditionObjectMappingSnapshotHash": (run.get("conditionObjectMappingSnapshot") or {}).get("snapshotHash")}
        if capture_context is not None:
            result_event = capture_tool_result(capture, capture_context, "evaluate_saved_conditions", output,
                                              provider_tool_call_id=tool_call_id)
            require_capture_success(result_event)
            output["rawCapture"] = {"status": "captured", "requestEventId": request_event.id, "resultEventId": result_event.id}
        else:
            output["rawCapture"] = {"status": "not_configured"}
        results[replacement["atomicCheckId"]] = {"atomicCheckId": replacement["atomicCheckId"],
            "result": output["result"], "toolResults": [output], "warnings": [],
            "sourceMethod": "structured_conditions_v1",
            "planAtomicCheckIds": sorted(plan["retainedAtomicCheckIds"] + [row["atomicCheckId"] for row in plan["replacements"]])}
    return results


def execute_with_condition_replacements(plan, *, condition_results, base_executor, **kwargs):
    if not condition_results:
        return base_executor(plan, **kwargs)
    identities = [str(item.get("atomicCheckId")) for item in plan]
    if len(set(identities)) != len(identities) or set(condition_results) - set(identities):
        raise ValueError("condition_replacement_plan_mismatch")
    resolve_atomic_arguments(plan, kwargs.get("tool_arguments") or {}, kwargs.get("arguments_by_atomic_check") or {})
    for identity, result in condition_results.items():
        if set(result.get("planAtomicCheckIds") or []) != set(identities):
            raise ValueError("condition_replacement_coverage_mismatch")
        if result.get("atomicCheckId") != identity or result.get("result") not in {"passed", "failed", "evidence_insufficient", "not_applicable"}:
            raise ValueError("invalid_condition_replacement_result")
    retained = [item for item in plan if item["atomicCheckId"] not in condition_results]
    remaining_kwargs = {**kwargs, "arguments_by_atomic_check": {
        key: value for key, value in (kwargs.get("arguments_by_atomic_check") or {}).items() if key not in condition_results}}
    legacy = base_executor(retained, **remaining_kwargs)
    results = {item["atomicCheckId"]: item for item in legacy["atomicResults"]}
    if set(results) != {item["atomicCheckId"] for item in retained}:
        raise ValueError("condition_retained_results_incomplete")
    results.update(deepcopy(condition_results))
    ordered = [results[identity] for identity in identities]
    return {"result": aggregate_atomic_results(ordered), "atomicResults": ordered, "summary": summarize(ordered)}


def condition_source_rule_id(rule: dict[str, Any], pack: dict[str, Any]) -> str:
    compiled = compile_condition_bindings(rule, pack)
    sources = {str(row.get("sourceRuleId") or "") for row in pack.get("atomicChecks") or []
               if row.get("nodeId") == compiled["nodeId"]}
    if len(sources) != 1 or not next(iter(sources)):
        raise ValueError("condition_source_rule_ambiguous")
    return next(iter(sources))


def require_capture_success(event) -> None:
    if event is None or isinstance(event, RawCaptureFailure):
        raise IntegrationServiceError("raw_vault", "condition_capture", status_code=503, reason="CONDITION_TOOL_CAPTURE_FAILED")


def merge_semantic_condition_results(base: dict[str, Any], replacements: dict[str, dict[str, Any]]) -> dict[str, Any]:
    if not replacements:
        return base
    identities = next(iter(replacements.values())).get("planAtomicCheckIds") or []
    expected = set(identities)
    if not expected or len(expected) != len(identities) or set(replacements) - expected:
        raise ValueError("condition_semantic_plan_mismatch")
    for identity, result in replacements.items():
        if set(result.get("planAtomicCheckIds") or []) != expected or result.get("atomicCheckId") != identity:
            raise ValueError("condition_semantic_plan_mismatch")
        if result.get("result") not in {"passed", "failed", "evidence_insufficient", "not_applicable"}:
            raise ValueError("invalid_condition_replacement_result")
    rows = base.get("atomicResults") or []
    existing = {row.get("atomicCheckId"): row for row in rows}
    if len(existing) != len(rows) or set(existing) - expected or (expected - set(replacements)) - set(existing):
        raise ValueError("condition_semantic_retained_results_incomplete")
    merged = {**deepcopy(existing), **deepcopy(replacements)}
    ordered = [merged[identity] for identity in identities]
    counts = {status: sum(row["result"] == status for row in ordered) for status in {row["result"] for row in ordered}}
    return {"result": aggregate_atomic_results(ordered), "atomicResults": ordered,
            "summary": {**summarize(ordered), "resultCounts": counts,
                        "executionMode": "semantic_with_condition_replacements",
                        "nodeResultSource": "fixed_aggregator_over_retained_semantics_and_frozen_conditions"}}
