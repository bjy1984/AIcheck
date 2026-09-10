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
    # 液压用例写明试验温度不低于设计温度：公式(54) 的温度修正因此不适用，
    # 这些用例继续只测倍率上下限本身。
    text = (f'依据 GB/T 20801.1-2025，{method}，试验压力为设计压力的 {ratio} 倍，'
            '试验温度 20℃，保压 10 min 无泄漏无变形。')
    if yield_limit is not None:
        text += f'屈服强度极限时试验压力为 {yield_limit} MPa。'
    facts = design_special_requirements(text, [{'designPressureMPa': 1, 'designTemperatureC': 20}])
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


# 2026-09-10：8.6.1.3 b) 2) 的温度修正（公式 54）与 d) 的折减例外方向相反，
# 各自只能推翻一个方向的结论。把这条对称性钉住：
#   温度修正只抬高要求 → 不允许"基础 1.5 倍通过"直接宣布符合；
#   折减例外只降低要求 → 不允许"不足 1.5 倍"直接宣布不符合。
def _hydro(text, pipelines):
    from libs.review_orchestrator.design_facts import (
        design_special_requirements,
        frozen_special_requirement_rules,
    )
    from libs.review_tools.business_tools import evaluate_design_special_requirements

    facts = design_special_requirements(text, pipelines)
    output = evaluate_design_special_requirements(
        {'requirements': facts['domains'], 'standardRules': frozen_special_requirement_rules(),
         'domains': ['pressureTest'],
         'requiredPathsByDomain': {'pressureTest': ['requirements.method', 'requirements.testPressure',
                                                    'requirements.acceptanceCriteria']}})
    return facts['domains']['pressureTest']['requirements'], output


def test_temperature_correction_blocks_a_pass_it_cannot_compute():
    """设计温度高于试验温度时公式(54) 抬高要求；S1/S2 取不到就不能宣布符合。"""
    text = ('依据 GB/T 20801.1-2025，液压试验，试验压力为设计压力的 1.5 倍，'
            '试验温度 20℃，保压 10 min 无泄漏无变形。')
    facts, output = _hydro(text, [{'designPressureMPa': 1, 'designTemperatureC': 260}])
    assert facts['temperatureCorrectionApplies'] is True
    # _domain() 会把 None 值剔掉，所以判不了的字段是「键不存在」，要用 .get()
    assert facts.get('temperatureCorrectionResolved') is None
    assert facts.get('ratioUndecidedReason') == 'hydro_temperature_correction_unresolved'
    assert facts['testPressureMeetsRatio'] is True, '基础倍率本身仍然算得出来，字段含义不变'
    assert output['result'] == 'evidence_insufficient', '算不清修正就不能报符合'


def test_temperature_correction_is_evaluated_when_the_stress_ratio_is_given():
    text = ('依据 GB/T 20801.1-2025，液压试验，试验压力为设计压力的 1.8 倍，'
            '试验温度 20℃，S1/S2 = 1.15，保压 10 min 无泄漏无变形。')
    facts, output = _hydro(text, [{'designPressureMPa': 1, 'designTemperatureC': 260}])
    assert facts['temperatureCorrectedRatio'] == 1.725
    assert facts['temperatureCorrectionResolved'] is True
    assert output['result'] == 'passed'

    low = ('依据 GB/T 20801.1-2025，液压试验，试验压力为设计压力的 1.6 倍，'
           '试验温度 20℃，S1/S2 = 1.15，保压 10 min 无泄漏无变形。')
    facts_low, output_low = _hydro(low, [{'designPressureMPa': 1, 'designTemperatureC': 260}])
    assert facts_low['temperatureCorrectionResolved'] is False
    assert output_low['result'] == 'failed', '1.6 倍过了 1.5 倍这一关，却不满足修正后的 1.725 倍'


def test_temperature_correction_does_not_apply_when_test_is_not_colder():
    text = ('依据 GB/T 20801.1-2025，液压试验，试验压力为设计压力的 1.5 倍，'
            '试验温度 30℃，保压 10 min 无泄漏无变形。')
    facts, output = _hydro(text, [{'designPressureMPa': 1, 'designTemperatureC': 20}])
    assert facts['temperatureCorrectionApplies'] is False
    assert output['result'] == 'passed'


def test_documented_reduction_exception_blocks_a_nonconformance_it_cannot_verify():
    """8.6.1.3 d)：准许按屈服强度或组成件额定值折减。写明折减时不足 1.5 倍不能直接判不符合。"""
    text = ('依据 GB/T 20801.1-2025，液压试验，试验压力为设计压力的 1.2 倍，试验温度 20℃，'
            '按 8.6.1.3 d) 降低试验压力至不超过组成件额定值，保压 10 min 无泄漏无变形。')
    facts, output = _hydro(text, [{'designPressureMPa': 1, 'designTemperatureC': 20}])
    assert facts['ratioReductionExceptionDocumented'] is True
    assert facts.get('testPressureMeetsRatio') is None
    assert facts.get('ratioUndecidedReason') == 'hydro_reduction_exception_unresolved'
    assert output['result'] == 'evidence_insufficient'


def test_without_the_exception_a_low_ratio_is_still_a_nonconformance():
    text = ('依据 GB/T 20801.1-2025，液压试验，试验压力为设计压力的 1.2 倍，试验温度 20℃，'
            '保压 10 min 无泄漏无变形。')
    facts, output = _hydro(text, [{'designPressureMPa': 1, 'designTemperatureC': 20}])
    assert facts.get('ratioReductionExceptionDocumented') is False
    assert facts['testPressureMeetsRatio'] is False
    assert output['result'] == 'failed'
