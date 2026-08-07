from __future__ import annotations

from decimal import Decimal
from typing import Any, Callable

from libs.review_orchestrator.deterministic_tools import (
    check,
    decimal,
    normalize_value,
    parse_date,
    result,
)
from libs.review_tools.r13_tools import (
    classify_r13_component_requirements,
    evaluate_r13_supervision_certificate_completeness,
    evaluate_r13_type_test_coverage,
)
from libs.review_tools.r14_tools import (
    classify_r14_component_applicability,
    evaluate_r14_component_design_match,
    evaluate_r14_pressure_compatibility,
    evaluate_r14_special_report_coverage,
    resolve_r14_required_inspection_items,
)
from libs.review_tools.r15_tools import (
    classify_r15_foreign_manufacturing_applicability,
    classify_r15_regulatory_requirements,
    evaluate_r15_manufacturing_inspection_route,
    evaluate_r15_manufacturing_license_coverage,
    evaluate_r15_type_test_coverage,
)
from libs.review_tools.r16_tools import (
    evaluate_r16_batch_traceability,
    evaluate_r16_quality_certificate_batch_coverage,
    evaluate_r16_quality_certificate_content,
    evaluate_r16_quality_certificate_design_match,
    evaluate_r16_quality_certificate_form_and_seals,
    evaluate_r16_quality_certificate_results,
    resolve_r16_product_standard_profile,
)
from libs.review_tools.r17_tools import (
    evaluate_r17_acceptance_procedure,
    evaluate_r17_arrival_acceptance_batch_coverage,
    evaluate_r17_nonconformance_control,
    evaluate_r17_sampling_witness_chain,
    resolve_r17_sampling_retest_requirement,
)
from libs.review_tools.r18_tools import (
    classify_r18_material_test_applicability,
    evaluate_r18_material_ndt_report_completeness,
    evaluate_r18_material_report_approval_procedure,
    evaluate_r18_material_retest_report_completeness,
    evaluate_r18_material_test_results_and_traceability,
    resolve_r18_material_test_requirement_profile,
)
from libs.review_tools.r19_tools import validate_r19_semantic_judgment
from libs.review_tools.r20_r23_tools import (
    classify_r20_new_material_applicability,
    evaluate_r20_new_material_procedure,
    evaluate_r21_mark_transfer,
    evaluate_r22_material_substitution,
    evaluate_r23_valve_sampling,
    evaluate_r23_valve_test_records,
    resolve_r23_valve_test_basis,
)
from libs.review_tools.r24_r34_tools import (
    check_wps_pqr_coverage as check_r25_wps_pqr_coverage,
    evaluate_heat_treatment as evaluate_r32_r34_heat_treatment,
    evaluate_heat_treatment_instruments as evaluate_r33_heat_treatment_instruments,
    evaluate_pipe_fit_up as evaluate_r28_pipe_fit_up,
    evaluate_weld_appearance as evaluate_r30_weld_appearance,
    evaluate_weld_repair as evaluate_r31_weld_repair,
    evaluate_welding_consumable as evaluate_r26_welding_consumable,
    evaluate_welding_consumable_control as evaluate_r27_welding_consumable_control,
    evaluate_welding_process as evaluate_r29_welding_process,
    resolve_pwht_applicability,
)


COMMON_TOOL_NAMES = (
    "check_required",
    "check_scope_coverage",
    "check_cross_document_match",
    "check_signature_completeness",
    "check_numeric_range",
    "check_conditional_requirement",
    "check_sampling_requirement",
    "check_document_set_completeness",
    "check_standard_version_active",
    "check_traceability",
)

DOMAIN_TOOL_NAMES = (
    "check_license_registry_match",
    "classify_r13_component_requirements",
    "classify_r14_component_applicability",
    "classify_r15_foreign_manufacturing_applicability",
    "classify_r15_regulatory_requirements",
    "classify_r18_material_test_applicability",
    "check_ndt_personnel_coverage",
    "check_installation_license_scope",
    "check_wps_pqr_coverage",
    "decode_ndt_approval_item_codes",
    "evaluate_calculation_document_consistency",
    "evaluate_alternative_standard",
    "evaluate_blowing_cleaning",
    "evaluate_component_manufacturer_scope",
    "evaluate_construction_plan",
    "evaluate_corrosion_protection",
    "evaluate_design_approval_level",
    "evaluate_design_document_approval",
    "evaluate_design_change_approval",
    "evaluate_design_special_requirements",
    "evaluate_heat_treatment",
    "evaluate_heat_treatment_instruments",
    "evaluate_installation_license_scope",
    "evaluate_leak_test",
    "evaluate_material_component",
    "evaluate_ndt_nonconformance",
    "evaluate_ndt_organization_scope",
    "evaluate_ndt_agencies",
    "evaluate_ndt_process",
    "evaluate_ndt_quality_system",
    "evaluate_pipe_fit_up",
    "evaluate_pipeline_installation",
    "evaluate_pressure_test",
    "evaluate_r13_supervision_certificate_completeness",
    "evaluate_r13_type_test_coverage",
    "evaluate_r14_component_design_match",
    "evaluate_r14_pressure_compatibility",
    "evaluate_r14_special_report_coverage",
    "resolve_r14_required_inspection_items",
    "evaluate_r15_manufacturing_inspection_route",
    "evaluate_r15_manufacturing_license_coverage",
    "evaluate_r15_type_test_coverage",
    "evaluate_r16_batch_traceability",
    "evaluate_r16_quality_certificate_batch_coverage",
    "evaluate_r16_quality_certificate_content",
    "evaluate_r16_quality_certificate_design_match",
    "evaluate_r16_quality_certificate_form_and_seals",
    "evaluate_r16_quality_certificate_results",
    "resolve_r16_product_standard_profile",
    "evaluate_r17_acceptance_procedure",
    "evaluate_r17_arrival_acceptance_batch_coverage",
    "evaluate_r17_nonconformance_control",
    "evaluate_r17_sampling_witness_chain",
    "resolve_r17_sampling_retest_requirement",
    "evaluate_r18_material_ndt_report_completeness",
    "evaluate_r18_material_report_approval_procedure",
    "evaluate_r18_material_retest_report_completeness",
    "evaluate_r18_material_test_results_and_traceability",
    "resolve_r18_material_test_requirement_profile",
    "validate_r19_semantic_judgment",
    "classify_r20_new_material_applicability",
    "evaluate_r20_new_material_procedure",
    "evaluate_r21_mark_transfer",
    "evaluate_r22_material_substitution",
    "resolve_r23_valve_test_basis",
    "resolve_pwht_applicability",
    "evaluate_r23_valve_sampling",
    "evaluate_r23_valve_test_records",
    "evaluate_rt_film",
    "evaluate_safety_accessory",
    "evaluate_stress_analysis",
    "evaluate_valve_test",
    "evaluate_weld_appearance",
    "evaluate_weld_repair",
    "evaluate_welding_consumable",
    "evaluate_welding_consumable_control",
    "evaluate_welding_process",
    "verify_design_license_seals",
)


