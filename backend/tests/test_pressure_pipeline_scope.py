from copy import deepcopy

import pytest

from libs.review_orchestrator.design_facts import (
    design_special_requirements,
    frozen_special_requirement_rules,
)
from libs.review_tools.business_tools import evaluate_design_special_requirements

TEXT = '依据 GB/T 20801.1-2025，液压试验，试验压力 1.5 MPa，保压 10 min 无泄漏无变形；气密性试验，泄漏试验压力 1 MPa，无泄漏。'


@pytest.mark.parametrize('values', [[1, 2], [2, 1], [1, 1], [1, None], [None, 1]])
def test_multiple_pipelines_never_supply_an_arbitrary_denominator(values):
    pipelines = [{'pipelineId': f'P{i}', 'designPressureMPa': value} for i, value in enumerate(values)]
    before = deepcopy(pipelines)
    facts = design_special_requirements(TEXT, pipelines)
    for name, comparison in [('pressureTest', 'testPressureMeetsRatio'), ('leakTest', 'leakPressureNotBelowDesign')]:
        requirements = facts['domains'][name]['requirements']
        assert requirements.get(comparison) is None
        assert requirements['designPressureScopeIssue'] == 'multiple_pipeline_scope_unresolved'
    output = evaluate_design_special_requirements({'requirements': facts['domains'], 'standardRules': frozen_special_requirement_rules(),
        'domains': ['pressureTest'], 'requiredPathsByDomain': {'pressureTest': ['requirements.method', 'requirements.testPressure', 'requirements.acceptanceCriteria']}})
    assert output['result'] == 'evidence_insufficient'
    assert pipelines == before


def test_single_pipeline_keeps_its_own_design_pressure():
    facts = design_special_requirements(TEXT, [{'pipelineId': 'P', 'designPressureMPa': 1}])
    assert facts['domains']['pressureTest']['requirements']['testPressureMeetsRatio'] is True
    assert facts['domains']['leakTest']['requirements']['leakPressureNotBelowDesign'] is True


def test_explicit_ratio_does_not_require_an_invented_denominator():
    facts = design_special_requirements('液压试验，试验压力为设计压力的 1.5 倍。',
                                       [{'pipelineId': 'A', 'designPressureMPa': 1}, {'pipelineId': 'B', 'designPressureMPa': 2}])
    assert facts['domains']['pressureTest']['requirements']['testPressureMeetsRatio'] is True
    # This checks the stated ratio only; it is not an absolute pressure/event match.
    assert 'designPressureScopeIssue' not in facts['domains']['pressureTest']['requirements']
