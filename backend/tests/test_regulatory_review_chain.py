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


def test_r14_frozen_product_rules_reach_formal_arguments():
    from libs.review_orchestrator.r14_facts import build_r14_business_facts
    from libs.review_tools.r14_tools import resolve_r14_required_inspection_items

    facts = build_r14_business_facts({}, {})
    facts['r14']['designItems'] = [{'componentType': '钢管', 'standardRef': 'GB/T 8163-2018', 'materialGrade': '20'}]
    binding = next(item for item in load_business_pack('engineering_inspection_v1')['atomicCheckToolBindings'] if item['atomicCheckId'] == 'AC-R14-02')
    args = build_tool_arguments('resolve_r14_required_inspection_items', binding, facts=facts, explicit={}, document_version_ids=[], evidence_facts=[], evidence_refs=[])
    assert 'GB/T 8163-2018' in args['productInspectionRules']
    output = resolve_r14_required_inspection_items(args)
    assert all(row.get('requirementSource') != 'product_standard_rule_missing' for row in output['inspectionRequirementMatrix'])


@pytest.mark.parametrize(('carbon', 'expected'), [(0.2, 'passed'), (0.9, 'failed'), (None, 'evidence_insufficient')])
def test_r16_composition_reaches_numeric_judgment(carbon, expected):
    from libs.review_orchestrator.material_facts import _enrich_material_design_item
    from libs.review_tools.r16_tools import evaluate_r16_quality_certificate_results

    item = _enrich_material_design_item({'standardRef': 'GB/T 8163-2018', 'materialGrade': '20', 'batchNo': 'B1'})
    measurements = {limit['itemCode']: limit.get('minimum', limit.get('maximum')) for limit in item['acceptanceLimits']}
    measurements['chemicalComposition.C'] = carbon
    output = evaluate_r16_quality_certificate_results({'designItems': [item], 'qualityCertificates': [{'batchNo': 'B1', 'testResults': measurements}]})
    assert output['result'] == expected
    assert output['numericResultMatrix'][0]['limitSource']['standard'] == 'GB/T 8163-2018'


def test_r16_unresolved_quality_or_thickness_cannot_pass_partial_limits():
    from libs.review_orchestrator.material_facts import _enrich_material_design_item
    from libs.review_tools.r16_tools import evaluate_r16_quality_certificate_results

    item = _enrich_material_design_item({'standardRef': 'GB/T 8163-2018', 'materialGrade': 'Q345', 'batchNo': 'B1'})
    measurements = {limit['itemCode']: limit.get('minimum', limit.get('maximum')) for limit in item['acceptanceLimits']}
    output = evaluate_r16_quality_certificate_results({'designItems': [item], 'qualityCertificates': [{'batchNo': 'B1', 'testResults': measurements}]})
    assert output['result'] == 'evidence_insufficient'
    assert 'quality_level_missing_or_unknown' in output['numericResultMatrix'][0]['unresolvedRequirements']


def test_grade_suffix_selects_quality_level_and_conflict_is_unresolved():
    from libs.regulatory_tables import pipe_material_limits

    assert pipe_material_limits('GB/T 8163-2018', 'Q345B')['level'] == 'B'
    assert pipe_material_limits('GB/T 8163-2018', 'Q345B', 'E') is None


@pytest.mark.parametrize(('strength', 'expected'), [(500, 'passed'), (450, 'failed'), (None, 'evidence_insufficient')])
def test_r26_designation_profile_is_used_by_formal_binding(strength, expected):
    from libs.review_orchestrator.r24_r34_facts import _consumable_profiles_by_designation
    from libs.review_tools.r24_r34_tools import evaluate_welding_consumable

    profiles = _consumable_profiles_by_designation()
    profile = profiles['gbt51172012e5015']
    certificate = {'standardRef': 'GB/T 5117-2012', 'materialGrade': 'E5015', 'batchNo': 'B1', 'originalSeen': True,
                   'chemicalComposition': {name: limits.get('min', limits.get('max')) for name, limits in profile['chemicalComposition'].items()},
                   'mechanicalProperties': {name: limits.get('min', limits.get('max')) for name, limits in profile['mechanicalProperties'].items()}}
    certificate['mechanicalProperties']['tensileStrength'] = strength
    facts = {'r26': {'qualityCertificates': [certificate], 'designRequirements': [{'materialGrade': 'E5015', 'standardRef': 'GB/T 5117-2012'}],
                     'physicalItems': [{'batchNo': 'B1'}], 'productStandardProfiles': profiles}}
    binding = next(item for item in load_business_pack('engineering_inspection_v1')['atomicCheckToolBindings'] if item['sourceRuleId'] == 'R26')
    args = build_tool_arguments('evaluate_welding_consumable', binding, facts=facts, explicit={}, document_version_ids=[], evidence_facts=[], evidence_refs=[])
    output = evaluate_welding_consumable(args)
    assert output['result'] == expected
    assert output['facts']['consumableCertificateMatrix'][0]['limitSource']['designation'] == 'E5015'
