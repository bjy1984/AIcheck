from copy import deepcopy

import pytest

from libs import regulatory_tables
from libs.review_orchestrator.design_facts import (
    design_special_requirements,
    frozen_special_requirement_rules,
)
from libs.review_tools.business_tools import evaluate_design_special_requirements


def evaluate(method, ratio, *, missing_max=False, monkeypatch=None, yield_limit=None):
    if missing_max:
        original = regulatory_tables.table
        def table(*keys):
            row = deepcopy(original(*keys))
            if keys == ('gbt20801_inspection', 'pressureTest'):
                row.pop('pneumaticTestRatioMax', None)
            return row
        monkeypatch.setattr(regulatory_tables, 'table', table)
    text = f'依据 GB/T 20801.1-2025，{method}，试验压力为设计压力的 {ratio} 倍，保压 10 min 无泄漏无变形。'
    if yield_limit is not None:
        text += f'屈服强度极限时试验压力为 {yield_limit} MPa。'
    facts = design_special_requirements(text, [])
    return evaluate_design_special_requirements({'requirements': facts['domains'], 'standardRules': frozen_special_requirement_rules(),
        'domains': ['pressureTest'], 'requiredPathsByDomain': {'pressureTest': ['requirements.method', 'requirements.testPressure', 'requirements.acceptanceCriteria']}})


# 2026-09-10：气压试验加入 8.6.1.4 e) 2）的第二个上限（屈服强度极限时试验压力的 90%）后，
# 只写倍率的气压方案不再判 passed——第二个上限算不出来就是只判了一半，报通过等于放行。
# 想验证倍率本身合格，必须同时给出屈服强度极限对应压力（下面用 yield_limit 传入）。
@pytest.mark.parametrize('method,ratio,expected', [('气压试验', '1.3304', 'failed'),
    ('气压试验', '1.33', 'evidence_insufficient'), ('气压试验', '1.1', 'evidence_insufficient'),
    ('气压试验', '1.0996', 'failed'), ('液压试验', '1.5', 'passed'),
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


def test_yield_limit_sentence_is_not_mistaken_for_the_test_pressure():
    """「屈服强度极限时试验压力为 X MPa」里也含「试验压力…MPa」。

    不加断言会被当成本次试验压力，再与倍率对不上就误报矛盾——与此前泄漏、气密压力
    被误读是同一类。
    """
    facts = design_special_requirements(
        '依据 GB/T 20801.1-2025，气压试验，试验压力为设计压力的 1.2 倍，保压 10 min 无泄漏。'
        '屈服强度极限时试验压力为 1.4 MPa。', [])
    pressure = facts['domains']['pressureTest']['requirements']
    assert pressure['yieldLimitPressureMPa'] == 1.4
    assert pressure.get('testPressureMPa') is None, '屈服极限那句不是本次试验压力'
    assert pressure.get('pressureRatioConflict') in (None, False), '不该因为误读而报矛盾'


def test_second_pneumatic_ceiling_needs_an_absolute_test_pressure():
    """倍率式表述算不出绝对压力，第二个上限就判不了——保留证据不足，不当成没超过。"""
    ratio_only = evaluate('气压试验', '1.2', yield_limit='1.4')
    assert ratio_only['result'] == 'evidence_insufficient'
    assert 'pneumatic_yield_ceiling' in ratio_only['domainResults'][0]['unresolvedRules']
    # 液压不适用第二个上限
    assert 'pneumatic_yield_ceiling' in evaluate('液压试验', '1.5')['domainResults'][0]['notApplicableRules']
