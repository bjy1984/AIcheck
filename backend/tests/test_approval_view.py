from copy import deepcopy

from libs.review_orchestrator.output_contract import review_view_with_limitations


def test_recorded_approval_projection_is_scoped_and_does_not_change_history():
    run = {'id': 'RUN', 'tenantId': 'T', 'projectId': 'P', 'nodeId': 11}
    row = {'code': 'r11_owner_approval_before_use', 'result': 'failed', 'usageId': 'U1',
           'startedAt': '2026-08-31', 'internalSecret': 'not exposed', 'evidenceRefs': [{'documentVersionId': 'V', 'pageNo': 2}]}
    atomic = {'atomicCheckId': 'AC-R11-01', 'toolResults': [{'toolName': 'evaluate_construction_plan', 'facts': {'approvalChecks': [row]}}]}
    record = {'reviewRunId': 'RUN', 'tenantId': 'T', 'projectId': 'P', 'nodeId': 11, 'atomicCheckResults': [atomic]}
    state = {'rule_check_results': [record, dict(deepcopy(record), tenantId='OTHER'), dict(deepcopy(record), reviewRunId='OLD')]}
    before = deepcopy(state)
    view = review_view_with_limitations(run, state)
    assert view['approvalChecks'] == [{key: value for key, value in row.items() if key != 'internalSecret'}]
    assert state == before
    assert 'approvalChecks' not in run
    view['approvalChecks'][0]['evidenceRefs'].clear()
    assert state == before


def test_other_atomic_tools_and_legacy_empty_results_do_not_invent_approval_checks():
    assert review_view_with_limitations({'id': 'R'}, {}).get('approvalChecks', []) == []

    state = {'rule_check_results': [{'reviewRunId': 'R', 'atomicCheckResults': [
        {'atomicCheckId': 'AC-R11-02', 'toolResults': [{'toolName': 'evaluate_construction_plan', 'facts': {'approvalChecks': [{'code': 'ignored'}]}}]},
        {'atomicCheckId': 'AC-R11-01', 'toolResults': [{'toolName': 'other_tool', 'facts': {'approvalChecks': [{'code': 'ignored'}]}}]}]}]}
    assert review_view_with_limitations({'id': 'R'}, state).get('approvalChecks', []) == []
