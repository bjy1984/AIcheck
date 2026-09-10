from __future__ import annotations

from scripts.audit_review_release import audit


def test_release_inventory_distinguishes_compilation_from_business_acceptance():
    report = audit()
    assert report['ruleCount'] == 69 and report['atomicCheckCount'] == 194
    assert all(row['allToolsRegistered'] for row in report['rules'])
    assert all(row['emptyInputResult'] == 'evidence_insufficient' for row in report['rules'])
    assert not report['releaseReady']
    assert 'unconfigured_generic_interpreters' in report['blockers']
    # 具体举一条仍未配置判定的规则，防止"发布清单看起来干净"。补上一条就把例子换成
    # 另一条仍未配置的；数量本身由 tests/test_generic_interpreter_gap.py 钉住。
    # 2026-09-10：原例 R43 已按 GB/T 20801.1-2025 8.5 补上判定，改为 R56；同日 R56 也按
    # TSG 92-2026 补上，再改为 R51。R51 的规则包登记的是 7.7.12 支吊架，与"绝缘支撑"
    # 不符——那是条款挂错，需要人工重新指认后才谈得上冻结判据，短期内不会被补上。
    assert any(row['rule'] == 'R51' and row['unconfiguredInterpreters'] for row in report['rules'])


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
