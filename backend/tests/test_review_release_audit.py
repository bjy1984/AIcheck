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
