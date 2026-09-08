from __future__ import annotations

import pytest

from libs.regulatory_tables import pipe_material_limits, table
from libs.review_orchestrator.material_facts import _enrich_material_design_item
from libs.review_tools.r16_tools import evaluate_r16_quality_certificate_results


def test_all_31_grades_have_source_traced_composition_and_alias_lookup():
    standard = next(row for row in table('pipeMaterialLimits')['standards'] if row['standard'] == 'GB/T 13296-2023')
    assert len(standard['grades']) == 31
    for grade in standard['grades']:
        result = pipe_material_limits(standard['standard'], grade['alias'])
        assert result['composition']['C'] and result['composition']['S']
        assert result['compositionSource']['pdfPages'] == [10, 11]
        assert result['sourcePdfSha256'] == 'd156ea818f31dec56bc73459b69db474599435f6c5e40a8536aaa529e9924564'
    assert pipe_material_limits(standard['standard'], 'S30408')['composition']['S'] == '<=.015'
    assert pipe_material_limits(standard['standard'], 'S31252')['composition']['Ni'] == '17.5-18.5'


@pytest.mark.parametrize(('titanium', 'nitrogen', 'expected'), [(0.5, 0.02, 'passed'), (0.1, 0.02, 'failed'), (0.8, 0.02, 'failed'), (0.5, None, 'evidence_insufficient')])
def test_titanium_bound_depends_on_carbon_and_nitrogen(titanium, nitrogen, expected):
    item = _enrich_material_design_item({'standardRef': 'GB/T 13296-2023', 'materialGrade': 'S32168', 'batchNo': 'B1'})
    measurements = {limit['itemCode']: limit.get('minimum', limit.get('maximum')) for limit in item['acceptanceLimits']}
    measurements.update({'chemicalComposition.C': .08, 'chemicalComposition.N': nitrogen, 'chemicalComposition.Ti': titanium})
    result = evaluate_r16_quality_certificate_results({'designItems': [item], 'qualityCertificates': [{'batchNo': 'B1', 'testResults': measurements}]})
    assert result['result'] == expected


@pytest.mark.parametrize(('nickel', 'copper', 'expected'), [(.3, .2, 'passed'), (.5, .2, 'failed'), (.3, None, 'evidence_insufficient')])
def test_individually_allowed_nickel_and_copper_must_also_meet_combined_limit(nickel, copper, expected):
    item = _enrich_material_design_item({'standardRef': 'GB/T 13296-2023', 'materialGrade': 'S12791', 'batchNo': 'B1'})
    values = {limit['itemCode']: limit.get('minimum', limit.get('maximum')) for limit in item['acceptanceLimits']}
    values.update({'chemicalComposition.Ni': nickel, 'chemicalComposition.Cu': copper})
    result = evaluate_r16_quality_certificate_results({'designItems': [item], 'qualityCertificates': [{'batchNo': 'B1', 'testResults': values}]})
    assert result['result'] == expected
    assert not any(limit['itemCode'].startswith('hardness') for limit in item['acceptanceLimits'])


def test_hardness_is_selected_only_for_explicit_contract_requirement():
    base = {'执行标准': 'GB/T 13296-2023', '材料牌号': 'S30408', '壁厚': 2}
    ordinary = _enrich_material_design_item({'sourceRow': base})
    assert not any(limit['itemCode'].startswith('hardness') for limit in ordinary['acceptanceLimits'])
    selected = _enrich_material_design_item({'sourceRow': {**base, '布氏硬度合同要求': True, '洛氏硬度合同要求': True}})
    limits = {item['itemCode']: item for item in selected['acceptanceLimits']}
    assert limits['hardnessHBW']['maximum'] == 192
    assert limits['hardnessRockwell']['maximum'] == 90
    assert 'hardnessHV' not in limits


@pytest.mark.parametrize(('niobium', 'expected'), [(0.8, 'passed'), (0.5, 'failed'), (None, 'evidence_insufficient')])
def test_niobium_minimum_tracks_measured_carbon(niobium, expected):
    item = _enrich_material_design_item({'standardRef': 'GB/T 13296-2023', 'materialGrade': 'S34778', 'batchNo': 'B1'})
    values = {limit['itemCode']: limit.get('minimum', limit.get('maximum')) for limit in item['acceptanceLimits']}
    values.update({'chemicalComposition.C': .08, 'chemicalComposition.Nb': niobium})
    result = evaluate_r16_quality_certificate_results({'designItems': [item], 'qualityCertificates': [{'batchNo': 'B1', 'testResults': values}]})
    assert result['result'] == expected
