"""Exercise the real frozen rules after document facts and tool argument assembly."""
from __future__ import annotations

from copy import deepcopy

import pytest

from libs.business_pack import load_business_pack
from libs.review_orchestrator.design_facts import (
    design_special_requirements,
    frozen_special_requirement_rules,
)
from libs.review_tools.business_tools import evaluate_design_special_requirements
from libs.review_tools.executor import build_tool_arguments


def review_ndt(text, pipeline):
    binding = next(item for item in load_business_pack('engineering_inspection_v1')['atomicCheckToolBindings']
                   if item['atomicCheckId'] == 'AC-R09-01')
    facts = {'designSpecialRequirements': design_special_requirements(text, [pipeline]),
             'fixedClauses': {'designSpecialRequirementRules': frozen_special_requirement_rules()}}
    arguments = build_tool_arguments('evaluate_design_special_requirements', binding, facts=facts,
                                    explicit={'domains': ['ndt']}, document_version_ids=[],
                                    evidence_facts=[], evidence_refs=[])
    return evaluate_design_special_requirements(arguments)


@pytest.mark.parametrize(('ratio', 'level', 'expected'), [(100, 'Ⅲ', 'failed'), (100, 'Ⅱ', 'passed'), (20, 'Ⅲ', 'passed')])
def test_frozen_rules_consume_acceptance_comparison(ratio, level, expected):
    pipeline = {'pipelineId': 'P1', 'pipelineGrade': 'GC2', 'mediumToxicity': '无毒', 'leakHazard': '否'}
    output = review_ndt(f'GB/T 20801.1-2025 射线检测，检测比例 {ratio}%，验收等级 {level}级', pipeline)
    assert output['result'] == expected
    if expected == 'failed':
        assert 'acceptance_level_meets_requirement' in output['domainResults'][0]['violations']


def test_incomplete_gc2_hazard_is_evidence_insufficient_in_real_rule_path():
    pipeline = {'pipelineId': 'P1', 'pipelineGrade': 'GC2', 'mediumToxicity': '无毒'}
    before = deepcopy(pipeline)
    output = review_ndt('GB/T 20801.1-2025 射线检测，检测比例 5%，验收等级 Ⅲ级', pipeline)
    assert output['result'] == 'evidence_insufficient'
    assert 'coverage_meets_grade_requirement' in output['domainResults'][0]['unresolvedRules']
    assert pipeline == before


def test_confirmed_failure_is_not_hidden_by_unknown_hazard():
    output = review_ndt('GB/T 20801.1-2025 射线检测，检测比例 100%，验收等级 Ⅲ级',
                       {'pipelineId': 'P1', 'pipelineGrade': 'GC2'})
    assert output['result'] == 'failed'
