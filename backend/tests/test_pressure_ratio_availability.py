import pytest

from libs import regulatory_tables
from libs.review_orchestrator.design_facts import (
    design_special_requirements,
    frozen_special_requirement_rules,
)
from libs.review_tools.business_tools import evaluate_design_special_requirements


@pytest.mark.parametrize('value', [None, 0, -1, True, '1.5', float('nan'), float('inf')])
def test_invalid_standard_values_do_not_become_defaults(monkeypatch, value):
    monkeypatch.setattr(regulatory_tables, 'table', lambda *args: {'hydroTestRatio': value})
    assert regulatory_tables.pressure_test_ratios() == {'hydro': None, 'pneumatic': None, 'pneumaticMax': None}


def test_inverted_bounds_are_unavailable(monkeypatch):
    monkeypatch.setattr(regulatory_tables, 'table', lambda *args: {'hydroTestRatio': 1.5, 'pneumaticTestRatioMin': 2, 'pneumaticTestRatioMax': 1.33})
    assert regulatory_tables.pressure_test_ratios() == {'hydro': 1.5, 'pneumatic': None, 'pneumaticMax': None}


@pytest.mark.parametrize('method', ['压力试验', '耐压试验', '气液组合', '液压试验和气压试验'])
def test_unresolved_method_never_defaults_to_hydro(method):
    facts = design_special_requirements(f'依据 GB/T 20801.1-2025，{method}，试验压力为设计压力的 1.5 倍。', [])
    pressure = facts['domains']['pressureTest']['requirements']
    assert pressure.get('requiredTestPressureRatio') is None
    assert pressure.get('testPressureMeetsRatio') is None
    assert pressure.get('testPressureExceedsMax') is None


@pytest.mark.parametrize('method', ['液压试验', '气压试验'])
def test_missing_ratio_remains_insufficient_in_business_evaluation(monkeypatch, method):
    original = regulatory_tables.table
    monkeypatch.setattr(regulatory_tables, 'table', lambda *args: {} if args == ('gbt20801_inspection', 'pressureTest') else original(*args))
    facts = design_special_requirements(f'依据 GB/T 20801.1-2025，{method}，试验压力为设计压力的 1.5 倍，保压 10 min 无泄漏无变形。', [])
    output = evaluate_design_special_requirements({'requirements': facts['domains'], 'standardRules': frozen_special_requirement_rules(),
        'domains': ['pressureTest'], 'requiredPathsByDomain': {'pressureTest': ['requirements.method', 'requirements.testPressure', 'requirements.acceptanceCriteria']}})
    assert output['result'] == 'evidence_insufficient'
