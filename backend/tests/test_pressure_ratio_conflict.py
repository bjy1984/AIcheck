import pytest

from libs.review_orchestrator.design_facts import (
    design_special_requirements,
    frozen_special_requirement_rules,
)
from libs.review_orchestrator.pressure_ratio_calculation import pressure_ratio_calculation
from libs.review_tools.business_tools import evaluate_design_special_requirements


@pytest.mark.parametrize('pressure,conflict,expected', [('1.5', False, 'passed'), ('1.2', True, 'evidence_insufficient'), ('1.5004', True, 'evidence_insufficient')])
def test_stated_ratio_and_absolute_pressure_must_agree(pressure, conflict, expected):
    facts = design_special_requirements(f'依据 GB/T 20801.1-2025，液压试验，试验压力 {pressure} MPa，试验压力为设计压力的 1.5 倍，试验温度 20℃，保压 10 min 无泄漏无变形。', [{'designPressureMPa': 1, 'designTemperatureC': 20}])
    requirements = facts['domains']['pressureTest']['requirements']
    assert requirements['pressureRatioConflict'] is conflict
    assert requirements.get('testPressureMeetsRatio') is (None if conflict else True)
    output = evaluate_design_special_requirements({'requirements': facts['domains'], 'standardRules': frozen_special_requirement_rules(),
        'domains': ['pressureTest'], 'requiredPathsByDomain': {'pressureTest': ['requirements.method', 'requirements.testPressure', 'requirements.acceptanceCriteria']}})
    assert output['result'] == expected


@pytest.mark.parametrize('label', ['泄漏试验压力', '气密性试验压力', '气密试验压力'])
def test_leak_pressure_is_not_the_absolute_pressure_of_the_strength_test(label):
    facts = design_special_requirements(f'液压试验，试验压力为设计压力的 1.5 倍。{label} 1 MPa。', [{'designPressureMPa': 1}])
    requirements = facts['domains']['pressureTest']['requirements']
    assert 'testPressureMPa' not in requirements
    assert 'pressureRatioConflict' not in requirements
    assert requirements['testPressureMeetsRatio'] is True


def test_exact_arithmetic_distinguishes_conflicts_even_when_display_rounds():
    assert pressure_ratio_calculation('1.5', '1.499999999999999999999', 1, 1.5, None) == (None, None, None)
    assert pressure_ratio_calculation('1.5', '2.4', 1.6, 1.5, None) == (1.5, True, None)