BUSINESS_TOOL_CAPABILITIES = {
    "check_license_registry_match": (
        "核对制造许可证 OCR 候选与人工官网核验记录；官网未查到、信息不一致或证照非有效状态时判定不符合，未完成核验时返回证据不足。"
    ),
    "check_installation_license_scope": (
        "按照GC1、GC2、GCD和A级锅炉安装资质的固定覆盖关系，判断安装许可证是否覆盖项目管道等级。"
    ),
    "classify_r20_new_material_applicability": (
        "按TSG 31-2025第2.1.3条区分非新材料、未列入任何专用材料标准的新材料，以及已列入其他专用材料标准的新材料；分类事实不足时停止自动判定。"
    ),
    "evaluate_r20_new_material_procedure": (
        "逐项核验新材料元件或安全附件的型式试验覆盖；对未列入任何专用材料标准的材料核验技术评审及批准手续，对已列入其他专用材料标准的材料核验必要性能数据。"
    ),
    "evaluate_r21_mark_transfer": (
        "核验材料标志移植记录、原标志至移植标志的追溯链、特殊材料种类抽查覆盖，以及硬印和色标方法限制；未发生标志移植时返回不适用。"
    ),
    "evaluate_r22_material_substitution": (
        "仅对实际实施的材料代用核验原设计单位书面批准、批准时间、代用范围及实际使用一致性；仅有未实施建议时返回不适用。"
    ),
    "resolve_r23_valve_test_basis": (
        "按设计文件、供货合同、缺省GB/T 13927-2022的优先级确定阀门试验依据，并识别设计与合同冲突或不支持的标准。"
    ),
    "evaluate_r23_valve_sampling": (
        "按GB/T 20801.1-2025第7.2.4条计算GC1、GC2、GC3阀门检验数量，核验工厂逐台见证豁免条件及抽样不合格后的整批处置。"
    ),
    "evaluate_r23_valve_test_records": (
        "逐台核验阀门施工记录和耐压试验报告的依据标准、壳体及密封试验介质、压力、保压时间、程序、泄漏与结论；规范参数未冻结时返回证据不足。"
    ),
    "check_wps_pqr_coverage": (
        "核验WPS/PQR审批与对应关系、WPS参数是否位于PQR评定范围内，并逐管线核验实际方法、材料和壁厚及施焊参数覆盖。"
    ),
    "evaluate_welding_consumable": (
        "按设计牌号规格、产品标准限值、MTC化学及力学实测数据、实物批号和超库存期复验记录审核焊材；缺少已冻结产品标准限值时返回证据不足。"
    ),
    "evaluate_welding_consumable_control": (
        "联查焊材验收、保管温湿度、烘干保温、领用、使用与回收记录，识别混用、过期及批号追溯中断。"
    ),
    "evaluate_pipe_fit_up": (
        "按材料类别和壁厚计算错边量限值，核验组对间隙、坡口角度及禁止强行组对要求。"
    ),
    "evaluate_welding_process": (
        "核验施焊记录参数与焊缝标识追溯，并要求R24焊工资格覆盖和R25 WPS/PQR覆盖结果同时成立。"
    ),
    "evaluate_weld_appearance": (
        "按GB/T 20801.1-2025表43的检验等级、接头类型和壁厚核验裂纹、未熔合、气孔夹渣、咬边和余高；宽度仅按设计/WPS明确限值判断。"
    ),
    "evaluate_weld_repair": (
        "核验返修申请、原因与返修工艺、同一部位超过2次的专项措施及技术负责人批准、返修后同方法复检和必要的重新热处理。"
    ),
    "resolve_pwht_applicability": (
        "按材料组、控制厚度、强度和接头例外统一解析焊后热处理适用性，为R32至R34生成稳定适用性键和表36规则档案。"
    ),
    "evaluate_heat_treatment": (
        "分别审核R32热处理工艺卡和R34曲线/报告/硬度：复用统一适用性规则，核验审批、评定依据、温度速率及材料条件化硬度限值。"
    ),
    "evaluate_heat_treatment_instruments": (
        "核验热电偶、温控仪和自动记录仪的校准证书有效性及测温点布置图。"
    ),
    "classify_r13_component_requirements": (
        "依据TSG D7006-2020第1.2.1条、附件A1.2和市场监管总局2021年第41号公告附件1注三、注四，"
        "逐项判定设计材料表中的压力管道元件是否触发制造监检、型式试验及监检粒度；未知类别返回证据不足。"
    ),
    "decode_ndt_approval_item_codes": (
        "按照TSG Z7002-2022附件A表A-1解码检测机构核准项目代码；未知代码返回证据不足。"
    ),
    "evaluate_ndt_agencies": (
        "按检测机构分别核验核准证与检测方案机构名称、核准项目代码的方法覆盖和施工计划工期有效期。"
    ),
    "evaluate_calculation_document_consistency": (
        "逐份核验强度计算书和管道应力计算书本体、覆盖管线及其与设计文件的结构化参数比较结果。"
    ),
    "evaluate_design_document_approval": (
        "逐份核验主要设计文件本体和签字角色，并根据文件覆盖的管道级别、设计压力和设计温度，"
        "确定执行三级或四级批准程序。"
    ),
    "evaluate_design_change_approval": (
        "逐份核验设计变更书面批准文件的原设计单位批准、文件本体及按受影响设计文件和管道条件确定的三级或四级签字。"
    ),
    "evaluate_design_special_requirements": (
        "核验设计说明是否对无损检测、防腐、耐压试验和泄漏试验规定了具体要求，并按冻结标准规则逐领域判断符合性。"
    ),
    "evaluate_r13_supervision_certificate_completeness": (
        "对需制造监检的埋弧焊钢管、聚乙烯管和指定元件组合装置，按批次或台件核对制造监督检验证书是否齐全、合格且可追溯。"
    ),
    "evaluate_r13_type_test_coverage": (
        "逐项核对型式试验证书或报告的产品类别、制造单位、材料、结构、制造工艺及规格/压力范围是否覆盖设计材料表中的实际元件。"
    ),
    "classify_r14_component_applicability": (
        "逐项确认管道组成件是否不需要制造许可、制造监检和型式试验；任一要求无法分类时返回证据不足，并将需许可或监检/型式试验的元件分别路由至R12或R13。"
    ),
    "evaluate_r14_component_design_match": (
        "按元件类型、规格、批号和管线号关联出厂检验报告，逐项核对元件等级、材质及报告结论是否符合设计材料表。"
    ),
    "resolve_r14_required_inspection_items": (
        "根据设计文件明确要求和已冻结的具体产品标准规则，逐项确定光谱、硬度、金相、无损检测和耐压试验等必检项目；规则未覆盖时禁止推断。"
    ),
    "evaluate_r14_special_report_coverage": (
        "按元件、规格和批号核对必需的光谱、硬度、金相、无损检测及耐压试验报告是否齐全、关联正确且结论合格。"
    ),
    "evaluate_r14_pressure_compatibility": (
        "按管线号关联材料表、管道特性表、出厂检验报告和专项报告，判断元件额定压力等级是否覆盖管线要求；不支持的Class换算返回证据不足。"
    ),
    "classify_r15_foreign_manufacturing_applicability": (
        "仅依据制造国家、制造地点或明确的境外制造结构化事实，逐项判定R15适用性；不得以境外材料牌号替代境外制造事实。"
    ),
    "classify_r15_regulatory_requirements": (
        "依据TSG 31-2025第1.10、2.2.1.5条和TSG D7006-2020附件D D2.4.1，逐项分类制造许可、型式试验和制造监检要求；无法分类时返回证据不足。"
    ),
    "evaluate_r15_manufacturing_license_coverage": (
        "对需要制造许可的境外制造元件逐项核对制造单位、官网人工核验状态和许可范围，确认相应制造许可覆盖工程实际产品。"
    ),
    "evaluate_r15_type_test_coverage": (
        "对有型式试验要求的境外制造元件逐项核对制造单位、产品类别、材料、结构、制造工艺及规格/压力范围。"
    ),
    "evaluate_r15_manufacturing_inspection_route": (
        "对需要制造监检的境外制造元件，按境外完成制造监检、到岸检验或随锅炉/压力容器整机检验三条路径核验证书或检验记录。"
    ),
    "resolve_r16_product_standard_profile": (
        "按设计文件中的产品执行标准，将元件路由到已冻结的GB/T产品标准规则；标准未建模时返回证据不足，禁止由模型猜测。"
    ),
    "evaluate_r16_quality_certificate_batch_coverage": (
        "按产品、规格、炉批号或产品编号逐项核验本工程到货元件是否具有唯一对应的产品质量证明文件。"
    ),
    "evaluate_r16_quality_certificate_form_and_seals": (
        "识别质量证明文件为原件或复印件；原件核验制造单位质量检验章，复印件核验经营单位公章和经办负责人章。"
    ),
    "evaluate_r16_quality_certificate_design_match": (
        "逐批核对质量证明文件中的制造单位、产品、规格、材质、执行标准和交货状态与设计材料表及订货要求。"
    ),
    "evaluate_r16_quality_certificate_content": (
        "依据已冻结的具体产品标准和设计特殊要求，核验质量证明文件必需字段、出厂检验项目及合格结论是否齐全。"
    ),
    "evaluate_r16_quality_certificate_results": (
        "仅使用结构化验收限值核验质量证明文件中的化学、力学及专项检验数值；限值未冻结时返回证据不足。"
    ),
    "evaluate_r16_batch_traceability": (
        "核验设计材料表、产品质量证明文件和实物标识的炉号、批号或产品编号形成同一追溯链。"
    ),
    "evaluate_r17_arrival_acceptance_batch_coverage": (
        "按产品、规格、炉批号或产品编号核验每批到货元件是否存在唯一对应的验收记录。"
    ),
    "evaluate_r17_acceptance_procedure": (
        "核验到货验收是否执行质量证明、身份标识、外观、尺寸和结论记录等质量体系步骤，并具有验收签字。"
    ),
    "resolve_r17_sampling_retest_requirement": (
        "根据设计明确要求或冻结的抽样规则逐批确定是否需要抽样复验；触发条件不明时返回证据不足。"
    ),
    "evaluate_r17_sampling_witness_chain": (
        "对需要抽样复验的批次核对取样见证记录、见证角色、样品编号和复验报告的连续证据链。"
    ),
    "evaluate_r17_nonconformance_control": (
        "对验收不合格批次核验隔离、处置和放行批准记录，防止未受控材料投入使用。"
    ),
    "classify_r18_material_test_applicability": (
        "逐批识别材料复验和材料本体无损检测是否适用；R18仅在规则或设计明确要求进行时进入报告审查。"
    ),
    "resolve_r18_material_test_requirement_profile": (
        "将适用批次绑定到具体产品标准、复验项目、材料无损检测方法和结构化验收限值，规则不完整时禁止判定符合。"
    ),
    "evaluate_r18_material_retest_report_completeness": (
        "对需要材料复验的批次核验复验报告是否存在，并覆盖规则要求的全部复验项目。"
    ),
    "evaluate_r18_material_ndt_report_completeness": (
        "对需要材料本体无损检测的批次核验专用检测报告是否存在，并覆盖要求的检测方法。"
    ),
    "evaluate_r18_material_report_approval_procedure": (
        "核验材料复验及材料无损检测报告的批准程序和试验、审核、批准等签字角色。"
    ),
    "evaluate_r18_material_test_results_and_traceability": (
        "核验复验/NDT报告结论、结构化数值限值以及材料批号—样品号—报告号追溯链。"
    ),
    "validate_r19_semantic_judgment": (
        "校验R19由LLM形成的逐原子项语义判断是否符合输出Schema，是否引用已登记的EvidenceRef和固定ClauseRef；"
        "本Tool只校验判断记录，不生成或改写业务结论。"
    ),
    "verify_design_license_seals": (
        "依据TSG 31-2025第3.1.2条，逐份核验重新出具的管道图纸目录和管道布置图上的压力管道设计许可印章。"
    ),
}


BUSINESS_TOOL_DESCRIPTORS: list[dict[str, Any]] = [
    {
        "name": name,
        "capability": BUSINESS_TOOL_CAPABILITIES.get(
            name,
            "执行结构化、确定性业务规则；事实或规则参数不足时禁止判定符合。",
        ),
        "inputSchema": (
            {
                "licenseCandidates": ["object"],
                "registryVerifications": ["object"],
                "ruleVersion": "string?",
            }
            if name == "check_license_registry_match"
            else {
                "designItems": ["object"],
                "ruleVersion": "string?",
            }
            if name in {
                "classify_r15_foreign_manufacturing_applicability",
                "classify_r15_regulatory_requirements",
            }
            else {
                "designItems": ["object"],
                "licenseCandidates": ["object"],
                "registryVerifications": ["object"],
                "requireRegistryVerification": "boolean?",
                "ruleVersion": "string?",
            }
            if name == "evaluate_r15_manufacturing_license_coverage"
            else {
                "designItems": ["object"],
                "typeTestReports": ["object"],
                "ruleVersion": "string?",
            }
            if name == "evaluate_r15_type_test_coverage"
            else {
                "designItems": ["object"],
                "supervisionCertificates": ["object"],
                "arrivalInspectionRecords": ["object"],
                "completeMachineInspectionRecords": ["object"],
                "ruleVersion": "string?",
            }
            if name == "evaluate_r15_manufacturing_inspection_route"
            else {
                "designItems": ["object"],
                "qualityCertificates": ["object"],
                "ruleVersion": "string?",
            }
            if name in {
                "resolve_r16_product_standard_profile",
                "evaluate_r16_quality_certificate_batch_coverage",
                "evaluate_r16_quality_certificate_design_match",
                "evaluate_r16_quality_certificate_content",
                "evaluate_r16_quality_certificate_results",
                "evaluate_r16_batch_traceability",
            }
            else {
                "qualityCertificates": ["object"],
                "ruleVersion": "string?",
            }
            if name == "evaluate_r16_quality_certificate_form_and_seals"
            else {
                "designItems": ["object"],
                "acceptanceRecords": ["object"],
                "witnessRecords": ["object"],
                "samplingRetestReports": ["object"],
                "samplingRules": "object?",
                "ruleVersion": "string?",
            }
            if name in {
                "evaluate_r17_arrival_acceptance_batch_coverage",
                "evaluate_r17_acceptance_procedure",
                "resolve_r17_sampling_retest_requirement",
                "evaluate_r17_sampling_witness_chain",
                "evaluate_r17_nonconformance_control",
            }
            else {
                "designItems": ["object"],
                "retestReports": ["object"],
                "materialNdtReports": ["object"],
                "ruleVersion": "string?",
            }
            if name in {
                "classify_r18_material_test_applicability",
                "resolve_r18_material_test_requirement_profile",
                "evaluate_r18_material_retest_report_completeness",
                "evaluate_r18_material_ndt_report_completeness",
                "evaluate_r18_material_report_approval_procedure",
                "evaluate_r18_material_test_results_and_traceability",
            }
            else {
                "atomicCheckId": "string",
                "judgment": "object",
                "knownEvidenceRefIds": ["string"],
                "evidenceIndex": "object?",
                "ruleVersion": "string?",
            }
            if name == "validate_r19_semantic_judgment"
            else {
                "designItems": ["object"],
                "typeTestReports": ["object"],
                "technicalReviewApprovals": ["object"],
                "materialDataDocuments": ["object"],
                "ruleVersion": "string?",
            }
            if name in {"classify_r20_new_material_applicability", "evaluate_r20_new_material_procedure"}
            else {
                "markTransferOccurred": "boolean?",
                "transferRecords": ["object"],
                "materialInventory": ["object"],
                "ruleVersion": "string?",
            }
            if name == "evaluate_r21_mark_transfer"
            else {
                "materialSubstitutionOccurred": "boolean?",
                "substitutionRecords": ["object"],
                "actualMaterialUsage": ["object"],
                "ruleVersion": "string?",
            }
            if name == "evaluate_r22_material_substitution"
            else {
                "designStandardRefs": ["string"],
                "contractStandardRefs": ["string"],
                "designAndContractBasisChecked": "boolean?",
                "testLots": ["object"],
                "constructionRecords": ["object"],
                "testRecords": ["object"],
                "standardRequirementProfiles": "object?",
                "ruleVersion": "string?",
            }
            if name in {"resolve_r23_valve_test_basis", "evaluate_r23_valve_sampling", "evaluate_r23_valve_test_records"}
            else {
                "designItems": ["object"],
                "ruleVersion": "string?",
            }
            if name == "classify_r13_component_requirements"
            else {
                "designItems": ["object"],
                "supervisionCertificates": ["object"],
                "ruleVersion": "string?",
            }
            if name == "evaluate_r13_supervision_certificate_completeness"
            else {
                "designItems": ["object"],
                "typeTestReports": ["object"],
                "ruleVersion": "string?",
            }
            if name == "evaluate_r13_type_test_coverage"
            else {
                "designItems": ["object"],
                "ruleVersion": "string?",
            }
            if name == "classify_r14_component_applicability"
            else {
                "designItems": ["object"],
                "factoryInspectionReports": ["object"],
                "ruleVersion": "string?",
            }
            if name == "evaluate_r14_component_design_match"
            else {
                "designItems": ["object"],
                "productInspectionRules": "object",
                "ruleVersion": "string?",
            }
            if name == "resolve_r14_required_inspection_items"
            else {
                "designItems": ["object"],
                "specialInspectionReports": ["object"],
                "productInspectionRules": "object",
                "ruleVersion": "string?",
            }
            if name == "evaluate_r14_special_report_coverage"
            else {
                "designItems": ["object"],
                "pipelineCharacteristics": ["object"],
                "factoryInspectionReports": ["object"],
                "specialInspectionReports": ["object"],
                "ruleVersion": "string?",
            }
            if name == "evaluate_r14_pressure_compatibility"
            else {
                "licenseCandidates": ["object"],
                "registryVerifications": ["object"],
                "componentItems": ["object"],
                "ruleVersion": "string?",
            }
            if name == "evaluate_component_manufacturer_scope"
            else
            {
                "approvalMode": "three_level|four_level_conditional",
                "documents": ["object"],
                "pipelines": ["object"],
                "targetDocumentTypes": ["string"],
                "requiredRoles": ["string"],
                "ruleVersion": "string?",
            }
            if name == "evaluate_design_document_approval"
            else {
                "hasDesignChanges": "boolean",
                "documents": ["object"],
                "pipelines": ["object"],
                "ruleVersion": "string?",
            }
            if name == "evaluate_design_change_approval"
            else {
                "requirements": "object",
                "standardRules": "object",
                "requiredPathsByDomain": "object",
                "domains": ["ndt|corrosion|pressureTest|leakTest"],
                "ruleVersion": "string?",
            }
            if name == "evaluate_design_special_requirements"
            else {
                "hasDesignChanges": "boolean",
                "documents": ["object"],
                "requiredDocumentTypes": ["string"],
                "expectedSealName": "string",
                "ruleVersion": "string?",
            }
            if name == "verify_design_license_seals"
            else {
                "documents": ["object"],
                "targetDocumentTypes": ["string"],
                "ruleVersion": "string?",
            }
            if name == "evaluate_calculation_document_consistency"
            else {
                "agencies": ["object"],
                "evaluationMode": "identity|method_coverage|date_coverage",
                "failureAction": "string?",
                "ruleVersion": "string?",
            }
            if name == "evaluate_ndt_agencies"
            else {
                "approvalItemCodes": ["string"],
                "ruleVersion": "string?",
            }
            if name == "decode_ndt_approval_item_codes"
            else {
                "licenseScopes": ["string"],
                "requiredPipelineGrades": ["string"],
                "ruleVersion": "string?",
            }
            if name == "check_installation_license_scope"
            else {
                "facts": "object?",
                "requiredFields": ["string?"],
                "ruleChecks": ["object?"],
                "profile": "string?",
                "applicable": "boolean?",
            }
        ),
        "outputSchema": "deterministic-tool-result-v1",
    }
    for name in (*COMMON_TOOL_NAMES, *DOMAIN_TOOL_NAMES)
]

