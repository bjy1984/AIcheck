import pytest

from libs.review_orchestrator.design_facts import design_special_requirements
from libs.review_orchestrator.pressure_ratio_calculation import pressure_ratio_calculation


@pytest.mark.parametrize('method,pressure,design,meets,exceeds', [
    ('液压试验', '1.4996', 1, False, None), ('液压试验', '2.4', 1.6, True, None),
    ('气压试验', '1.0996', 1, False, False), ('气压试验', '1.3304', 1, True, True),
    ('气压试验', '1.33', 1, True, False), ('液压试验', '0', 1, False, None)])
def test_source_pressure_comparison_does_not_round_across_limits(method, pressure, design, meets, exceeds):
    facts = design_special_requirements(f'{method}，试验压力 {pressure} MPa。', [{'designPressureMPa': design}])
    values = facts['domains']['pressureTest']['requirements']
    assert values.get('testPressureMeetsRatio') is meets
    assert values.get('testPressureExceedsMax') is exceeds


def test_float_display_does_not_control_exact_comparison():
    display, meets, _ = pressure_ratio_calculation('1.49999999999999999999999999999', None, None, 1.5, None)
    assert display == 1.5
    assert meets is False


@pytest.mark.parametrize('explicit,pressure,design', [(None, '1', 0), (None, '1', -1),
    (None, '1', True), (None, 'bad', 1), ('bad', '2', 1), ('nan', None, None), ('1e999', None, None), ('1e9999999999', None, None), ('3/2', None, None)])
def test_invalid_values_do_not_fall_back_or_raise(explicit, pressure, design):
    assert pressure_ratio_calculation(explicit, pressure, design, 1.5, 1.33) == (None, None, None)


@pytest.mark.parametrize('design', [True, float('nan'), float('inf'), 0, -1])
def test_invalid_design_pressure_cannot_become_a_denominator(design):
    facts = design_special_requirements('液压试验，试验压力 1.5 MPa。', [{'designPressureMPa': design}])
    assert facts['domains']['pressureTest']['requirements'].get('testPressureMeetsRatio') is None


@pytest.mark.parametrize('pressure,expected', [('1.4996', 'failed'), ('1.5', 'passed')])
def test_exact_lower_bound_reaches_existing_business_rule(pressure, expected):
    from libs.review_orchestrator.design_facts import frozen_special_requirement_rules
    from libs.review_tools.business_tools import evaluate_design_special_requirements

    facts = design_special_requirements(f'依据 GB/T 20801.1-2025，液压试验，试验压力 {pressure} MPa，保压 10 min 无泄漏无变形。',
                                       [{'designPressureMPa': 1}])
    output = evaluate_design_special_requirements({'requirements': facts['domains'], 'standardRules': frozen_special_requirement_rules(),
        'domains': ['pressureTest'], 'requiredPathsByDomain': {'pressureTest': ['requirements.method', 'requirements.testPressure', 'requirements.acceptanceCriteria']}})
    assert output['result'] == expected
