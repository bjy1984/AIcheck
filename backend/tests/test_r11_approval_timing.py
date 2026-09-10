from copy import deepcopy

import pytest
from test_r11_approval import body

from libs.review_orchestrator.runtime_tools import dispatch_runtime_tool
from libs.review_tools.r11_approval_timing import approval_timing


def timings(approved, started):
    args = body()
    args['ownerApproval'].update(approvedAt=approved)
    args['ownerApproval']['evidenceRefs'][0]['quotedText'] = f'批复时间：{approved}'
    args['planUsage'].update(startedAt=started)
    args['planUsage']['evidenceRefs'][0]['quotedText'] = f'采用时间：{started}'
    return args


@pytest.mark.parametrize('approved,started,expected', [
    ('2026-09-01', '2026-09-02', 'passed'), ('2026-09-03', '2026-09-02', 'failed'),
    ('2026-09-02', '2026-09-02', 'evidence_insufficient'),
    ('2026-09-02T08:00:00+08:00', '2026-09-02T01:00:00Z', 'passed'),
    ('2026-09-02T02:00:00Z', '2026-09-02T08:00:00+08:00', 'failed'),
    ('2026-09-02T00:00:00Z', '2026-09-02T08:00:00+08:00', 'evidence_insufficient'),
    ('2026-09-02T08:00:00Z', '2026-09-02T08:00:00.5Z', 'evidence_insufficient'),
    ('2026-09-02T08:00:00.1Z', '2026-09-02T08:00:00.2Z', 'passed'),
    ('2026-09-01', '2026-09-02T08:00:00Z', 'evidence_insufficient'),
    ('2026-09', '2026-09-02', 'evidence_insufficient'),
    ('2026-02-30', '2026-09-02', 'evidence_insufficient'),
    ('2026-09-02T08:00:00', '2026-09-02T09:00:00', 'evidence_insufficient')])
def test_time_precision_and_offsets_are_not_guessed(approved, started, expected):
    args = timings(approved, started)
    before = deepcopy(args)
    result = approval_timing(args['scope'], args['ownerApproval'], args['planUsage'])
    assert result['result'] == expected
    assert args == before


@pytest.mark.parametrize('case', ['wrong_cycle', 'wrong_version', 'unlocated_time', 'partial_date_quote', 'missing_usage', 'not_started'])
def test_timing_requires_matching_scope_and_its_own_exact_source(case):
    args = body()
    if case == 'wrong_cycle': args['planUsage']['approvalCycleId'] = 'OLD'
    if case == 'wrong_version': args['planUsage']['evidenceRefs'][0]['documentVersionId'] = 'OTHER'
    if case == 'unlocated_time': args['ownerApproval']['evidenceRefs'][0]['quotedText'] = '存在批复'
    if case == 'partial_date_quote': args['ownerApproval']['evidenceRefs'][0]['quotedText'] = '2026-09-01T09:00:00Z'
    if case == 'missing_usage': args['planUsage'] = None
    if case == 'not_started': args['planUsage']['usageStatus'] = 'not_started'
    output = dispatch_runtime_tool({}, 'evaluate_construction_plan', args)
    assert output['result'] == 'evidence_insufficient'


def test_late_approval_is_retained_with_other_missing_signature():
    args = timings('2026-09-03', '2026-09-02')
    args['signatures'].pop()
    output = dispatch_runtime_tool({}, 'evaluate_construction_plan', args)
    assert output['result'] == 'failed'
    assert any(row['code'] == 'r11_owner_approval_before_use' and row['result'] == 'failed' for row in output['facts']['approvalChecks'])


def test_ascii_label_separator_does_not_hide_supported_dates():
    args = body()
    args['ownerApproval']['evidenceRefs'][0]['quotedText'] = 'approvedAt:2026-09-01'
    args['planUsage']['evidenceRefs'][0]['quotedText'] = 'startedAt:2026-09-02'
    assert approval_timing(args['scope'], args['ownerApproval'], args['planUsage'])['result'] == 'passed'


@pytest.mark.parametrize('approved,started,expected', [('2026-09-01', '2026-09-02', 'passed'),
    ('2026-09-03', '2026-09-02', 'failed'), ('2026-09-02', '2026-09-02', 'evidence_insufficient')])
def test_frozen_usage_table_reaches_real_node_timing_check(approved, started, expected):
    from test_r11_parameters import fixture

    from libs.business_pack import load_business_pack
    from libs.review_document_scope import freeze_document_scope
    from libs.review_orchestrator.design_facts import build_design_business_facts
    from libs.review_orchestrator.runtime_tools import runtime_tool_catalog
    from libs.review_tools import compile_node_tool_plan, execute_node_tool_plan

    state, run = fixture()
    args = timings(approved, started)
    for schema, values, parse in [('construction_approval_context', [args['scope']], state['ocr_parse_results'][0]),
        ('construction_approval_signatures', args['signatures'], state['ocr_parse_results'][0]),
        ('construction_owner_approval', [args['ownerApproval']], state['ocr_parse_results'][1]),
        ('construction_plan_usage', [args['planUsage']], state['ocr_parse_results'][0])]:
        table = deepcopy(parse['tables'][0])
        table.update(tableId=schema, businessSchema=schema, normalizedRows=values,
                     contentMarkdown=f'明确记录：批复 {approved}，采用 {started}')
        parse['tables'].append(table)
    run['documentScopeSnapshot'] = freeze_document_scope(run, state)
    before = deepcopy(state)
    facts = build_design_business_facts(state, run)
    plan = compile_node_tool_plan(load_business_pack('engineering_inspection_v1'), 'R11',
                                  available_tools={row['name'] for row in runtime_tool_catalog()})
    seen = []

    def runner(name, arguments):
        result = dispatch_runtime_tool(state, name, arguments, context={'reviewRun': run})
        if name == 'evaluate_construction_plan' and arguments.get('profile') == 'construction_plan_approval':
            seen.append(result)
        return result

    output = execute_node_tool_plan(plan, facts=facts, document_version_ids=run['inputDocumentVersionIds'],
        evidence_facts=facts['judgment']['claimedFacts'], evidence_refs=facts['judgment']['evidenceRefs'], tool_runner=runner)
    assert len(seen) == 1
    timing = next(row for row in seen[0]['facts']['approvalChecks'] if row['code'] == 'r11_owner_approval_before_use')
    assert timing['result'] == expected
    assert {ref['documentVersionId'] for ref in timing['evidenceRefs']} == {'PLAN', 'DESIGN'}
    atomic = next(row for row in output['atomicResults'] if row['atomicCheckId'] == 'AC-R11-01')
    assert atomic['result'] == ('evidence_insufficient' if expected == 'passed' else expected)
    assert state == before
