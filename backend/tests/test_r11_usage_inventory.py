from copy import deepcopy

import pytest
from test_r11_approval import body

from libs.review_orchestrator.runtime_tools import dispatch_runtime_tool


def batch():
    args = body()
    args['planUsages'] = [dict(deepcopy(args['planUsage']), usageId=identity) for identity in ('U1', 'U2')]
    args['usageInventory'] = dict(deepcopy(args['scope']), complete=True, usageIds=['U1', 'U2'])
    return args


@pytest.mark.parametrize('case,expected', [('complete', 'passed'), ('missing', 'evidence_insufficient'),
    ('extra', 'evidence_insufficient'), ('duplicate', 'evidence_insufficient'),
    ('duplicate_inventory', 'evidence_insufficient'), ('wrong_scope', 'evidence_insufficient'),
    ('no_source', 'evidence_insufficient'), ('no_inventory', 'evidence_insufficient'),
    ('empty', 'evidence_insufficient'), ('malformed', 'evidence_insufficient'),
    ('late_and_missing', 'failed'), ('late_duplicate', 'evidence_insufficient')])
def test_batch_coverage_and_known_failures(case, expected):
    args = batch()
    if case == 'missing': args['planUsages'].pop()
    if case == 'extra': args['planUsages'].append(dict(deepcopy(args['planUsage']), usageId='U3'))
    if case in ('duplicate', 'late_duplicate'): args['planUsages'].append(deepcopy(args['planUsages'][0]))
    if case == 'duplicate_inventory': args['usageInventory']['usageIds'].append('U1')
    if case == 'wrong_scope': args['usageInventory']['approvalCycleId'] = 'OLD'
    if case == 'no_source': args['usageInventory']['evidenceRefs'] = []
    if case == 'no_inventory': args.pop('usageInventory')
    if case == 'empty': args['planUsages'] = []
    if case == 'malformed': args['planUsages'].append(None)
    if case in ('late_and_missing', 'late_duplicate'):
        args['planUsages'][0]['startedAt'] = '2026-08-31'
        args['planUsages'][0]['evidenceRefs'][0]['quotedText'] = '采用：2026-08-31'
    if case == 'late_and_missing': args['planUsages'].pop()
    before = deepcopy(args)
    output = dispatch_runtime_tool({}, 'evaluate_construction_plan', args)
    assert output['result'] == expected
    assert args == before
    checks = output['facts']['approvalChecks']
    if case == 'late_and_missing':
        assert any(row.get('usageId') == 'U1' and row['result'] == 'failed' for row in checks)
        assert any(row.get('usageId') == 'U2' and row['result'] == 'evidence_insufficient' for row in checks)