BUSINESS_TOOL_NAMES = {item["name"] for item in BUSINESS_TOOL_DESCRIPTORS}


def dispatch_business_tool(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    dedicated_r24_r34_tools = {
        "evaluate_welding_consumable",
        "evaluate_welding_consumable_control",
        "evaluate_pipe_fit_up",
        "evaluate_welding_process",
        "evaluate_weld_appearance",
        "evaluate_weld_repair",
        "resolve_pwht_applicability",
        "evaluate_heat_treatment",
        "evaluate_heat_treatment_instruments",
    }
    # 保留历史显式规则档案调用兼容性；正式R24-R34绑定不再使用该入口。
    if tool_name in dedicated_r24_r34_tools and arguments.get("requiredFields") and arguments.get("ruleChecks"):
        return evaluate_rule_profile(tool_name, arguments)
    if tool_name == "check_wps_pqr_coverage" and arguments.get("qualifiedRanges") and not arguments.get("wpsItems"):
        return check_wps_pqr_coverage(arguments)
    handlers: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
        "check_license_registry_match": check_license_registry_match,
        "classify_r13_component_requirements": classify_r13_component_requirements,
        "classify_r14_component_applicability": classify_r14_component_applicability,
        "classify_r15_foreign_manufacturing_applicability": classify_r15_foreign_manufacturing_applicability,
        "classify_r15_regulatory_requirements": classify_r15_regulatory_requirements,
        "classify_r18_material_test_applicability": classify_r18_material_test_applicability,
        "validate_r19_semantic_judgment": validate_r19_semantic_judgment,
        "classify_r20_new_material_applicability": classify_r20_new_material_applicability,
        "evaluate_r20_new_material_procedure": evaluate_r20_new_material_procedure,
        "evaluate_r21_mark_transfer": evaluate_r21_mark_transfer,
        "evaluate_r22_material_substitution": evaluate_r22_material_substitution,
        "resolve_r23_valve_test_basis": resolve_r23_valve_test_basis,
        "evaluate_r23_valve_sampling": evaluate_r23_valve_sampling,
        "evaluate_r23_valve_test_records": evaluate_r23_valve_test_records,
        "check_required": check_required,
        "check_scope_coverage": check_scope_coverage,
        "check_cross_document_match": check_cross_document_match,
        "check_signature_completeness": check_signature_completeness,
        "check_numeric_range": check_numeric_range,
        "check_conditional_requirement": check_conditional_requirement,
        "check_sampling_requirement": check_sampling_requirement,
        "check_document_set_completeness": check_document_set_completeness,
        "check_standard_version_active": check_standard_version_active,
        "check_traceability": check_traceability,
        "check_ndt_personnel_coverage": check_ndt_personnel_coverage,
        "check_installation_license_scope": check_installation_license_scope,
        "check_wps_pqr_coverage": check_r25_wps_pqr_coverage,
        "decode_ndt_approval_item_codes": decode_ndt_approval_item_codes,
        "evaluate_installation_license_scope": evaluate_installation_license_scope,
        "evaluate_ndt_organization_scope": evaluate_ndt_organization_scope,
        "evaluate_ndt_agencies": evaluate_ndt_agencies,
        "evaluate_design_approval_level": evaluate_design_approval_level,
        "evaluate_design_document_approval": evaluate_design_document_approval,
        "evaluate_design_change_approval": evaluate_design_change_approval,
        "evaluate_design_special_requirements": evaluate_design_special_requirements,
        "evaluate_calculation_document_consistency": evaluate_calculation_document_consistency,
        "evaluate_component_manufacturer_scope": evaluate_component_manufacturer_scope,
        "evaluate_rt_film": evaluate_rt_film,
        "evaluate_pressure_test": evaluate_pressure_test,
        "evaluate_r13_supervision_certificate_completeness": evaluate_r13_supervision_certificate_completeness,
        "evaluate_r13_type_test_coverage": evaluate_r13_type_test_coverage,
        "evaluate_r14_component_design_match": evaluate_r14_component_design_match,
        "evaluate_r14_pressure_compatibility": evaluate_r14_pressure_compatibility,
        "evaluate_r14_special_report_coverage": evaluate_r14_special_report_coverage,
        "resolve_r14_required_inspection_items": resolve_r14_required_inspection_items,
        "evaluate_r15_manufacturing_inspection_route": evaluate_r15_manufacturing_inspection_route,
        "evaluate_r15_manufacturing_license_coverage": evaluate_r15_manufacturing_license_coverage,
        "evaluate_r15_type_test_coverage": evaluate_r15_type_test_coverage,
        "evaluate_r16_batch_traceability": evaluate_r16_batch_traceability,
        "evaluate_r16_quality_certificate_batch_coverage": evaluate_r16_quality_certificate_batch_coverage,
        "evaluate_r16_quality_certificate_content": evaluate_r16_quality_certificate_content,
        "evaluate_r16_quality_certificate_design_match": evaluate_r16_quality_certificate_design_match,
        "evaluate_r16_quality_certificate_form_and_seals": evaluate_r16_quality_certificate_form_and_seals,
        "evaluate_r16_quality_certificate_results": evaluate_r16_quality_certificate_results,
        "resolve_r16_product_standard_profile": resolve_r16_product_standard_profile,
        "evaluate_r17_acceptance_procedure": evaluate_r17_acceptance_procedure,
        "evaluate_r17_arrival_acceptance_batch_coverage": evaluate_r17_arrival_acceptance_batch_coverage,
        "evaluate_r17_nonconformance_control": evaluate_r17_nonconformance_control,
        "evaluate_r17_sampling_witness_chain": evaluate_r17_sampling_witness_chain,
        "resolve_r17_sampling_retest_requirement": resolve_r17_sampling_retest_requirement,
        "evaluate_r18_material_ndt_report_completeness": evaluate_r18_material_ndt_report_completeness,
        "evaluate_r18_material_report_approval_procedure": evaluate_r18_material_report_approval_procedure,
        "evaluate_r18_material_retest_report_completeness": evaluate_r18_material_retest_report_completeness,
        "evaluate_r18_material_test_results_and_traceability": evaluate_r18_material_test_results_and_traceability,
        "resolve_r18_material_test_requirement_profile": resolve_r18_material_test_requirement_profile,
        "evaluate_valve_test": evaluate_valve_test,
        "evaluate_welding_consumable": evaluate_r26_welding_consumable,
        "evaluate_welding_consumable_control": evaluate_r27_welding_consumable_control,
        "evaluate_pipe_fit_up": evaluate_r28_pipe_fit_up,
        "evaluate_welding_process": evaluate_r29_welding_process,
        "evaluate_weld_appearance": evaluate_r30_weld_appearance,
        "evaluate_weld_repair": evaluate_r31_weld_repair,
        "resolve_pwht_applicability": resolve_pwht_applicability,
        "evaluate_heat_treatment": evaluate_r32_r34_heat_treatment,
        "evaluate_heat_treatment_instruments": evaluate_r33_heat_treatment_instruments,
        "verify_design_license_seals": verify_design_license_seals,
    }
    handler = handlers.get(tool_name)
    if handler:
        return handler(arguments)
    return evaluate_rule_profile(tool_name, arguments)


def check_required(arguments: dict[str, Any]) -> dict[str, Any]:
    facts = fact_container(arguments)
    required_fields = string_list(arguments.get("requiredFields"))
    if not required_fields:
        return insufficient("check_required", arguments, "requiredFields_not_configured")
    checks = [
        check(f"required_{safe_code(path)}", is_present(read_path(facts, path)), read_path(facts, path), "present")
        for path in required_fields
    ]
    return checked_result("check_required", facts, checks)


def check_scope_coverage(arguments: dict[str, Any]) -> dict[str, Any]:
    granted = normalized_set(arguments.get("grantedScopes") or arguments.get("actualScopes"))
    required = normalized_set(arguments.get("requiredScopes"))
    coverage_map = {
        normalize_value(key, "text"): normalized_set(value)
        for key, value in dict_value(arguments.get("coverageMap")).items()
    }
    if not granted or not required:
        return insufficient("check_scope_coverage", arguments, "scope_facts_missing")
    checks = []
    for scope in sorted(required):
        accepted = {scope} | coverage_map.get(scope, set())
        checks.append(check(f"scope_{safe_code(scope)}", bool(granted & accepted), sorted(granted), sorted(accepted)))
    return checked_result("check_scope_coverage", {"grantedScopes": sorted(granted), "requiredScopes": sorted(required)}, checks)


