from copy import deepcopy

import pytest

from libs import regulatory_tables
from libs.review_orchestrator.design_facts import (
    design_special_requirements,
    frozen_special_requirement_rules,
)
from libs.review_tools.business_tools import evaluate_design_special_requirements


def evaluate(method, ratio, *, missing_max=False, monkeypatch=None):
    if missing_max:
        original = regulatory_tables.table
        def table(*keys):
            row = deepcopy(original(*keys))
            if keys == ('gbt20801_inspection', 'pressureTest'):
                row.pop('pneumaticTestRatioMax', None)
            return row
        monkeypatch.setattr(regulatory_tables, 'table', table)
    facts = design_special_requirements(f'依据 GB/T 20801.1-2025，{method}，试验压力为设计压力的 {ratio} 倍，保压 10 min 无泄漏无变形。', [])
    return evaluate_design_special_requirements({'requirements': facts['domains'], 'standardRules': frozen_special_requirement_rules(),
        'domains': ['pressureTest'], 'requiredPathsByDomain': {'pressureTest': ['requirements.method', 'requirements.testPressure', 'requirements.acceptanceCriteria']}})


@pytest.mark.parametrize('method,ratio,expected', [('气压试验', '1.3304', 'failed'), ('气压试验', '1.33', 'passed'),
    ('气压试验', '1.1', 'passed'), ('气压试验', '1.0996', 'failed'), ('液压试验', '1.5', 'passed'),
    ('压力试验', '1.2', 'evidence_insufficient'), ('气液组合', '1.2', 'evidence_insufficient')])
def test_ceiling_reaches_frozen_business_rule_and_is_not_required_for_hydro(method, ratio, expected):
    output = evaluate(method, ratio)
    assert output['result'] == expected
    domain = output['domainResults'][0]
    if method == '液压试验': assert 'pneumatic_ratio_ceiling' in domain['notApplicableRules']
    if method == '气压试验' and expected == 'failed' and ratio == '1.3304':
        assert 'pneumatic_ratio_ceiling' in domain['violations']


def test_missing_ceiling_cannot_pass_but_does_not_hide_known_low_pressure(monkeypatch):
    assert evaluate('气压试验', '1.2', missing_max=True, monkeypatch=monkeypatch)['result'] == 'evidence_insufficient'
    assert evaluate('气压试验', '1.0')['result'] == 'failed'
