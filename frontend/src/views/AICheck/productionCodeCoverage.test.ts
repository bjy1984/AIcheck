/**
 * 生产实测代号守门。
 *
 * 2026-09-13 线上审计：把三个工程 207 个节点包（P-2026-ECD202 / P-2026-GDLNG-002 /
 * P-TEST-OCR-002）里界面会直接显示的代号全抽出来，逐个过翻译函数。当时 59 个检查码、
 * 5 个枚举值、3 个资料类型翻不出来——`uploaded_pipeline_data_sheet`、
 * `required_ndtpersonnel_roster`、`r46_cathodic_scope_missing` 这些是后端 f-string
 * 拼出来的，`rawCodeCoverage` 那条从源码抽字面量的守门测试**看不见**它们。
 *
 * 所以这里冻结当天的生产取值：源码扫描管新增的字面量，这份清单管拼出来的族。
 * 重跑抽取：scratchpad/online_audit.ts（读节点包 JSON，输出仍是机器码的项）。
 */
import assert from 'node:assert/strict'

import {
  friendlyCheckCode,
  friendlyCheckReason,
  friendlyEnumValue,
  friendlyMaterialType,
  friendlyRuleCode
} from './components/auditLabels'

/** 中文才算翻出来了——半中半英（「缺少cathodic_scope」）按没翻算。 */
const translated = (text: string) =>
  /[\u4e00-\u9fa5]/.test(text) && !/[a-z]{3,}_[a-z]{3,}/.test(text)

const expectAll = (label: string, codes: string[], render: (code: string) => string) => {
  const raw = codes.filter((code) => !translated(render(code)))
  assert.deepEqual(
    raw,
    [],
    label + ' 还有生码没翻：' + raw.map((code) => code + ' → ' + render(code)).join('、')
  )
}

/** 逐条检查码（带证件号前缀的已剥前缀）。 */
const PRODUCTION_CHECKS = [
  'all_codes_decoded',
  'all_values_equal',
  'certificate_10_form_and_seals',
  'certificate_11_form_and_seals',
  'certificate_12_form_and_seals',
  'certificate_13_form_and_seals',
  'certificate_14_form_and_seals',
  'certificate_1_form_and_seals',
  'certificate_2_form_and_seals',
  'certificate_3_form_and_seals',
  'certificate_4_form_and_seals',
  'certificate_5_form_and_seals',
  'certificate_6_form_and_seals',
  'certificate_7_form_and_seals',
  'certificate_8_form_and_seals',
  'certificate_9_form_and_seals',
  'corrosion_protection_method_specified',
  'corrosion_requirements_acceptancecriteria',
  'corrosion_requirements_protectionmethod',
  'corrosion_specified',
  'corrosion_standard_ref_1',
  'grade_gc2',
  'holder_matches_project',
  'holder_matches_registry',
  'leaktest_method_specified',
  'leaktest_requirements_acceptancecriteria',
  'leaktest_requirements_method',
  'leaktest_requirements_testpressure',
  'leaktest_specified',
  'leaktest_standard_ref_1',
  'ndt_acceptance_level_specified',
  'ndt_coverage_specified',
  'ndt_method_specified',
  'ndt_requirements_acceptancecriteria',
  'ndt_requirements_coverage',
  'ndt_requirements_method',
  'ndt_specified',
  'ndt_standard_ref_1',
  'ndt_standard_ref_2',
  'ndt_standard_ref_3',
  'not_expired_on_reference_date',
  'parseable_design_specification',
  'parseable_drawing_catalog',
  'parseable_pipeline_data_sheet',
  'parseable_pipeline_layout_drawing',
  'parseable_pipeline_material_list',
  'parseable_straight_pipe_strength_calculation',
  'pressuretest_method_specified',
  'pressuretest_requirements_acceptancecriteria',
  'pressuretest_requirements_method',
  'pressuretest_requirements_testpressure',
  'pressuretest_specified',
  'pressuretest_standard_ref_1',
  'r36_applicability_missing',
  'r43_certificate_scope_missing',
  'r46_cathodic_scope_missing',
  'r47_grounding_scope_missing',
  'r50_sleeve_scope_missing',
  'r54_compensator_scope_missing',
  'r55_support_scope_missing',
  'r56_documents_scope_missing',
  'r56_installation_scope_missing',
  'r63_stress_scope_missing',
  'r68_blowing_scope_missing',
  'required_actualndt_workitems',
  'required_certificatefacts_certificates',
  'required_design_requiresinsulatedsupport',
  'required_insulatedsupport_inspectionrecords',
  'required_insulatedsupport_results',
  'required_ndtpersonnel_qualificationcodes',
  'required_ndtpersonnel_registration',
  'required_ndtpersonnel_roster',
  'scope_covers_required',
  'uploaded_design_specification',
  'uploaded_drawing_catalog',
  'uploaded_pipeline_data_sheet',
  'uploaded_pipeline_layout_drawing',
  'uploaded_pipeline_material_list',
  'uploaded_straight_pipe_strength_calculation'
]