def check_license_registry_match(arguments: dict[str, Any]) -> dict[str, Any]:
    candidates = list_of_dicts(arguments.get("licenseCandidates"))
    verifications = list_of_dicts(arguments.get("registryVerifications"))
    if not candidates:
        return insufficient("check_license_registry_match", arguments, "manufacturing_license_candidates_missing")
    by_candidate = {
        str(item.get("candidateId")): item
        for item in verifications
        if item.get("candidateId")
    }
    checks: list[dict[str, Any]] = []
    incomplete = False
    failed = False
    for candidate in candidates:
        candidate_id = str(candidate.get("candidateId") or "")
        verification = by_candidate.get(candidate_id)
        if not verification:
            incomplete = True
            checks.append(check(f"registry_{safe_code(candidate_id)}_completed", False, None, "manual_registry_verification"))
            continue
        outcome = str(verification.get("outcome") or "")
        if outcome == "unable_to_verify":
            incomplete = True
            checks.append(check(f"registry_{safe_code(candidate_id)}_completed", False, outcome, "verified_match"))
            continue
        if outcome in {"not_found", "verified_mismatch"}:
            failed = True
            checks.append(check(f"registry_{safe_code(candidate_id)}_found_and_matched", False, outcome, "verified_match"))
            continue
        correction_reason = str(verification.get("correctionReason") or "").strip()
        license_matches = _license_no(verification.get("registryLicenseNo")) == _license_no(candidate.get("licenseNo"))
        organization_matches = _organization(verification.get("registryOrganizationName")) == _organization(
            candidate.get("organizationName")
        )
        identity_passed = (license_matches and organization_matches) or bool(correction_reason)
        registry_active = str(verification.get("registryStatus") or "unknown") == "active"
        failed = failed or not identity_passed or not registry_active
        checks.extend(
            [
                check(
                    f"registry_{safe_code(candidate_id)}_identity",
                    identity_passed,
                    {
                        "registryLicenseNo": verification.get("registryLicenseNo"),
                        "registryOrganizationName": verification.get("registryOrganizationName"),
                        "correctionReason": correction_reason or None,
                    },
                    {"licenseNo": candidate.get("licenseNo"), "organizationName": candidate.get("organizationName")},
                ),
                check(
                    f"registry_{safe_code(candidate_id)}_active",
                    registry_active,
                    verification.get("registryStatus"),
                    "active",
                ),
            ]
        )
    output_result = "failed" if failed else "evidence_insufficient" if incomplete else "passed"
    return result(
        "check_license_registry_match",
        output_result,
        facts={"licenseCandidates": candidates, "registryVerifications": verifications},
        checks=checks,
        rule_version=rule_version(arguments),
    )


def evaluate_component_manufacturer_scope(arguments: dict[str, Any]) -> dict[str, Any]:
    candidates = list_of_dicts(arguments.get("licenseCandidates"))
    verifications = list_of_dicts(arguments.get("registryVerifications"))
    component_items = list_of_dicts(arguments.get("componentItems"))
    if not component_items:
        return insufficient("evaluate_component_manufacturer_scope", arguments, "project_component_items_missing")
    by_candidate = {
        str(item.get("candidateId")): item
        for item in verifications
        if item.get("candidateId") and item.get("outcome") == "verified_match"
    }
    verified_licenses = [
        {
            "candidate": candidate,
            "verification": by_candidate[str(candidate.get("candidateId"))],
        }
        for candidate in candidates
        if str(candidate.get("candidateId")) in by_candidate
    ]
    if not verified_licenses:
        return insufficient("evaluate_component_manufacturer_scope", arguments, "verified_manufacturing_licenses_missing")
    checks: list[dict[str, Any]] = []
    matrix: list[dict[str, Any]] = []
    incomplete = False
    failed = False
    for item in component_items:
        item_id = str(item.get("componentItemId") or f"item-{len(matrix) + 1}")
        manufacturer = _organization(item.get("manufacturerName"))
        component_type = str(item.get("componentType") or "").strip()
        required_scope = _component_scope_category(component_type)
        if not manufacturer or not required_scope:
            incomplete = True
            checks.append(
                check(
                    f"component_{safe_code(item_id)}_classifiable",
                    False,
                    {"manufacturerName": item.get("manufacturerName"), "componentType": component_type},
                    "manufacturer_and_supported_component_type",
                )
            )
            matrix.append({**item, "result": "evidence_insufficient", "reason": "component_mapping_missing"})
            continue
        matched = [
            license_item
            for license_item in verified_licenses
            if _organization(license_item["verification"].get("registryOrganizationName")) == manufacturer
        ]
        if not matched:
            failed = True
            checks.append(check(f"component_{safe_code(item_id)}_manufacturer_license", False, manufacturer, "verified_license"))
            matrix.append({**item, "requiredScopeCategory": required_scope, "result": "failed", "reason": "manufacturer_license_not_verified"})
            continue
        scopes = [str(entry["verification"].get("registryScopeRaw") or "") for entry in matched]
        covered = any(_scope_covers_component(scope, required_scope) for scope in scopes)
        failed = failed or not covered
        checks.append(
            check(
                f"component_{safe_code(item_id)}_scope",
                covered,
                scopes,
                required_scope,
            )
        )
        matrix.append(
            {
                **item,
                "requiredScopeCategory": required_scope,
                "matchedLicenseCandidateIds": [entry["candidate"].get("candidateId") for entry in matched],
                "registryScopes": scopes,
                "result": "passed" if covered else "failed",
            }
        )
    output_result = "failed" if failed else "evidence_insufficient" if incomplete else "passed"
    return result(
        "evaluate_component_manufacturer_scope",
        output_result,
        facts={"componentCoverageMatrix": matrix},
        checks=checks,
        rule_version=rule_version(arguments),
    )


def check_cross_document_match(arguments: dict[str, Any]) -> dict[str, Any]:
    comparisons = list_of_dicts(arguments.get("comparisons"))
    if not comparisons:
        return insufficient("check_cross_document_match", arguments, "comparisons_missing")
    checks = []
    for index, item in enumerate(comparisons, 1):
        values = [value for value in item.get("values") or [] if value not in {None, ""}]
        mode = str(item.get("normalizer") or "text")
        tolerance = decimal(item.get("tolerance"))
        if len(values) < int(item.get("requiredCount") or 2):
            checks.append(check(f"comparison_{index}_has_values", False, len(values), item.get("requiredCount") or 2))
            continue
        if tolerance is not None:
            numbers = [decimal(value) for value in values]
            passed = all(value is not None for value in numbers) and max(numbers) - min(numbers) <= tolerance
            actual: Any = numbers
        else:
            actual = [normalize_value(value, mode) for value in values]
            passed = len(set(actual)) == 1
        checks.append(check(str(item.get("code") or f"comparison_{index}"), passed, actual, "all_equal"))
    return checked_result("check_cross_document_match", {"comparisons": comparisons}, checks)


def check_signature_completeness(arguments: dict[str, Any]) -> dict[str, Any]:
    actual = normalized_set(arguments.get("actualRoles") or arguments.get("signatureRoles"))
    required = normalized_set(arguments.get("requiredRoles"))
    if not required:
        return insufficient("check_signature_completeness", arguments, "required_signature_roles_missing")
    checks = [check(f"signature_{safe_code(role)}", role in actual, sorted(actual), role) for role in sorted(required)]
    return checked_result("check_signature_completeness", {"actualRoles": sorted(actual), "requiredRoles": sorted(required)}, checks)


def check_numeric_range(arguments: dict[str, Any]) -> dict[str, Any]:
    ranges = list_of_dicts(arguments.get("ranges") or arguments.get("checks"))
    if not ranges:
        return insufficient("check_numeric_range", arguments, "numeric_ranges_missing")
    checks = []
    for index, item in enumerate(ranges, 1):
        value = decimal(item.get("value"))
        minimum = decimal(item.get("min"))
        maximum = decimal(item.get("max"))
        if value is None or minimum is None and maximum is None:
            checks.append(check(str(item.get("code") or f"range_{index}"), False, value, "configured_range"))
            continue
        min_ok = minimum is None or (value >= minimum if item.get("includeMin", True) else value > minimum)
        max_ok = maximum is None or (value <= maximum if item.get("includeMax", True) else value < maximum)
        checks.append(check(str(item.get("code") or f"range_{index}"), min_ok and max_ok, value, {"min": minimum, "max": maximum}))
    return checked_result("check_numeric_range", {"ranges": ranges}, checks)


def check_conditional_requirement(arguments: dict[str, Any]) -> dict[str, Any]:
    if "condition" not in arguments:
        return insufficient("check_conditional_requirement", arguments, "condition_missing")
    condition = arguments.get("condition")
    if not isinstance(condition, bool):
        return insufficient("check_conditional_requirement", arguments, "condition_not_boolean")
    if not condition:
        return result("check_conditional_requirement", "not_applicable", facts=arguments, checks=[])
    facts = fact_container(arguments)
    required_fields = string_list(arguments.get("requiredFields"))
    if not required_fields:
        return insufficient("check_conditional_requirement", arguments, "conditional_required_fields_missing")
    checks = [check(f"required_{safe_code(path)}", is_present(read_path(facts, path)), read_path(facts, path), "present") for path in required_fields]
    return checked_result("check_conditional_requirement", facts, checks)


def check_sampling_requirement(arguments: dict[str, Any]) -> dict[str, Any]:
    population = integer(arguments.get("populationCount"))
    sampled = integer(arguments.get("sampledCount"))
    ratio = decimal(arguments.get("requiredRatio"))
    minimum = integer(arguments.get("minimumCount"))
    if population is None or sampled is None or population < 0 or sampled < 0 or ratio is None and minimum is None:
        return insufficient("check_sampling_requirement", arguments, "sampling_parameters_missing")
    required_by_ratio = ceiling(Decimal(population) * ratio) if ratio is not None else 0
    required_count = max(required_by_ratio, minimum or 0)
    checks = [
        check("sample_not_larger_than_population", sampled <= population, sampled, population),
        check("sample_count_satisfies_requirement", sampled >= required_count, sampled, required_count),
    ]
    if arguments.get("selectedIds") is not None:
        selected = string_list(arguments.get("selectedIds"))
        checks.append(check("selected_ids_match_sample_count", len(set(selected)) == sampled, len(set(selected)), sampled))
    return checked_result("check_sampling_requirement", {**arguments, "requiredCount": required_count}, checks)


def check_document_set_completeness(arguments: dict[str, Any]) -> dict[str, Any]:
    required = normalized_set(arguments.get("requiredDocumentTypes"))
    uploaded = normalized_set(arguments.get("uploadedDocumentTypes"))
    parseable = normalized_set(arguments.get("parseableDocumentTypes") or arguments.get("uploadedDocumentTypes"))
    if not required:
        return insufficient("check_document_set_completeness", arguments, "required_document_types_missing")
    checks = []
    for document_type in sorted(required):
        checks.append(check(f"uploaded_{safe_code(document_type)}", document_type in uploaded, sorted(uploaded), document_type))
        checks.append(check(f"parseable_{safe_code(document_type)}", document_type in parseable, sorted(parseable), document_type))
    return checked_result(
        "check_document_set_completeness",
        {"requiredDocumentTypes": sorted(required), "uploadedDocumentTypes": sorted(uploaded), "parseableDocumentTypes": sorted(parseable)},
        checks,
    )


