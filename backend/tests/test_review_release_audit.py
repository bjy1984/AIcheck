from __future__ import annotations

from scripts.audit_review_release import audit


def test_release_inventory_distinguishes_compilation_from_business_acceptance():
    report = audit()
    assert report['ruleCount'] == 69 and report['atomicCheckCount'] == 194
    assert all(row['allToolsRegistered'] for row in report['rules'])
    assert all(row['emptyInputResult'] == 'evidence_insufficient' for row in report['rules'])
    assert not report['releaseReady']
    assert 'unconfigured_generic_interpreters' in report['blockers']
    assert any(row['rule'] == 'R43' and row['unconfiguredInterpreters'] for row in report['rules'])


def test_profile_specific_handler_is_identified_without_clearing_remaining_work():
    from copy import deepcopy

    from libs.business_pack import load_business_pack

    pack = load_business_pack('engineering_inspection_v1')
    report = audit(pack)
    row = next(row for row in report['rules'] if row['rule'] == 'R40')
    assert row['profileDedicatedTools'] == [{'atomicCheckId': 'AC-R40-01', 'tool': 'evaluate_ndt_process', 'profile': 'ndt_record_report'}]
    assert 'evaluate_ndt_process' not in row['genericInterpreters']
    assert row['pendingCapabilities'] == ['design_requirements', 'report_results', 'technical_parameters']
    assert 'pending_business_capabilities' in report['blockers']
    assert row['emptyInputResult'] == 'evidence_insufficient'
    assert not row['pilotEnabled'] and not report['releaseReady']
    assert set(row['scenarioAcceptance'].values()) == {'not_recorded'}
    changed = deepcopy(pack)
    binding = next(item for item in changed['atomicCheckToolBindings'] if item['atomicCheckId'] == 'AC-R40-01')
    binding['parameters']['profile'] = 'another_profile'
    other = next(row for row in audit(changed)['rules'] if row['rule'] == 'R40')
    assert not other['profileDedicatedTools']
    assert 'evaluate_ndt_process' in other['unconfiguredInterpreters']