/** 检查项的期望值/实际值。 */
const PRODUCTION_ENUM_VALUES = [
  'design_specification',
  'drawing_catalog',
  'evidence_insufficient',
  'original_with_manufacturer_quality_seal_or_copy_with_dealer_and_handler_seals',
  'pipeline_data_sheet',
  'pipeline_layout_drawing',
  'pipeline_material_list',
  'straight_pipe_strength_calculation'
]

/** 原子项的不通过原因。 */
const PRODUCTION_REASONS = [
  'approval_item_codes_missing',
  'calculation_documents_or_types_missing',
  'condition_missing',
  'consumable_certificate_or_design_requirement_missing',
  'design_documents_missing',
  'drawing_review_witness_document_missing',
  'ndt_agencies_missing',
  'periodStart_and_periodEnd_missing',
  'provider_confidence_unavailable',
  'pwht_weld_items_missing',
  'required_pipeline_grades_missing',
  'required_signature_roles_missing',
  'sampling_parameters_missing',
  'target_design_documents_missing',
  'validUntil_and_periodStart_and_periodEnd_missing',
  'welding_records_missing',
  'welding_work_records_missing',
  'wps_pqr_or_actual_work_missing'
]

/** 原子项所属规则键。 */
const PRODUCTION_RULE_CODES = [
  'engineering-inspection-r01',
  'engineering-inspection-r02',
  'engineering-inspection-r03',
  'engineering-inspection-r04',
  'engineering-inspection-r05',
  'engineering-inspection-r06',
  'engineering-inspection-r07',
  'engineering-inspection-r08',
  'engineering-inspection-r09',
  'engineering-inspection-r16',
  'engineering-inspection-r21',
  'engineering-inspection-r23',
  'engineering-inspection-r25',
  'engineering-inspection-r26',
  'engineering-inspection-r29',
  'engineering-inspection-r32',
  'engineering-inspection-r36',
  'engineering-inspection-r38',
  'engineering-inspection-r43',
  'engineering-inspection-r46',
  'engineering-inspection-r47',
  'engineering-inspection-r50',
  'engineering-inspection-r51',
  'engineering-inspection-r54',
  'engineering-inspection-r55',
  'engineering-inspection-r56',
  'engineering-inspection-r59',
  'engineering-inspection-r63',
  'engineering-inspection-r68',
  'welder-qualification'
]

/** 节点资料要求的资料类型码。 */
const PRODUCTION_MATERIAL_TYPES = [
  'acceptance_witness_record',
  'anticorrosion_insulation_material_certificate',
  'anticorrosion_insulation_record',
  'calculation_report',
  'cathodic_protection_record',
  'construction_license',
  'construction_organization_design',
  'construction_schedule',
  'design_change_document',
  'design_document',
  'design_license',
  'drawing_material_list',
  'drawing_review_record',
  'enterprise_material_standard',
  'external_query_screenshot',
  'factory_inspection_report',
  'field_photo',
  'grounding_test_record',
  'hardness_report',
  'heat_treatment_procedure',
  'heat_treatment_record',
  'installation_record',
  'instrument_calibration_certificate',
  'leakage_test_report',
  'manufacturing_license',
  'manufacturing_supervision_certificate',
  'material_mark_transfer_record',
  'material_ndt_report',
  'material_retest_report',
  'material_substitution_approval',
  'ndt_org_certificate',
  'ndt_person_certificate',
  'ndt_plan',
  'ndt_procedure',
  'ndt_report',
  'new_material_data',
  'overseas_material_certificate',
  'pipe_fit_up_record',
  'pipeline_summary',
  'platform_verification',
  'pmi_report',
  'pqr',
  'pressure_test_plan',
  'pressure_test_report',
  'purge_cleaning_record',
  'quality_certificate',
  'quality_system_document',
  'radiographic_film',
  'safety_accessory_record',
  'sampling_witness_record',
  'technical_review_approval',
  'temperature_point_layout',
  'type_test_report',
  'valve_construction_record',
  'valve_test_report',
  'weld_appearance_record',
  'weld_repair_record',
  'welder_certificate',
  'welder_roster',
  'welding_material_certificate',
  'welding_material_management_record',
  'welding_process_card',
  'welding_record',
  'wps',
  'wps_pqr'
]

expectAll('检查码', PRODUCTION_CHECKS, friendlyCheckCode)
expectAll('期望/实际值', PRODUCTION_ENUM_VALUES, friendlyEnumValue)
expectAll('原因码', PRODUCTION_REASONS, friendlyCheckReason)
expectAll('规则键', PRODUCTION_RULE_CODES, (code) => friendlyRuleCode(code))
expectAll('资料类型', PRODUCTION_MATERIAL_TYPES, friendlyMaterialType)

console.log(
  '生产代号守门通过：检查码 ' +
    PRODUCTION_CHECKS.length +
    '、枚举值 ' +
    PRODUCTION_ENUM_VALUES.length +
    '、原因码 ' +
    PRODUCTION_REASONS.length +
    '、规则键 ' +
    PRODUCTION_RULE_CODES.length +
    '、资料类型 ' +
    PRODUCTION_MATERIAL_TYPES.length
)