def check_standard_version_active(arguments: dict[str, Any]) -> dict[str, Any]:
    references = list_of_dicts(arguments.get("standardReferences"))
    review_date = parse_date(arguments.get("reviewDate"))
    if not references or review_date is None:
        return insufficient("check_standard_version_active", arguments, "standard_version_facts_missing")
    checks = []
    for index, item in enumerate(references, 1):
        effective = parse_date(item.get("effectiveFrom"))
        withdrawn = parse_date(item.get("withdrawnOn"))
        status = normalize_value(item.get("status"), "text")
        active_status = status not in {"withdrawn", "废止", "obsolete", "replaced"}
        active_period = (effective is None or effective <= review_date) and (withdrawn is None or review_date < withdrawn)
        checks.append(check(str(item.get("standardRef") or f"standard_{index}"), active_status and active_period, item, review_date))
    return checked_result("check_standard_version_active", {"standardReferences": references, "reviewDate": review_date}, checks)


def check_traceability(arguments: dict[str, Any]) -> dict[str, Any]:
    items = list_of_dicts(arguments.get("items"))
    if not items:
        return insufficient("check_traceability", arguments, "traceability_items_missing")
    checks = []
    for index, item in enumerate(items, 1):
        original = item.get("originalMark")
        transferred = item.get("transferredMark")
        batch = item.get("batchNo")
        record = item.get("transferRecord") or item.get("record")
        checks.extend(
            [
                check(f"item_{index}_original_mark", is_present(original), original, "present"),
                check(f"item_{index}_transferred_mark", is_present(transferred), transferred, "present"),
                check(f"item_{index}_batch", is_present(batch), batch, "present"),
                check(f"item_{index}_record", is_present(record), record, "present"),
            ]
        )
        if isinstance(record, dict) and record.get("batchNo") is not None:
            checks.append(check(f"item_{index}_batch_matches", normalize_value(batch, "text") == normalize_value(record.get("batchNo"), "text"), batch, record.get("batchNo")))
    return checked_result("check_traceability", {"items": items}, checks)


def check_ndt_personnel_coverage(arguments: dict[str, Any]) -> dict[str, Any]:
    personnel = list_of_dicts(arguments.get("personnel"))
    work_items = list_of_dicts(arguments.get("workItems"))
    if not personnel or not work_items:
        return insufficient("check_ndt_personnel_coverage", arguments, "personnel_or_work_items_missing")
    checks = []
    for index, work in enumerate(work_items, 1):
        method = normalize_value(work.get("method"), "text")
        required_level = integer(work.get("requiredLevel")) or 1
        matched = [
            person
            for person in personnel
            if person_is_current(person, arguments.get("workDate"))
            and method in normalized_set(person.get("methods"))
            and (integer(person.get("level")) or 0) >= required_level
        ]
        checks.append(check(f"work_{index}_covered", bool(matched), [item.get("personId") for item in matched], {"method": method, "level": required_level}))
    return checked_result("check_ndt_personnel_coverage", {"personnel": personnel, "workItems": work_items}, checks)


def check_wps_pqr_coverage(arguments: dict[str, Any]) -> dict[str, Any]:
    pqr = list_of_dicts(arguments.get("qualifiedRanges") or arguments.get("pqrItems"))
    work_items = list_of_dicts(arguments.get("workItems"))
    if not pqr or not work_items:
        return insufficient("check_wps_pqr_coverage", arguments, "pqr_or_work_items_missing")
    checks = []
    for index, work in enumerate(work_items, 1):
        matched = [item for item in pqr if coverage_item_matches(item, work)]
        checks.append(check(f"work_{index}_covered", bool(matched), work, [item.get("id") for item in matched]))
    return checked_result("check_wps_pqr_coverage", {"qualifiedRanges": pqr, "workItems": work_items}, checks)


def check_installation_license_scope(arguments: dict[str, Any]) -> dict[str, Any]:
    scopes = normalized_set(arguments.get("licenseScopes"))
    grades = normalized_set(arguments.get("requiredPipelineGrades"))
    if not scopes or not grades:
        return insufficient("check_installation_license_scope", arguments, "license_scope_facts_missing")
    coverage = {
        "gc1": {"gc1"},
        "gc2": {"gc1", "gc2", "gcd"},
        "gcd": {"gcd", "a级锅炉安装资质"},
    }
    checks = [
        check(
            f"grade_{safe_code(grade)}",
            bool(scopes & coverage.get(grade, {grade})),
            sorted(scopes),
            sorted(coverage.get(grade, {grade})),
        )
        for grade in sorted(grades)
    ]
    return checked_result(
        "check_installation_license_scope",
        {"licenseScopes": sorted(scopes), "requiredPipelineGrades": sorted(grades)},
        checks,
        "installation-license-scope-cn-v2",
    )


NDT_APPROVAL_CODE_METHODS: dict[str, set[str]] = {
    "CG": {"RT", "UT", "MT", "PT"},
    "ECT": {"ECT"},
    "AE": {"AE"},
    "TOFD": {"TOFD"},
    "PA": {"PA"},
    "MFL": {"MFL"},
    "TC": {"TC"},
    "FD1": {"FD1"},
    "FD2": {"FD2"},
}


def decode_ndt_approval_item_codes(arguments: dict[str, Any]) -> dict[str, Any]:
    codes = unique_upper(arguments.get("approvalItemCodes"))
    if not codes:
        return insufficient("decode_ndt_approval_item_codes", arguments, "approval_item_codes_missing")
    unknown = [code for code in codes if code not in NDT_APPROVAL_CODE_METHODS]
    decoded = sorted({method for code in codes for method in NDT_APPROVAL_CODE_METHODS.get(code, set())})
    output = result(
        "decode_ndt_approval_item_codes",
        "evidence_insufficient" if unknown else "passed",
        facts={"approvalItemCodes": codes, "decodedMethods": decoded, "unknownCodes": unknown},
        checks=[check("all_approval_codes_decoded", not unknown, unknown, [])],
        rule_version=str(arguments.get("ruleVersion") or "ndt-approval-code-tsg-z7002-2022-v1"),
    )
    if unknown:
        output["warnings"] = ["unknown_ndt_approval_item_codes"]
    return output


def evaluate_ndt_agencies(arguments: dict[str, Any]) -> dict[str, Any]:
    agencies = list_of_dicts(arguments.get("agencies"))
    mode = str(arguments.get("evaluationMode") or "").strip()
    if not agencies:
        return insufficient("evaluate_ndt_agencies", arguments, "ndt_agencies_missing")
    if mode not in {"identity", "method_coverage", "date_coverage"}:
        return insufficient("evaluate_ndt_agencies", arguments, "ndt_evaluation_mode_unsupported")

    checks: list[dict[str, Any]] = []
    agency_results: list[dict[str, Any]] = []
    recommended_actions: list[dict[str, Any]] = []
    for index, agency in enumerate(agencies, 1):
        agency_id = str(agency.get("agencyId") or "").strip()
        if not agency_id:
            return insufficient("evaluate_ndt_agencies", arguments, "ndt_agency_id_missing")
        item_checks: list[dict[str, Any]] = []
        item_facts: dict[str, Any] = {"agencyId": agency_id}
        if mode == "identity":
            license_name = agency.get("licenseOrganizationName")
            plan_name = agency.get("planOrganizationName")
            if not license_name or not plan_name:
                return insufficient("evaluate_ndt_agencies", arguments, "ndt_organization_names_missing")
            normalized_license = normalize_value(license_name, "organization_name")
            normalized_plan = normalize_value(plan_name, "organization_name")
            item_checks.append(check(f"agency_{index}_organization_name", normalized_license == normalized_plan, license_name, plan_name))
            item_facts.update({"licenseOrganizationName": license_name, "planOrganizationName": plan_name})
        elif mode == "method_coverage":
            codes = unique_upper(agency.get("approvalItemCodes"))
            required = set(unique_upper(agency.get("requiredMethods")))
            if not codes or not required:
                return insufficient("evaluate_ndt_agencies", arguments, "ndt_codes_or_required_methods_missing")
            unknown = [code for code in codes if code not in NDT_APPROVAL_CODE_METHODS]
            if unknown:
                return insufficient("evaluate_ndt_agencies", arguments, "unknown_ndt_approval_item_codes")
            decoded = {method for code in codes for method in NDT_APPROVAL_CODE_METHODS[code]}
            for method in sorted(required):
                item_checks.append(check(f"agency_{index}_method_{safe_code(method)}", method in decoded, sorted(decoded), method))
            item_facts.update({"approvalItemCodes": codes, "decodedMethods": sorted(decoded), "requiredMethods": sorted(required)})
        else:
            valid_from = parse_date(agency.get("validFrom"))
            valid_until = parse_date(agency.get("validUntil"))
            period_start = parse_date(agency.get("periodStart"))
            period_end = parse_date(agency.get("plannedPeriodEnd"))
            if valid_until is None or period_start is None or period_end is None:
                return insufficient("evaluate_ndt_agencies", arguments, "ndt_license_or_planned_period_dates_missing")
            starts_before = valid_from is None or valid_from <= period_start
            ends_after = valid_until >= period_end
            item_checks.extend(
                [
                    check(f"agency_{index}_valid_from", starts_before, valid_from, period_start),
                    check(f"agency_{index}_valid_until", ends_after, valid_until, period_end),
                ]
            )
            item_facts.update(
                {
                    "validFrom": valid_from,
                    "validUntil": valid_until,
                    "periodStart": period_start,
                    "plannedPeriodEnd": period_end,
                }
            )
            if not starts_before or not ends_after:
                recommended_actions.append(
                    {
                        "agencyId": agency_id,
                        "action": str(arguments.get("failureAction") or "CONTACT_NOTICE_REQUIRED"),
                        "externalDocumentCreated": False,
                    }
                )
        checks.extend(item_checks)
        agency_results.append(
            {
                **item_facts,
                "result": "passed" if all(item.get("passed") for item in item_checks) else "failed",
            }
        )

    output = result(
        "evaluate_ndt_agencies",
        "passed" if checks and all(item.get("passed") for item in checks) else "failed",
        facts={"evaluationMode": mode, "agencyCount": len(agencies)},
        checks=checks,
        rule_version=str(arguments.get("ruleVersion") or "ndt-agency-tsg-z7002-2022-v1"),
    )
    output["agencyResults"] = agency_results
    output["recommendedActions"] = recommended_actions
    return output


def evaluate_installation_license_scope(arguments: dict[str, Any]) -> dict[str, Any]:
    scopes = normalized_set(arguments.get("licenseScopes"))
    grades = normalized_set(arguments.get("requiredPipelineGrades"))
    if not scopes or not grades:
        return insufficient("evaluate_installation_license_scope", arguments, "license_scope_facts_missing")
    aliases = {"gc1": {"gc1"}, "gc2": {"gc1", "gc2", "gcd"}, "gcd": {"gcd", "a级锅炉安装资质"}}
    checks = [check(f"grade_{safe_code(grade)}", bool(scopes & aliases.get(grade, {grade})), sorted(scopes), sorted(aliases.get(grade, {grade}))) for grade in sorted(grades)]
    dates = date_coverage_checks(arguments)
    if dates is None:
        return insufficient("evaluate_installation_license_scope", arguments, "license_or_construction_dates_missing")
    return checked_result("evaluate_installation_license_scope", arguments, [*checks, *dates], "installation-license-scope-cn-v1")


