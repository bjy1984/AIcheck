from copy import deepcopy

from libs.review_orchestrator.output_contract import review_view_with_limitations


def test_only_actual_run_warnings_project_to_view_without_rewriting_verdict():
    run = {"reviewRunId": "CURRENT", "projectId": "P", "tenantId": "T", "nodeId": 39,
           "findingDrafts": [{"checklistVerdict": "不符合", "description": "Original business issue"}]}
    row = {"reviewRunId": "CURRENT", "atomicCheckResults": [
        {"atomicCheckId": "AC-R39-01", "warnings": ["pending_capability:method_specific_technical_requirements",
                                                  "pending_capability:method_specific_technical_requirements", "unrelated_warning"]}]}
    foreign = {**deepcopy(row), "reviewRunId": "OLDER"}
    wrong_scope = {**deepcopy(row), "projectId": "OTHER"}
    wrong_scope["atomicCheckResults"][0]["warnings"] = ["pending_capability:other_project"]
    state = {"rule_check_results": [row, foreign, wrong_scope]}
    original = deepcopy((run, state))
    view = review_view_with_limitations(run, state)
    assert view["automationLimitations"] == [{"atomicCheckId": "AC-R39-01",
        "code": "method_specific_technical_requirements", "requiresHumanReview": True}]
    assert view["findingDrafts"] == run["findingDrafts"]
    assert (run, state) == original


def test_no_recorded_warning_does_not_infer_pass_or_current_pack_limitations():
    run = {"reviewRunId": "OLD", "status": "completed"}
    state = {"rule_check_results": [], "rule_versions": [{"pendingCapabilities": ["new_capability"]}]}
    view = review_view_with_limitations(run, state)
    assert view == {**run, "automationLimitations": []}
    assert "reviewResult" not in view


def test_invalid_coverage_declaration_is_visible_instead_of_silently_hidden():
    state = {"rule_check_results": [{"reviewRunId": "R", "atomicCheckResults": [
        {"atomicCheckId": "A", "warnings": ["invalid_pending_capabilities"]}]}]}
    view = review_view_with_limitations({"reviewRunId": "R"}, state)
    assert view["automationLimitations"][0]["code"] == "invalid_pending_capabilities"
