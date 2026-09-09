"""Execute frozen structured replacements and retain all untouched atomic checks."""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from libs.review_condition_facts import condition_facts_from_run
from libs.review_rule_snapshot import effective_rule_snapshot
from libs.review_tools.executor import aggregate_atomic_results, resolve_atomic_arguments, summarize
from libs.rule_condition_bindings import compile_condition_bindings
from libs.rule_conditions import evaluate_conditions


def prepare_condition_results(state: dict[str, Any], run: dict[str, Any], pack: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rule = effective_rule_snapshot(run)
    if not rule or rule.get("executionConditions") is None:
        return {}
    plan = compile_condition_bindings(rule, pack)
    if str(plan["nodeId"]) != str(run.get("nodeId")) or plan["businessPackId"] != run.get("businessPackId"):
        raise ValueError("condition_execution_scope_mismatch")
    facts, diagnostics = condition_facts_from_run(state, run, rule["executionConditions"])
    results = {}
    for replacement in plan["replacements"]:
        evaluated = evaluate_conditions(replacement["conditions"], facts)
        refs = []
        for check in evaluated["checks"]:
            for ref in check["evidenceRefs"]:
                if ref not in refs:
                    refs.append(deepcopy(ref))
        output = {"toolName": "evaluate_saved_conditions", "status": "succeeded",
                  "result": {"pass": "passed", "fail": "failed"}.get(evaluated["result"], evaluated["result"]),
                  "conditionResults": evaluated, "factDiagnostics": diagnostics, "evidenceRefs": refs,
                  "conditionPlanHash": plan["planHash"], "ruleSnapshotHash": run["effectiveRuleSnapshot"]["snapshotHash"],
                  "sourceSnapshotHash": run["documentScopeSnapshot"]["snapshotHash"]}
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