def evaluate_ndt_organization_scope(arguments: dict[str, Any]) -> dict[str, Any]:
    license_name = arguments.get("licenseOrganizationName")
    plan_name = arguments.get("planOrganizationName")
    methods = normalized_set(arguments.get("licensedMethods"))
    required = normalized_set(arguments.get("requiredMethods"))
    if not license_name or not plan_name or not methods or not required:
        return insufficient("evaluate_ndt_organization_scope", arguments, "ndt_organization_facts_missing")
    checks = [
        check("organization_name_matches", normalize_value(license_name, "organization_name") == normalize_value(plan_name, "organization_name"), license_name, plan_name),
        *[check(f"method_{safe_code(method)}", method in methods, sorted(methods), method) for method in sorted(required)],
    ]
    dates = date_coverage_checks(arguments)
    if dates is None:
        return insufficient("evaluate_ndt_organization_scope", arguments, "license_or_construction_dates_missing")
    return checked_result("evaluate_ndt_organization_scope", arguments, [*checks, *dates], "ndt-organization-scope-cn-v1")


def evaluate_design_approval_level(arguments: dict[str, Any]) -> dict[str, Any]:
    documents = list_of_dicts(arguments.get("documents"))
    if not documents:
        return insufficient("evaluate_design_approval_level", arguments, "design_documents_missing")
    checks = []
    for index, document in enumerate(documents, 1):
        actual = normalized_set(document.get("signatureRoles"))
        required = normalized_set(document.get("requiredRoles") or arguments.get("requiredRoles"))
        if not required:
            return insufficient("evaluate_design_approval_level", arguments, "required_signature_roles_missing")
        for role in sorted(required):
            checks.append(check(f"document_{index}_{safe_code(role)}", role in actual, sorted(actual), role))
        if document.get("bodyUploaded") is not None:
            checks.append(check(f"document_{index}_body_uploaded", document.get("bodyUploaded") is True, document.get("bodyUploaded"), True))
    return checked_result("evaluate_design_approval_level", {"documents": documents}, checks)


def evaluate_calculation_document_consistency(arguments: dict[str, Any]) -> dict[str, Any]:
    documents = list_of_dicts(arguments.get("documents"))
    target_types = normalized_set(arguments.get("targetDocumentTypes"))
    if not documents or not target_types:
        return insufficient("evaluate_calculation_document_consistency", arguments, "calculation_documents_or_types_missing")
    selected = [item for item in documents if normalize_value(item.get("documentType"), "text") in target_types]
    if not selected:
        return insufficient("evaluate_calculation_document_consistency", arguments, "target_calculation_documents_missing")

    checks: list[dict[str, Any]] = []
    document_results: list[dict[str, Any]] = []
    for index, document in enumerate(selected, 1):
        document_id = str(document.get("documentId") or "").strip()
        comparisons = list_of_dicts(document.get("parameterComparisons"))
        covered_ids = string_list(document.get("coveredPipelineIds"))
        if not document_id or "bodyUploaded" not in document or not covered_ids or not comparisons:
            return insufficient(
                "evaluate_calculation_document_consistency",
                arguments,
                "calculation_identity_body_coverage_or_comparisons_missing",
            )
        item_checks = [
            check(f"document_{index}_body_uploaded", document.get("bodyUploaded") is True, document.get("bodyUploaded"), True),
            check(f"document_{index}_covered_pipeline", bool(covered_ids), covered_ids, "non_empty"),
        ]
        for comparison_index, comparison in enumerate(comparisons, 1):
            actual = comparison.get("documentValue")
            expected = comparison.get("designValue")
            if actual is None or expected is None:
                return insufficient("evaluate_calculation_document_consistency", arguments, "calculation_parameter_value_missing")
            tolerance = decimal(comparison.get("tolerance"))
            if tolerance is not None:
                actual_number = decimal(actual)
                expected_number = decimal(expected)
                if actual_number is None or expected_number is None:
                    return insufficient("evaluate_calculation_document_consistency", arguments, "calculation_numeric_parameter_invalid")
                passed = abs(actual_number - expected_number) <= tolerance
            else:
                normalizer = str(comparison.get("normalizer") or "text")
                passed = normalize_value(actual, normalizer) == normalize_value(expected, normalizer)
            code = safe_code(comparison.get("code") or f"parameter_{comparison_index}")
            item_checks.append(check(f"document_{index}_{code}", passed, actual, expected))
        checks.extend(item_checks)
        document_results.append(
            {
                "documentId": document_id,
                "documentType": document.get("documentType"),
                "coveredPipelineIds": covered_ids,
                "result": "passed" if all(item.get("passed") for item in item_checks) else "failed",
            }
        )
    output = result(
        "evaluate_calculation_document_consistency",
        "passed" if checks and all(item.get("passed") for item in checks) else "failed",
        facts={"documentCount": len(selected)},
        checks=checks,
        rule_version=str(arguments.get("ruleVersion") or "r06-calculation-consistency-v1"),
    )
    output["documentResults"] = document_results
    return output


FOUR_LEVEL_DESIGN_DOCUMENT_TYPES = {
    "pipeline_material_grade_table",
    "pipeline_stress_calculation",
    "equipment_layout_drawing",
    "pipeline_layout_drawing",
}


def evaluate_design_change_approval(arguments: dict[str, Any]) -> dict[str, Any]:
    has_changes = arguments.get("hasDesignChanges")
    if not isinstance(has_changes, bool):
        return insufficient("evaluate_design_change_approval", arguments, "design_change_applicability_missing")
    if not has_changes:
        return result(
            "evaluate_design_change_approval",
            "not_applicable",
            facts={"hasDesignChanges": False},
            checks=[],
            rule_version=str(arguments.get("ruleVersion") or "r07-design-change-approval-tsg31-2025-v1"),
        )
    documents = list_of_dicts(arguments.get("documents"))
    pipelines = list_of_dicts(arguments.get("pipelines"))
    if not documents:
        return insufficient("evaluate_design_change_approval", arguments, "design_change_documents_missing")
    pipeline_by_id = {str(item.get("pipelineId")): item for item in pipelines if item.get("pipelineId")}

    checks: list[dict[str, Any]] = []
    document_results: list[dict[str, Any]] = []
    for index, document in enumerate(documents, 1):
        document_id = str(document.get("documentId") or "").strip()
        document_type = normalize_value(document.get("documentType"), "text")
        approval_type = normalize_value(document.get("changedDocumentType") or document.get("documentType"), "text")
        if not document_id or not document_type or "bodyUploaded" not in document or "writtenApproval" not in document:
            return insufficient("evaluate_design_change_approval", arguments, "design_change_identity_body_or_approval_missing")
        actual_role_list = unique_normalized(document.get("signatureRoles"))
        if not actual_role_list:
            return insufficient("evaluate_design_change_approval", arguments, "design_change_signature_roles_missing")
        original_org = document.get("originalDesignOrganizationName")
        approving_org = document.get("approvingOrganizationName")
        if not original_org or not approving_org:
            return insufficient("evaluate_design_change_approval", arguments, "design_change_organization_names_missing")

        required_level = 3
        trigger_codes: list[str] = []
        if approval_type in FOUR_LEVEL_DESIGN_DOCUMENT_TYPES:
            covered_ids = string_list(document.get("coveredPipelineIds"))
            if covered_ids:
                covered = [pipeline_by_id[item] for item in covered_ids if item in pipeline_by_id]
                if len(covered) != len(set(covered_ids)):
                    return insufficient("evaluate_design_change_approval", arguments, "design_change_covered_pipeline_not_found")
            elif len(pipelines) == 1:
                covered = pipelines
            else:
                return insufficient("evaluate_design_change_approval", arguments, "design_change_pipeline_link_missing")
            for pipeline in covered:
                trigger = design_four_level_trigger(pipeline)
                if trigger is None:
                    return insufficient("evaluate_design_change_approval", arguments, "design_change_pipeline_parameters_missing")
                if trigger:
                    trigger_codes.append(trigger)
            if trigger_codes:
                required_level = 4

        required_roles = ["设计", "校核", "审核"] + (["审定"] if required_level == 4 else [])
        actual_roles = set(actual_role_list)
        item_checks = [
            check(f"document_{index}_body_uploaded", document.get("bodyUploaded") is True, document.get("bodyUploaded"), True),
            check(f"document_{index}_written_approval", document.get("writtenApproval") is True, document.get("writtenApproval"), True),
            check(
                f"document_{index}_original_design_organization",
                normalize_value(approving_org, "organization_name") == normalize_value(original_org, "organization_name"),
                approving_org,
                original_org,
            ),
            *[
                check(f"document_{index}_{safe_code(role)}", role in actual_roles, actual_role_list, role)
                for role in required_roles
            ],
        ]
        checks.extend(item_checks)
        document_results.append(
            {
                "documentId": document_id,
                "documentType": document.get("documentType"),
                "changedDocumentType": document.get("changedDocumentType"),
                "requiredApprovalLevel": required_level,
                "requiredRoles": required_roles,
                "actualRoles": actual_role_list,
                "triggerCodes": sorted(set(trigger_codes)),
                "result": "passed" if all(item.get("passed") for item in item_checks) else "failed",
            }
        )
    output = result(
        "evaluate_design_change_approval",
        "passed" if checks and all(item.get("passed") for item in checks) else "failed",
        facts={"hasDesignChanges": True, "documentCount": len(documents)},
        checks=checks,
        rule_version=str(arguments.get("ruleVersion") or "r07-design-change-approval-tsg31-2025-v1"),
    )
    output["documentResults"] = document_results
    return output


def verify_design_license_seals(arguments: dict[str, Any]) -> dict[str, Any]:
    has_changes = arguments.get("hasDesignChanges")
    if not isinstance(has_changes, bool):
        return insufficient("verify_design_license_seals", arguments, "design_change_applicability_missing")
    if not has_changes:
        return result("verify_design_license_seals", "not_applicable", facts={"hasDesignChanges": False}, checks=[])
    documents = list_of_dicts(arguments.get("documents"))
    required_types = normalized_set(arguments.get("requiredDocumentTypes"))
    expected_name = str(arguments.get("expectedSealName") or "").strip()
    if not documents or not required_types or not expected_name:
        return insufficient("verify_design_license_seals", arguments, "seal_documents_or_policy_missing")
    selected = [item for item in documents if normalize_value(item.get("documentType"), "text") in required_types]
    if not selected:
        return result(
            "verify_design_license_seals",
            "not_applicable",
            facts={"requiredDocumentTypes": sorted(required_types), "matchedDocumentCount": 0},
            checks=[],
            rule_version=str(arguments.get("ruleVersion") or "r07-design-license-seal-tsg31-2025-3.1.2-v1"),
        )

    checks: list[dict[str, Any]] = []
    document_results: list[dict[str, Any]] = []
    for index, document in enumerate(selected, 1):
        document_id = str(document.get("documentId") or "").strip()
        seal = dict_value(document.get("designLicenseSeal"))
        if not document_id or "present" not in seal:
            return insufficient("verify_design_license_seals", arguments, "seal_presence_fact_missing")
        item_checks = [check(f"document_{index}_seal_present", seal.get("present") is True, seal.get("present"), True)]
        if seal.get("present") is True:
            original_org = document.get("originalDesignOrganizationName")
            seal_name = seal.get("sealName")
            seal_org = seal.get("organizationName")
            impression_type = normalize_value(seal.get("impressionType"), "text")
            if not original_org or not seal_name or not seal_org or not impression_type:
                return insufficient("verify_design_license_seals", arguments, "seal_identity_or_impression_missing")
            item_checks.extend(
                [
                    check(f"document_{index}_seal_name", normalize_value(seal_name, "text") == normalize_value(expected_name, "text"), seal_name, expected_name),
                    check(
                        f"document_{index}_seal_organization",
                        normalize_value(seal_org, "organization_name") == normalize_value(original_org, "organization_name"),
                        seal_org,
                        original_org,
                    ),
                    check(f"document_{index}_seal_original", impression_type == "original", impression_type, "original"),
                    check(f"document_{index}_not_as_built_drawing", document.get("isAsBuiltDrawing") is not True, document.get("isAsBuiltDrawing"), False),
                ]
            )
            expected_license = document.get("expectedDesignLicenseNumber")
            if expected_license:
                item_checks.append(
                    check(
                        f"document_{index}_seal_license_number",
                        normalize_value(seal.get("licenseNumber"), "text") == normalize_value(expected_license, "text"),
                        seal.get("licenseNumber"),
                        expected_license,
                    )
                )
        checks.extend(item_checks)
        document_results.append(
            {
                "documentId": document_id,
                "documentType": document.get("documentType"),
                "sealRequired": True,
                "result": "passed" if all(item.get("passed") for item in item_checks) else "failed",
            }
        )
    output = result(
        "verify_design_license_seals",
        "passed" if checks and all(item.get("passed") for item in checks) else "failed",
        facts={"requiredDocumentTypes": sorted(required_types), "matchedDocumentCount": len(selected)},
        checks=checks,
        rule_version=str(arguments.get("ruleVersion") or "r07-design-license-seal-tsg31-2025-3.1.2-v1"),
    )
    output["documentResults"] = document_results
    return output


