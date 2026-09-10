"""R47／R48／R50／R53／R54／R55：安装与布置类规则的专用判定。

这六条原先分别绑 evaluate_static_grounding、evaluate_crossing_structure、
evaluate_corrosion_protection、evaluate_pipe_installation、evaluate_compensator、
evaluate_support_components——这些名字在 business_tools 里都没有实现，落到通用
解释器且 ruleChecks 无人产生，资料再齐也只返回"未配置"的证据不足。

判据取自各自规则包冻结的块，除 R49 外全部来自 GB/T 20801.1-2025 已逐句核对的正文，
R49 来自 GB 50235-2010 扫描件经 MinerU OCR 重建后逐句核对的正文；判定
语义共用 frozen_domain_checks.evaluate_frozen_domains，四种结果的边界在那个模块
里统一定义。

这批里数值判据比前两批多（跨接电阻 0.03Ω、对地电阻 100Ω／1000Ω、焊缝间距
150 mm／50 mm、法兰平行度 1 mm/200 mm、螺栓孔偏移 3 mm、全焊透抽检 20%／200 mm），
全部是条文明列的值，直接比较；凡是依赖壁厚、焊缝宽度、孔径这类需要换算的，
一律由事实侧给出布尔，工具不代算——写在各规则的 sourceReview.limitations 里。
"""
from __future__ import annotations

from libs.review_tools.frozen_domain_checks import evaluate_frozen_domains, frozen_rules_for_rule

SCOPE_FIELDS = ("projectId", "objectType", "objectId", "recordVersionId")

_SPECS = {
    "evaluate_r10_standard_adoption": ("R10", "alternativeStandardAdoptionRules", "r10-standard-adoption-v1", "r10_adoption"),
    "evaluate_r10_compliance_declaration": ("R10", "complianceDeclarationRules", "r10-compliance-declaration-v1", "r10_declaration"),
    "evaluate_r10_comparison_table": ("R10", "comparisonTableCoverageRules", "r10-comparison-table-v1", "r10_table"),
    "evaluate_r56_accessory_documents": ("R56", "safetyAccessoryDocumentRules", "r56-accessory-documents-v1", "r56_documents"),
    "evaluate_r56_accessory_installation": ("R56", "safetyAccessoryInstallationRules", "r56-accessory-installation-v1", "r56_installation"),
    "evaluate_r57_safety_valve_calibration": ("R57", "safetyValveCalibrationRules", "r57-safety-valve-calibration-v1", "r57_calibration"),
    "evaluate_r58_emergency_valve_test": ("R58", "emergencyValveTestRules", "r58-emergency-valve-test-v1", "r58_emergency"),
    "evaluate_r43_material_certificate": ("R43", "materialCertificateRules", "r43-material-certificate-v1", "r43_certificate"),
    "evaluate_r44_coating_construction": ("R44", "coatingConstructionRules", "r44-coating-construction-v1", "r44_coating"),
    "evaluate_r46_cathodic_protection": ("R46", "cathodicProtectionRules", "r46-cathodic-protection-v1", "r46_cathodic"),
    "evaluate_r47_static_grounding": ("R47", "staticGroundingRules", "r47-static-grounding-v1", "r47_grounding"),
    "evaluate_r48_weld_layout": ("R48", "weldLayoutRules", "r48-weld-layout-v1", "r48_weld_layout"),
    "evaluate_r49_crossing_construction": ("R49", "crossingConstructionRules", "r49-crossing-construction-v1", "r49_crossing"),
    "evaluate_r50_sleeve_insulation": ("R50", "sleeveInsulationRules", "r50-sleeve-insulation-v1", "r50_sleeve"),
    "evaluate_r53_installation_connections": ("R53", "installationConnectionRules", "r53-installation-connections-v1", "r53_installation"),
    "evaluate_r54_compensator": ("R54", "compensatorRules", "r54-compensator-v1", "r54_compensator"),
    "evaluate_r52_prefabrication": ("R52", "prefabricationRules", "r52-prefabrication-v1", "r52_prefab"),
    "evaluate_r53_equipment_connection": ("R53", "equipmentConnectionRules", "r53-equipment-connection-v1", "r53_equipment"),
    "evaluate_r55_supports": ("R55", "supportRules", "r55-supports-v1", "r55_support"),
}


def _run(tool_name, arguments):
    _rule_id, _key, rule_version, prefix = _SPECS[tool_name]
    return evaluate_frozen_domains(tool_name, arguments, rule_version=rule_version,
                                   scope_fields=SCOPE_FIELDS, version_field="recordVersionId",
                                   code_prefix=prefix)


def evaluate_r10_standard_adoption(arguments):
    return _run("evaluate_r10_standard_adoption", arguments)


def evaluate_r10_compliance_declaration(arguments):
    return _run("evaluate_r10_compliance_declaration", arguments)


def evaluate_r10_comparison_table(arguments):
    return _run("evaluate_r10_comparison_table", arguments)


def evaluate_r56_accessory_documents(arguments):
    return _run("evaluate_r56_accessory_documents", arguments)


def evaluate_r56_accessory_installation(arguments):
    return _run("evaluate_r56_accessory_installation", arguments)


def evaluate_r57_safety_valve_calibration(arguments):
    return _run("evaluate_r57_safety_valve_calibration", arguments)


def evaluate_r58_emergency_valve_test(arguments):
    return _run("evaluate_r58_emergency_valve_test", arguments)


def evaluate_r43_material_certificate(arguments):
    return _run("evaluate_r43_material_certificate", arguments)


def evaluate_r44_coating_construction(arguments):
    return _run("evaluate_r44_coating_construction", arguments)


def evaluate_r46_cathodic_protection(arguments):
    return _run("evaluate_r46_cathodic_protection", arguments)


def evaluate_r47_static_grounding(arguments):
    return _run("evaluate_r47_static_grounding", arguments)


def evaluate_r48_weld_layout(arguments):
    return _run("evaluate_r48_weld_layout", arguments)


def evaluate_r49_crossing_construction(arguments):
    return _run("evaluate_r49_crossing_construction", arguments)


def evaluate_r50_sleeve_insulation(arguments):
    return _run("evaluate_r50_sleeve_insulation", arguments)


def evaluate_r53_installation_connections(arguments):
    return _run("evaluate_r53_installation_connections", arguments)


def evaluate_r52_prefabrication(arguments):
    return _run("evaluate_r52_prefabrication", arguments)


def evaluate_r53_equipment_connection(arguments):
    return _run("evaluate_r53_equipment_connection", arguments)


def evaluate_r54_compensator(arguments):
    return _run("evaluate_r54_compensator", arguments)


def evaluate_r55_supports(arguments):
    return _run("evaluate_r55_supports", arguments)


def frozen_installation_rules(tool_name, run=None):
    rule_id, key, _version, _prefix = _SPECS[tool_name]
    return frozen_rules_for_rule(rule_id, key, run)
