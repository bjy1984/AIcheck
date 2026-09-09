from __future__ import annotations

from copy import deepcopy

import pytest

from libs.business_pack import load_business_pack
from libs.review_orchestrator.runtime_tools import runtime_tool_catalog
from libs.review_workstations import (
    WorkstationConfigurationError,
    apply_station_messages,
    freeze_station,
    load_registry,
    scope_catalog,
    station_snapshot,
    tool_allowed,
)


def run_for(node_id=24):
    pack = load_business_pack('engineering_inspection_v1')
    return {'id': 'RR-LAB', 'projectId': 'P-LAB', 'businessPackId': pack['id'], 'nodeId': node_id,
            'workstationSnapshot': freeze_station(node_id, pack, runtime_tool_catalog())}


def test_all_nodes_have_one_owner_and_each_real_binding_is_available():
    registry = load_registry()
    nodes = [node for row in registry['stations'] for node in row['nodeIds']]
    assert sorted(nodes) == list(range(1, 70))
    for node in nodes:
        run = run_for(node)
        snapshot = station_snapshot(run)
        assert snapshot['targetNodeId'] in snapshot['ownedNodeIds']
        scoped, meta = scope_catalog(run, runtime_tool_catalog())
        assert {item['name'] for item in scoped} == set(snapshot['allowedTools'])
        assert meta['stationId'] == snapshot['stationId']
    assert run_for(24)['workstationSnapshot']['stationId'] == 'A'
    assert run_for(65)['workstationSnapshot']['stationId'] == 'E'
    assert run_for(63)['workstationSnapshot']['stationId'] == 'B'


@pytest.mark.parametrize('node', [None, 0, 70, True, -1, 'x', 24.5])
def test_invalid_node_never_falls_back_to_full_agent(node):
    with pytest.raises(WorkstationConfigurationError):
        run_for(node)


def test_incomplete_bindings_and_missing_runtime_tools_block_freeze():
    pack = deepcopy(load_business_pack('engineering_inspection_v1'))
    pack['atomicCheckToolBindings'] = [row for row in pack['atomicCheckToolBindings'] if row['atomicCheckId'] != 'AC-R24-01']
    with pytest.raises(WorkstationConfigurationError, match='bindings_incomplete'):
        freeze_station(24, pack, runtime_tool_catalog())
    with pytest.raises(WorkstationConfigurationError, match='tools_missing'):
        freeze_station(24, load_business_pack('engineering_inspection_v1'), [])


def test_snapshot_is_immutable_and_cannot_be_reused_for_another_node():
    run = run_for()
    cloned = station_snapshot(run)
    cloned['systemPrompt'] = 'changed'
    assert station_snapshot(run)['systemPrompt'] != 'changed'
    run['nodeId'] = 25
    with pytest.raises(WorkstationConfigurationError, match='target_mismatch'):
        station_snapshot(run)
    run['nodeId'] = 24
    run['workstationSnapshot']['allowedTools'].append('evaluate_r23_valve_test_records')
    with pytest.raises(WorkstationConfigurationError, match='hash_mismatch'):
        station_snapshot(run)


def test_frozen_tool_removed_from_runtime_blocks_instead_of_expanding_permissions():
    run = run_for()
    with pytest.raises(WorkstationConfigurationError, match='tools_unavailable'):
        scope_catalog(run, [])
    assert not tool_allowed(run, 'evaluate_r23_valve_test_records')
    assert tool_allowed(run, 'get_document_ocr_result')


def test_specialized_loop_keeps_node_procedure_but_has_only_one_role():
    run = run_for(12)
    old = [{'role': 'system', 'content': '你是 R12 復核 Agent。必須先查候選，不得宣稱已完成官方核驗。'},
           {'role': 'user', 'content': '推進 R12'}]
    result = apply_station_messages(run, old)
    assert [row['role'] for row in result] == ['system', 'user', 'user']
    assert '工位 D' in result[0]['content']
    assert '必須先查候選' in result[1]['content']
    assert '你是 R12' not in result[1]['content']
    assert old[0]['role'] == 'system'
    assert apply_station_messages({'nodeId': 12}, old) is old


def test_formal_prompt_uses_frozen_station_and_keeps_target_rule(monkeypatch):
    from libs.review_orchestrator import execution as ex

    run = run_for()
    pack = load_business_pack('engineering_inspection_v1')
    monkeypatch.setattr(ex, 'select_prompt_template', lambda _: None)
    monkeypatch.setattr(ex, 'build_ai_review_prompt', lambda *args, **kwargs: {
        'system': 'LEGACY_OTHER_ROLE', 'user': 'LEGACY_ALL_NODES',
        'template': {'plannerPrompt': 'OTHER_PLANNER'}})
    monkeypatch.setattr(ex, 'audit_runtime_public_config', lambda **kwargs: {})
    monkeypatch.setattr(ex, 'grounding_prompt_block', lambda _: {
        'requirements': [], 'strictGroundingPolicy': {}, 'groundedOcrEvidence': []})
    monkeypatch.setattr(ex.checklist_mode, 'checklist_enabled', lambda: False)
    context = {'project': {'businessPackSnapshot': pack}, 'auditRuntime': {'mode': 'structured'},
               'groundingInput': {'groundingStatus': 'insufficient'}, 'currentRule': {'id': 'R24', 'criteria': '資格覆蓋'},
               'fields': [{'name': 'certificateNo', 'value': 'TEST'}]}
    result = ex.build_review_prompt_parts(run, context)
    assert '工位 A' in result['messages'][0]['content']
    assert 'LEGACY' not in str(result['messages'])
    assert result['userPayload']['currentRule']['criteria'] == '資格覆蓋'
    assert result['userPayload']['targetNodeId'] == 24
    assert result['userPayload']['plannerPrompt'] == ''
    assert 'evaluate_r23_valve_test_records' not in str(result['userPayload']['availableRuntimeTools'])


def test_tool_boundary_rejects_before_dispatch(monkeypatch):
    from libs.review_orchestrator import execution as ex

    monkeypatch.setattr(ex, 'append_tool_call', lambda *args: None)
    monkeypatch.setattr(ex, 'dispatch_runtime_tool', lambda *args, **kwargs: pytest.fail('must not dispatch'))
    result = ex.execute_agent_tool(run_for(), 'lab', 'evaluate_r23_valve_test_records', {}, {})
    assert result['errorCode'] == 'WORKSTATION_TOOL_NOT_ALLOWED'