def evaluate_design_special_requirements(arguments: dict[str, Any]) -> dict[str, Any]:
    requirements = dict_value(arguments.get("requirements"))
    standard_rules = dict_value(arguments.get("standardRules"))
    required_paths_by_domain = dict_value(arguments.get("requiredPathsByDomain"))
    domains = string_list(arguments.get("domains"))
    if not requirements or not standard_rules or not required_paths_by_domain or not domains:
        return insufficient(
            "evaluate_design_special_requirements",
            arguments,
            "design_special_requirement_profile_missing",
        )

    checks: list[dict[str, Any]] = []
    domain_results: list[dict[str, Any]] = []
    for domain_name in domains:
        domain = dict_value(requirements.get(domain_name))
        if not domain or not isinstance(domain.get("specified"), bool):
            return insufficient(
                "evaluate_design_special_requirements",
                arguments,
                f"{domain_name}_requirement_fact_missing",
            )
        required_paths = string_list(required_paths_by_domain.get(domain_name))
        rule_container = standard_rules.get(domain_name)
        rules = list_of_dicts(rule_container.get("checks")) if isinstance(rule_container, dict) else list_of_dicts(rule_container)
        if not required_paths or not rules:
            return insufficient(
                "evaluate_design_special_requirements",
                arguments,
                f"{domain_name}_required_paths_or_standard_rules_missing",
            )

        domain_checks = [
            check(
                f"{safe_code(domain_name)}_specified",
                domain.get("specified") is True,
                domain.get("specified"),
                True,
            )
        ]
        missing_paths: list[str] = []
        for path in required_paths:
            actual = read_path(domain, path)
            present = is_present(actual)
            if not present:
                missing_paths.append(path)
            domain_checks.append(check(f"{safe_code(domain_name)}_{safe_code(path)}", present, actual, "present"))

        referenced_standards = set(string_list(domain.get("standardRefs")))
        standard_checks: list[dict[str, Any]] = []
        violations: list[str] = []
        for index, rule in enumerate(rules, 1):
            actual_path = str(rule.get("actualPath") or "").strip()
            standard_ref = str(rule.get("standardRef") or "").strip()
            operator = str(rule.get("operator") or "").strip()
            if not actual_path or not standard_ref or not operator:
                return insufficient(
                    "evaluate_design_special_requirements",
                    arguments,
                    f"{domain_name}_standard_rule_{index}_invalid",
                )
            reference_check = check(
                f"{safe_code(domain_name)}_standard_ref_{index}",
                standard_ref in referenced_standards,
                sorted(referenced_standards),
                standard_ref,
            )
            evaluated = evaluate_rule_check(
                {
                    **rule,
                    "actual": read_path(domain, actual_path),
                    "code": f"{safe_code(domain_name)}_{rule.get('code') or index}",
                }
            )
            if evaluated is None:
                return insufficient(
                    "evaluate_design_special_requirements",
                    arguments,
                    f"{domain_name}_standard_rule_{index}_unsupported",
                )
            standard_checks.extend([reference_check, evaluated])
            if not reference_check.get("passed"):
                violations.append(f"standard_not_referenced:{standard_ref}")
            if not evaluated.get("passed"):
                violations.append(str(rule.get("code") or f"rule_{index}"))

        checks.extend([*domain_checks, *standard_checks])
        completeness_passed = all(item.get("passed") for item in domain_checks)
        compliance_passed = all(item.get("passed") for item in standard_checks)
        domain_results.append(
            {
                "domain": domain_name,
                "specified": domain.get("specified"),
                "completenessResult": "passed" if completeness_passed else "failed",
                "standardComplianceResult": "passed" if compliance_passed else "failed",
                "missingPaths": missing_paths,
                "violations": violations,
                "standardRefs": sorted(referenced_standards),
                "result": "passed" if completeness_passed and compliance_passed else "failed",
            }
        )

    output = result(
        "evaluate_design_special_requirements",
        "passed" if checks and all(item.get("passed") for item in checks) else "failed",
        facts={"domains": domains},
        checks=checks,
        rule_version=str(arguments.get("ruleVersion") or "r09-design-special-requirements-v1"),
    )
    output["domainResults"] = domain_results
    return output


def evaluate_design_document_approval(arguments: dict[str, Any]) -> dict[str, Any]:
    """Evaluate R04 approval signatures per document and per covered pipeline."""
    mode = str(arguments.get("approvalMode") or "").strip()
    documents = list_of_dicts(arguments.get("documents"))
    target_types = normalized_set(arguments.get("targetDocumentTypes"))
    required_role_list = unique_normalized(arguments.get("requiredRoles"))
    required_roles = set(required_role_list)
    if mode not in {"three_level", "four_level_conditional"}:
        return insufficient("evaluate_design_document_approval", arguments, "approval_mode_unsupported")
    if not documents:
        return insufficient("evaluate_design_document_approval", arguments, "design_documents_missing")
    if not target_types or not required_roles:
        return insufficient("evaluate_design_document_approval", arguments, "approval_rule_parameters_missing")

    selected = [item for item in documents if normalize_value(item.get("documentType"), "text") in target_types]
    if not selected:
        return insufficient("evaluate_design_document_approval", arguments, "target_design_documents_missing")
    for document in selected:
        if not document.get("documentId") or "bodyUploaded" not in document or not isinstance(document.get("signatureRoles"), list):
            return insufficient("evaluate_design_document_approval", arguments, "document_identity_body_or_signatures_missing")

    pipelines = list_of_dicts(arguments.get("pipelines"))
    pipeline_by_id = {str(item.get("pipelineId")): item for item in pipelines if item.get("pipelineId")}
    if mode == "four_level_conditional" and not pipelines:
        return insufficient("evaluate_design_document_approval", arguments, "pipeline_design_parameters_missing")

    checks: list[dict[str, Any]] = []
    document_results: list[dict[str, Any]] = []
    applicable_document_count = 0
    for index, document in enumerate(selected, 1):
        trigger_codes: list[str] = []
        if mode == "four_level_conditional":
            covered_ids = string_list(document.get("coveredPipelineIds"))
            if covered_ids:
                covered = [pipeline_by_id[item] for item in covered_ids if item in pipeline_by_id]
                if len(covered) != len(set(covered_ids)):
                    return insufficient("evaluate_design_document_approval", arguments, "covered_pipeline_not_found")
            elif len(pipelines) == 1:
                covered = pipelines
            else:
                return insufficient("evaluate_design_document_approval", arguments, "document_pipeline_link_missing")
            for pipeline in covered:
                trigger = design_four_level_trigger(pipeline)
                if trigger is None:
                    return insufficient("evaluate_design_document_approval", arguments, "pipeline_grade_pressure_or_temperature_missing")
                if trigger:
                    trigger_codes.append(trigger)
            if not trigger_codes:
                continue

        applicable_document_count += 1
        actual_role_list = unique_normalized(document.get("signatureRoles"))
        actual_roles = set(actual_role_list)
        body_check = check(
            f"document_{index}_body_uploaded",
            document.get("bodyUploaded") is True,
            document.get("bodyUploaded"),
            True,
        )
        role_checks = [
            check(f"document_{index}_{safe_code(role)}", role in actual_roles, actual_role_list, role)
            for role in required_role_list
        ]
        checks.extend([body_check, *role_checks])
        missing_roles = [role for role in required_role_list if role not in actual_roles]
        document_results.append(
            {
                "documentId": document.get("documentId"),
                "documentType": document.get("documentType"),
                "requiredApprovalLevel": 3 if mode == "three_level" else 4,
                "triggerCodes": sorted(set(trigger_codes)),
                "requiredRoles": required_role_list,
                "actualRoles": actual_role_list,
                "missingRoles": missing_roles,
                "bodyUploaded": document.get("bodyUploaded"),
                "result": "passed" if body_check["passed"] and not missing_roles else "failed",
                "evidenceRefs": list(document.get("evidenceRefs") or []),
            }
        )

    if mode == "four_level_conditional" and applicable_document_count == 0:
        output = result(
            "evaluate_design_document_approval",
            "not_applicable",
            facts={"documents": selected, "pipelines": pipelines, "approvalMode": mode},
            checks=[],
            rule_version=rule_version(arguments),
        )
        output["documentResults"] = []
        return output

    output = result(
        "evaluate_design_document_approval",
        "passed" if checks and all(item.get("passed") for item in checks) else "failed",
        facts={"documents": selected, "pipelines": pipelines, "approvalMode": mode},
        checks=checks,
        rule_version=rule_version(arguments),
    )
    output["documentResults"] = document_results
    return output


def design_four_level_trigger(pipeline: dict[str, Any]) -> str | None:
    grade = normalize_value(pipeline.get("pipelineGrade"), "text")
    if not grade:
        return None
    if grade == "gc1":
        return "GC1_PIPELINE"
    if grade != "gcd":
        return ""
    pressure = decimal(pipeline.get("designPressureMPa"))
    if pressure is None:
        return None
    if pressure >= Decimal("16.7"):
        return "GCD_PRESSURE_GTE_16_7"
    if pressure < Decimal("4.0"):
        return ""
    temperature = decimal(pipeline.get("designTemperatureC"))
    if temperature is None:
        return None
    if temperature >= Decimal("570"):
        return "GCD_PRESSURE_GTE_4_AND_TEMPERATURE_GTE_570"
    return ""


def evaluate_rt_film(arguments: dict[str, Any]) -> dict[str, Any]:
    films = list_of_dicts(arguments.get("films"))
    report_weld_ids = set(string_list(arguments.get("reportWeldIds")))
    if not films:
        return insufficient("evaluate_rt_film", arguments, "film_inventory_missing")
    checks = []
    for index, film in enumerate(films, 1):
        weld_id = str(film.get("weldId") or "")
        checks.extend(
            [
                check(f"film_{index}_weld_id", bool(weld_id), weld_id, "present"),
                check(f"film_{index}_image_quality", film.get("imageQualityAccepted") is True, film.get("imageQualityAccepted"), True),
            ]
        )
        if report_weld_ids:
            checks.append(check(f"film_{index}_report_link", weld_id in report_weld_ids, weld_id, sorted(report_weld_ids)))
    sample_args = arguments.get("sampling")
    if isinstance(sample_args, dict):
        sample_result = check_sampling_requirement(sample_args)
        if sample_result.get("result") == "evidence_insufficient":
            return insufficient("evaluate_rt_film", arguments, "sampling_parameters_incomplete")
        checks.extend(sample_result.get("checks") or [])
    return checked_result("evaluate_rt_film", {"films": films, "reportWeldIds": sorted(report_weld_ids)}, checks)


