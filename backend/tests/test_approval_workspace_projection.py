from copy import deepcopy

from test_r11_approval_timing import timings
from test_review_b_workspace import HEADERS, PROJECT_ID, assert_ok, client
from test_review_b_workspace import setup_function as reset_workspace

from libs.db.repository import repo
from libs.review_orchestrator.runtime_tools import dispatch_runtime_tool


def setup_function():
    reset_workspace()


def test_recorded_tool_result_reaches_workspace_and_audit_without_rewriting_history():
    run = {'id': 'APPROVAL-HTTP', 'reviewRunId': 'APPROVAL-HTTP', 'projectId': PROJECT_ID,
           'tenantId': 'TENANT-DEFAULT', 'nodeId': 11, 'status': 'waiting_human_review', 'revision': 1,
           'createdAt': '2026-09-09 10:00:00', 'findingDrafts': []}
    repo.state['review_runs'].append(run)
    output = dispatch_runtime_tool({}, 'evaluate_construction_plan', timings('2026-09-03', '2026-09-02'))
    record = {'id': 'APPROVAL-CHECK', 'reviewRunId': run['id'], 'projectId': PROJECT_ID,
              'tenantId': 'TENANT-DEFAULT', 'nodeId': 11,
              'atomicCheckResults': [{'atomicCheckId': 'AC-R11-01', 'toolResults': [output]}]}
    repo.state['rule_check_results'].extend([record, dict(deepcopy(record), id='FOREIGN', tenantId='OTHER'),
                                           dict(deepcopy(record), id='OLD', reviewRunId='OLDER')])
    before = deepcopy((run, repo.state['rule_check_results']))
    workspace = assert_ok(client.get(f'/api/projects/{PROJECT_ID}/inspection/nodes/11/review-workspace',
                                    params={'reviewRunId': run['id']}, headers=HEADERS))
    audit = assert_ok(client.get(f'/api/review-runs/{run["id"]}/audit-view', headers=HEADERS))
    expected = output['facts']['approvalChecks']
    assert workspace['activeReviewRun']['approvalChecks'] == expected
    assert audit['reviewRun']['approvalChecks'] == expected
    assert expected[-1]['result'] == 'failed'
    assert expected[-1]['startedAt'] == '2026-09-02'
    assert (run, repo.state['rule_check_results']) == before
