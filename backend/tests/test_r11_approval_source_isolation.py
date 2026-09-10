from copy import deepcopy

import pytest
from test_r11_parameters import fixture
from test_r11_usage_inventory import batch

from libs.business_pack import load_business_pack
from libs.review_document_scope import freeze_document_scope
from libs.review_orchestrator.design_facts import build_design_business_facts
from libs.review_orchestrator.runtime_tools import dispatch_runtime_tool, runtime_tool_catalog
from libs.review_tools import compile_node_tool_plan, execute_node_tool_plan


@pytest.mark.parametrize('case,expected', [
    ('low_other_use', 'failed'), ('conflicted_other_use', 'failed'),
    ('malformed_conflict', 'failed'), ('missing_quote_other_use', 'failed'),
    ('low_signature', 'failed'), ('low_inventory', 'failed'),
    ('low_duplicate_use', 'evidence_insufficient'), ('low_owner', 'evidence_insufficient'),
    ('low_context', 'evidence_insufficient'), ('low_absence', 'evidence_insufficient'),
    ('absent_with_low_other_role', 'failed'), ('absent_with_low_same_role', 'evidence_insufficient')])
def test_untrusted_rows_do_not_erase_independent_failures_or_disappear_from_identity_checks(case, expected):
    state, run = fixture()
    args = batch()
    if case not in ('low_absence', 'absent_with_low_other_role', 'absent_with_low_same_role'):
        args['planUsages'][0]['startedAt'] = '2026-08-31'
    if case == 'low_other_use': args['planUsages'][1]['confidence'] = .4
    if case == 'conflicted_other_use': args['planUsages'][1]['conflicted'] = True
    if case == 'malformed_conflict': args['planUsages'][1]['conflicted'] = 'false'
    if case == 'low_signature': args['signatures'][0]['confidence'] = .4
    if case == 'low_inventory': args['usageInventory']['confidence'] = .4
    if case == 'low_duplicate_use': args['planUsages'].append(dict(deepcopy(args['planUsages'][0]), confidence=.4))
    if case == 'low_owner': args['ownerApproval']['confidence'] = .4
    if case == 'low_context': args['scope']['confidence'] = .4
    if case in ('low_absence', 'absent_with_low_other_role', 'absent_with_low_same_role'):
        args['signatures'][0]['signatureStatus'] = 'absent'
        if case == 'low_absence': args['signatures'][0]['confidence'] = .4
        if case == 'absent_with_low_other_role': args['signatures'][1]['confidence'] = .4
        if case == 'absent_with_low_same_role': args['signatures'].append(dict(deepcopy(args['signatures'][0]), confidence=.4))
    for schema, records, index in [
        ('construction_approval_context', [args['scope']], 0),
        ('construction_approval_signatures', args['signatures'], 0),
        ('construction_owner_approval', [args['ownerApproval']], 1),
        ('construction_plan_usage', args['planUsages'], 0),
        ('construction_plan_usage_inventory', [args['usageInventory']], 0)]:
        for i, record in enumerate(records):
            parse = state['ocr_parse_results'][index]
            table = deepcopy(parse['tables'][0])
            table.update(tableId=f'{schema}-{i}', businessSchema=schema, normalizedRows=[record],
                         contentMarkdown='批复 2026-09-01，采用 2026-08-31、2026-09-02；编制未签名')
            if case == 'missing_quote_other_use' and schema == 'construction_plan_usage' and i == 1:
                table['contentMarkdown'] = ''
            parse['tables'].append(table)
    run['documentScopeSnapshot'] = freeze_document_scope(run, state)
    before = deepcopy(state)
    facts = build_design_business_facts(state, run)
    plan = compile_node_tool_plan(load_business_pack('engineering_inspection_v1'), 'R11',
                                 available_tools={row['name'] for row in runtime_tool_catalog()})
    seen = []
    grounding_inputs = []

    def runner(name, arguments):
        if name == "validate_evidence_grounding" and arguments.get("profile") == "construction_plan_approval":
            grounding_inputs.append(deepcopy(arguments))
        output = dispatch_runtime_tool(state, name, arguments, context={'reviewRun': run})
        if name == 'evaluate_construction_plan' and arguments.get('profile') == 'construction_plan_approval':
            seen.append(output)
        return output

    output = execute_node_tool_plan(plan, facts=facts, document_version_ids=run['inputDocumentVersionIds'],
        evidence_facts=facts['judgment']['claimedFacts'], evidence_refs=facts['judgment']['evidenceRefs'], tool_runner=runner)
    atomic = next(row for row in output['atomicResults'] if row['atomicCheckId'] == 'AC-R11-01')
    assert atomic['result'] == expected
    assert state == before
    if case != 'low_context':
        assert len(seen) == 1
        assert len(grounding_inputs) == 1
        assert all(.75 <= ref['confidence'] <= 1 for ref in grounding_inputs[0]['evidenceRefs'])
        assert next(row for row in output['atomicResults'] if row['atomicCheckId'] == 'AC-R11-04')['result'] == 'evidence_insufficient'
        assert seen[0]['result'] == expected
        assert any(issue['code'] == 'r11_approval_record_source_untrusted' for issue in seen[0]['facts']['selectionIssues'])
        if case == 'low_duplicate_use':
            assert len(facts['r11']['approval']['planUsages']) == 3
        if expected == 'failed':
            assert any(row['result'] == 'failed' and row['evidenceRefs'] for row in seen[0]['facts']['approvalChecks'])
    else:
        assert 'approval' not in facts['r11']