def evaluate_pressure_test(arguments: dict[str, Any]) -> dict[str, Any]:
    required = ["timing", "medium", "pressurizationRate", "instrumentRequirements", "safetyMeasures", "acceptanceCriteria"]
    facts = fact_container(arguments)
    checks = [check(f"plan_{safe_code(path)}", is_present(read_path(facts, path)), read_path(facts, path), "present") for path in required]
    roles = normalized_set(arguments.get("signatureRoles") or facts.get("signatureRoles"))
    required_roles = normalized_set(arguments.get("requiredRoles"))
    if not required_roles:
        return insufficient("evaluate_pressure_test", arguments, "pressure_plan_required_roles_missing")
    checks.extend(check(f"signature_{safe_code(role)}", role in roles, sorted(roles), role) for role in sorted(required_roles))
    return checked_result("evaluate_pressure_test", arguments, checks)


def evaluate_valve_test(arguments: dict[str, Any]) -> dict[str, Any]:
    grade = normalize_value(arguments.get("pipelineGrade"), "text")
    population = integer(arguments.get("lotSize"))
    tested = integer(arguments.get("testedCount"))
    if not grade or population is None or tested is None:
        return insufficient("evaluate_valve_test", arguments, "valve_sampling_facts_missing")
    if arguments.get("factoryWitnessExemption") is True:
        exemption_checks = [
            check("factory_test_each_valve", arguments.get("factoryTestedEach") is True, arguments.get("factoryTestedEach"), True),
            check("owner_approved_exemption", arguments.get("ownerApprovedExemption") is True, arguments.get("ownerApprovedExemption"), True),
            check("factory_records_traceable", arguments.get("factoryRecordsTraceable") is True, arguments.get("factoryRecordsTraceable"), True),
        ]
        return checked_result("evaluate_valve_test", arguments, exemption_checks, "valve-test-gbt20801-v1")
    ratios = {"gc1": Decimal("1"), "gc2": Decimal("0.10"), "gc3": Decimal("0.05")}
    ratio = ratios.get(grade)
    if ratio is None:
        return insufficient("evaluate_valve_test", arguments, "unsupported_pipeline_grade")
    sampling = check_sampling_requirement({"populationCount": population, "sampledCount": tested, "requiredRatio": ratio, "minimumCount": 1})
    checks = list(sampling.get("checks") or [])
    required_records = ["testProcedure", "testPressure", "holdMinutes", "testResult", "standardRef"]
    checks.extend(check(f"valve_{safe_code(path)}", is_present(arguments.get(path)), arguments.get(path), "present") for path in required_records)
    accepted = normalize_value(arguments.get("testResult"), "text") in {"passed", "qualified", "合格", "无泄漏", "no_leak"}
    checks.append(check("valve_test_result_accepted", accepted, arguments.get("testResult"), "accepted"))
    return checked_result("evaluate_valve_test", arguments, checks, "valve-test-gbt20801-v1")


def evaluate_rule_profile(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if arguments.get("applicable") is False:
        return result(tool_name, "not_applicable", facts=arguments, checks=[], rule_version=rule_version(arguments))
    if arguments.get("applicable") not in {None, True, False}:
        return insufficient(tool_name, arguments, "applicability_not_boolean")
    facts = fact_container(arguments)
    required_fields = string_list(arguments.get("requiredFields"))
    rule_checks = list_of_dicts(arguments.get("ruleChecks"))
    if not required_fields:
        return insufficient(tool_name, arguments, "requiredFields_not_configured")
    if not rule_checks:
        return insufficient(tool_name, arguments, "ruleChecks_not_configured")
    checks = [check(f"required_{safe_code(path)}", is_present(read_path(facts, path)), read_path(facts, path), "present") for path in required_fields]
    for index, spec in enumerate(rule_checks, 1):
        evaluated = evaluate_rule_check(spec)
        if evaluated is None:
            return insufficient(tool_name, arguments, f"unsupported_rule_check_{index}")
        checks.append(evaluated)
    return checked_result(tool_name, facts, checks, rule_version(arguments))


def evaluate_rule_check(spec: dict[str, Any]) -> dict[str, Any] | None:
    operator = str(spec.get("operator") or "").strip()
    actual = spec.get("actual")
    expected = spec.get("expected")
    if operator == "present":
        passed = is_present(actual)
    elif operator == "equals":
        passed = normalize_value(actual, str(spec.get("normalizer") or "text")) == normalize_value(expected, str(spec.get("normalizer") or "text"))
    elif operator in {"gte", "lte", "gt", "lt"}:
        left, right = decimal(actual), decimal(expected)
        if left is None or right is None:
            passed = False
        else:
            passed = {"gte": left >= right, "lte": left <= right, "gt": left > right, "lt": left < right}[operator]
    elif operator == "contains_all":
        passed = normalized_set(actual) >= normalized_set(expected)
    elif operator == "accepted":
        passed = normalize_value(actual, "text") in normalized_set(expected or ["passed", "qualified", "合格"])
    else:
        return None
    return check(str(spec.get("code") or "rule_check"), passed, actual, expected)


def checked_result(tool_name: str, facts: Any, checks: list[dict[str, Any]], version: str | None = None) -> dict[str, Any]:
    if not checks:
        return insufficient(tool_name, facts, "checks_empty")
    failures = [item for item in checks if not item.get("passed")]
    if not failures:
        return result(tool_name, "passed", facts={"input": facts}, checks=checks, rule_version=version or rule_version(dict_value(facts)))
    # 全部失败项均为「字段缺失」时按证据不足处理；存在实质不合规（有值但不满足）才判 failed。
    if all(item.get("missing") for item in failures):
        output = result(
            tool_name,
            "evidence_insufficient",
            facts={"input": facts},
            checks=checks,
            rule_version=version or rule_version(dict_value(facts)),
        )
        output["warnings"] = ["required_facts_missing:" + ",".join(str(item.get("code")) for item in failures)]
        return output
    return result(tool_name, "failed", facts={"input": facts}, checks=checks, rule_version=version or rule_version(dict_value(facts)))


def insufficient(tool_name: str, arguments: Any, reason: str) -> dict[str, Any]:
    output = result(tool_name, "evidence_insufficient", facts={"input": arguments, "reason": reason}, checks=[], rule_version=rule_version(dict_value(arguments)))
    output["warnings"] = [reason]
    return output


def rule_version(arguments: dict[str, Any]) -> str:
    return str(arguments.get("ruleVersion") or arguments.get("profile") or "business-rule-profile-v1")


def fact_container(arguments: dict[str, Any]) -> dict[str, Any]:
    return arguments.get("facts") if isinstance(arguments.get("facts"), dict) else arguments


def read_path(value: dict[str, Any], path: str) -> Any:
    current: Any = value
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def is_present(value: Any) -> bool:
    if value is None or value == "":
        return False
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return True


def string_list(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple, set)):
        return []
    return [str(item) for item in value if item not in {None, ""}]


def unique_normalized(value: Any) -> list[str]:
    output: list[str] = []
    for item in string_list(value):
        normalized = normalize_value(item, "text")
        if normalized and normalized not in output:
            output.append(normalized)
    return output


def unique_upper(value: Any) -> list[str]:
    output: list[str] = []
    for item in string_list(value):
        normalized = str(item).strip().upper()
        if normalized and normalized not in output:
            output.append(normalized)
    return output


def list_of_dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def dict_value(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def normalized_set(value: Any) -> set[str]:
    values = value if isinstance(value, (list, tuple, set)) else []
    return {normalize_value(item, "text") for item in values if item not in {None, ""}}


def integer(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def ceiling(value: Decimal) -> int:
    return int(value.to_integral_value(rounding="ROUND_CEILING"))


def safe_code(value: Any) -> str:
    text = normalize_value(value, "text")
    return "".join(character if character.isalnum() else "_" for character in text).strip("_") or "item"


def _license_no(value: Any) -> str:
    return "".join(character for character in str(value or "").upper() if character.isalnum())


def _organization(value: Any) -> str:
    normalized = normalize_value(value, "organization_name")
    for suffix in ("有限责任公司", "股份有限公司", "有限公司"):
        if normalized.endswith(suffix):
            normalized = normalized[: -len(suffix)]
            break
    return normalized


def _component_scope_category(component_type: str) -> str | None:
    normalized = normalize_value(component_type, "text")
    if not normalized:
        return None
    if any(token in normalized for token in ("安全阀", "爆破片", "紧急切断阀", "安全附件")):
        return "safety_accessory"
    if "阀" in normalized:
        return "valve"
    if "法兰" in normalized:
        return "forged_flange"
    if any(token in normalized for token in ("无缝钢管", "无缝管")):
        return "seamless_steel_pipe"
    if any(token in normalized for token in ("焊接钢管", "焊管", "螺旋焊管", "直缝钢管")):
        return "welded_steel_pipe"
    if any(token in normalized for token in ("弯头", "三通", "四通", "异径", "管帽", "管件", "接头")):
        return "welded_pipe_fitting" if "焊" in normalized else "pipe_fitting"
    return None


def _scope_covers_component(scope: str, required_scope: str) -> bool:
    normalized = normalize_value(scope, "text")
    aliases = {
        "seamless_steel_pipe": ("无缝钢管", "无缝管"),
        "welded_steel_pipe": ("焊接钢管", "焊管", "螺旋缝埋弧焊钢管", "直缝埋弧焊钢管"),
        "pipe_fitting": ("管件制造", "非焊接管件", "锻制管件", "无缝管件"),
        "welded_pipe_fitting": ("焊接管件", "有缝管件"),
        "forged_flange": ("锻制法兰", "法兰制造", "钢制锻造法兰"),
        "valve": ("阀门制造", "压力管道阀门"),
        "safety_accessory": ("安全附件制造", "安全阀制造", "爆破片装置", "紧急切断阀"),
    }
    return any(alias in normalized for alias in aliases.get(required_scope, ()))


def date_coverage_checks(arguments: dict[str, Any]) -> list[dict[str, Any]] | None:
    valid_from = parse_date(arguments.get("validFrom"))
    valid_until = parse_date(arguments.get("validUntil"))
    period_start = parse_date(arguments.get("periodStart"))
    planned_end = parse_date(arguments.get("plannedPeriodEnd") or arguments.get("periodEnd"))
    actual_end = parse_date(arguments.get("actualPeriodEnd"))
    if valid_until is None or period_start is None or planned_end is None:
        return None
    period_end = max(item for item in (planned_end, actual_end) if item is not None)
    return [
        check("valid_from_covers_period_start", valid_from is None or valid_from <= period_start, valid_from, period_start),
        check("valid_until_covers_later_construction_end", valid_until >= period_end, valid_until, period_end),
    ]


def person_is_current(person: dict[str, Any], work_date: Any) -> bool:
    date = parse_date(work_date)
    valid_until = parse_date(person.get("validUntil"))
    registered = person.get("registered")
    return date is not None and valid_until is not None and valid_until >= date and registered is True


def coverage_item_matches(qualification: dict[str, Any], work: dict[str, Any]) -> bool:
    for field in ("method", "materialCategory", "position", "fillerMetal"):
        expected = work.get(field)
        if expected not in {None, ""} and normalize_value(qualification.get(field), "text") != normalize_value(expected, "text"):
            return False
    thickness = decimal(work.get("thickness"))
    diameter = decimal(work.get("diameter"))
    if thickness is None or diameter is None:
        return False
    thickness_min, thickness_max = decimal(qualification.get("thicknessMin")), decimal(qualification.get("thicknessMax"))
    diameter_min, diameter_max = decimal(qualification.get("diameterMin")), decimal(qualification.get("diameterMax"))
    if None in {thickness_min, thickness_max, diameter_min}:
        return False
    return thickness_min <= thickness <= thickness_max and diameter >= diameter_min and (diameter_max is None or diameter <= diameter_max)
