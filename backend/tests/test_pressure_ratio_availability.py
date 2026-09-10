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
    assert regulatory_tables.pressure_test_ratios() == {
        'hydro': None, 'pneumatic': None, 'pneumaticMax': None, 'pneumaticYieldFactor': None}


def test_inverted_bounds_are_unavailable(monkeypatch):
    monkeypatch.setattr(regulatory_tables, 'table', lambda *args: {'hydroTestRatio': 1.5, 'pneumaticTestRatioMin': 2, 'pneumaticTestRatioMax': 1.33})
    assert regulatory_tables.pressure_test_ratios() == {
        'hydro': 1.5, 'pneumatic': None, 'pneumaticMax': None, 'pneumaticYieldFactor': None}


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


@pytest.mark.parametrize('value', [None, 0, -1, True, '0.9', 1.2, float('nan')])
def test_invalid_yield_factor_never_becomes_a_default(monkeypatch, value):
    """屈服上限系数无效时保持不可用；大于 1 的系数会把上限抬高，同样不许当默认值。"""
    monkeypatch.setattr(regulatory_tables, 'table',
                        lambda *args: {'hydroTestRatio': 1.5, 'pneumaticTestRatioMin': 1.1,
                                       'pneumaticTestRatioMax': 1.33, 'pneumaticYieldCeilingFactor': value})
    assert regulatory_tables.pressure_test_ratios()['pneumaticYieldFactor'] is None


def test_yield_ceiling_is_computed_only_from_a_stated_yield_limit_pressure():
    """屈服上限要用设计文件写明的「屈服强度极限时试验压力」；没写就算不出，保持不可用。"""
    stated = design_special_requirements(
        '依据 GB/T 20801.1-2025，气压试验，试验压力为 1.2 MPa，屈服强度极限时试验压力为 1.25 MPa。', [])
    pressure = stated['domains']['pressureTest']['requirements']
    assert pressure['pneumaticYieldCeilingMPa'] == 1.125
    assert pressure['testPressureExceedsYieldCeiling'] is True

    silent = design_special_requirements(
        '依据 GB/T 20801.1-2025，气压试验，试验压力为 1.2 MPa。', [])
    quiet = silent['domains']['pressureTest']['requirements']
    # _domain 会滤掉 None 值，所以算不出来时这两个键直接不存在；
    # 冻结判据用 read_path 读不到路径同样得 None，被当成未决而不是"没超过"。
    assert quiet.get('pneumaticYieldCeilingMPa') is None
    assert quiet.get('testPressureExceedsYieldCeiling') is None, '算不出来不能当成没超过'


def test_frozen_rules_carry_the_second_pneumatic_ceiling():
    checks = frozen_special_requirement_rules()['pressureTest']['checks']
    codes = [item['code'] for item in checks]
    assert 'pneumatic_ratio_ceiling' in codes and 'pneumatic_yield_ceiling' in codes
    yield_rule = next(item for item in checks if item['code'] == 'pneumatic_yield_ceiling')
    assert yield_rule['applicabilityPath'] == 'requirements.pneumaticTest'
    assert yield_rule['expected'] is False
