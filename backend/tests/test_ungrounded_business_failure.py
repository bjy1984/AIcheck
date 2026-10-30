"""锚定门一条事实都没有、业务工具却判出不符合时，报需人工而不是证据不足。

ECD202 储罐 9：evaluate_design_special_requirements 判了 failed（27 项里 13 项不过，含泄漏试验没写方法、介质、压力），
validate_evidence_grounding 因为设计类事实没登记成带页码引文的 claimedFacts，拿到 0 条事实回证据不足，
聚合时一票否决，违规被盖成「证据不足」。门拿到了事实却核不过的，仍然一票否决。"""
from __future__ import annotations

from libs.review_orchestrator.output_contract import atomic_check_outcomes
from libs.review_tools.executor import (
    UNGROUNDED_FAILURE_WARNING,
    aggregate_tool_results,
    execute_node_tool_plan,
    ungrounded_business_failure,
)


def business(result: str, tool: str = "evaluate_design_special_requirements") -> dict:
    return {"toolName": tool, "status": "succeeded", "result": result, "facts": {}, "checks": [{"code": "ndt_specified", "passed": result == "passed"}]}


def gate(result: str = "evidence_insufficient", fact_count: int = 0) -> dict:
    return {"toolName": "validate_evidence_grounding", "status": "succeeded", "result": result,
            "facts": {"factCount": fact_count, "evidenceRefCount": 0}, "checks": []}


def test_business_failure_with_an_empty_grounding_gate_goes_to_a_human():
    outputs = [business("failed"), gate()]
    assert aggregate_tool_results(outputs) == "human_review_required"
    assert ungrounded_business_failure(outputs)


def test_gate_that_had_facts_but_could_not_ground_them_still_vetoes():
    outputs = [business("failed"), gate("evidence_insufficient", fact_count=3)]
    assert aggregate_tool_results(outputs) == "evidence_insufficient"
    assert not ungrounded_business_failure(outputs)


def test_only_a_business_failure_is_lifted_not_a_pass_or_a_human_review():
    assert aggregate_tool_results([business("passed"), gate()]) == "evidence_insufficient"
    assert aggregate_tool_results([business("human_review_required"), gate()]) == "evidence_insufficient"
    assert aggregate_tool_results([business("evidence_insufficient"), gate()]) == "evidence_insufficient"


def test_failed_gate_with_no_facts_also_counts_as_empty():
    assert aggregate_tool_results([business("failed"), gate("failed")]) == "human_review_required"


def test_a_grounded_pass_and_a_grounded_failure_are_unchanged():
    assert aggregate_tool_results([business("failed"), gate("passed", fact_count=2)]) == "failed"
    assert aggregate_tool_results([business("passed"), gate("passed", fact_count=2)]) == "passed"


def test_gate_output_that_does_not_report_a_fact_count_keeps_the_veto():
    """不知道有没有事实就不放行：只有门明确报出 factCount 为 0 才改报需人工。"""
    for broken in ({"toolName": "validate_evidence_grounding", "status": "succeeded", "result": "evidence_insufficient"},
                   {"toolName": "validate_evidence_grounding", "result": "evidence_insufficient", "facts": {}},
                   {"toolName": "validate_evidence_grounding", "result": "evidence_insufficient", "facts": {"factCount": "n/a"}}):
        assert aggregate_tool_results([business("failed"), broken]) == "evidence_insufficient"


def plan_item() -> dict:
    return {"atomicCheckId": "AC-R09-01", "sourceRuleId": "R09", "requiredFacts": [], "compilable": True, "missingTools": [],
            "tools": ["evaluate_design_special_requirements", "validate_evidence_grounding"], "parameters": {}}


def test_plan_result_carries_the_warning_and_the_outcome_view_shows_why():
    def runner(name: str, arguments: dict) -> dict:
        return business("failed") if name == "evaluate_design_special_requirements" else gate()

    output = execute_node_tool_plan([plan_item()], tool_runner=runner)
    atomic = output["atomicResults"][0]
    assert atomic["result"] == "human_review_required"
    assert UNGROUNDED_FAILURE_WARNING in atomic["warnings"]
    assert output["result"] == "human_review_required"

    outcome = atomic_check_outcomes([{"ruleCode": "engineering-inspection-r09", "atomicCheckResults": [atomic]}], {"businessPackId": "engineering_inspection_v1"})[0]
    assert outcome["result"] == "human_review_required"
    assert outcome["reason"] == UNGROUNDED_FAILURE_WARNING
    assert outcome["checks"], "不过的检查项要随结论一起带出去，人才有东西可看"


def test_plan_without_a_business_failure_has_no_warning():
    def runner(name: str, arguments: dict) -> dict:
        return business("passed") if name == "evaluate_design_special_requirements" else gate()

    atomic = execute_node_tool_plan([plan_item()], tool_runner=runner)["atomicResults"][0]
    assert atomic["result"] == "evidence_insufficient" and UNGROUNDED_FAILURE_WARNING not in atomic["warnings"]
