"""R47／R48／R50／R53／R54／R55 的事实构建：显式对象、来源不可含糊。

沿用 R11／R45／泄漏试验／R63／R68 的口径：同一 scope 出现多行就是来源含糊，
不挑第一行；判据取不到就把 standardRules 留空，让工具报"判据缺失"，不在这里编。
"""
from copy import deepcopy

from libs.review_orchestrator.ndt_table_facts import read_ndt_tables
from libs.review_orchestrator.source_coverage import selected_source_issues
from libs.review_tools.installation_domain_rules import SCOPE_FIELDS, frozen_installation_rules

_NODES = {
    101: ("r10_standard_adoption_domains", "alternativeStandardAdoption", "evaluate_r10_standard_adoption", "r10"),
    103: ("r10_compliance_declaration_domains", "complianceDeclaration", "evaluate_r10_compliance_declaration", "r10"),
    102: ("r10_comparison_table_domains", "comparisonTableCoverage", "evaluate_r10_comparison_table", "r10"),
    561: ("r56_accessory_documents_domains", "safetyAccessoryDocuments", "evaluate_r56_accessory_documents", "r56"),
    562: ("r56_accessory_installation_domains", "safetyAccessoryInstallation", "evaluate_r56_accessory_installation", "r56"),
    57: ("r57_safety_valve_calibration_domains", "safetyValveCalibration", "evaluate_r57_safety_valve_calibration", "r57"),
    58: ("r58_emergency_valve_test_domains", "emergencyValveTest", "evaluate_r58_emergency_valve_test", "r58"),
    43: ("material_certificate_domains", "materialCertificate", "evaluate_r43_material_certificate", "r43"),
    44: ("coating_construction_domains", "coatingConstruction", "evaluate_r44_coating_construction", "r44"),
    46: ("cathodic_protection_domains", "cathodicProtection", "evaluate_r46_cathodic_protection", "r46"),
    47: ("static_grounding_domains", "staticGrounding", "evaluate_r47_static_grounding", "r47"),
    48: ("weld_layout_domains", "weldLayout", "evaluate_r48_weld_layout", "r48"),
    49: ("crossing_construction_domains", "crossingConstruction", "evaluate_r49_crossing_construction", "r49"),
    50: ("sleeve_insulation_domains", "sleeveInsulation", "evaluate_r50_sleeve_insulation", "r50"),
    53: ("installation_connection_domains", "installationConnections", "evaluate_r53_installation_connections", "r53"),
    52: ("prefabrication_domains", "prefabrication", "evaluate_r52_prefabrication", "r52"),
    530: ("equipment_connection_domains", "equipmentConnection", "evaluate_r53_equipment_connection", "r53"),
    54: ("compensator_domains", "compensator", "evaluate_r54_compensator", "r54"),
    55: ("support_domains", "supports", "evaluate_r55_supports", "r55"),
}


def _build(node_id, state, run):
    table_name, fact_key, tool_name, namespace = _NODES[node_id]
    issues = selected_source_issues(state, run, node_id=node_id)
    rows = read_ndt_tables(state, run, {table_name: "domains"}, node_id=node_id)["domains"]
    scope = None
    domains = []
    for row in rows:
        key = {field: row.get(field) for field in SCOPE_FIELDS}
        if scope is None:
            scope = key
        elif key != scope:
            return {namespace: {fact_key: {"projectId": run["projectId"], "scope": None, "standardRules": {},
                                           "domains": [], "selectionIssues": deepcopy(issues),
                                           "sourceIssues": [f"{namespace}_source_object_conflict"]}}}
        domains.append(deepcopy(row))
    return {namespace: {fact_key: {"projectId": run["projectId"], "scope": deepcopy(scope), "domains": domains,
                                   "standardRules": frozen_installation_rules(tool_name, run),
                                   "selectionIssues": deepcopy(issues)}}}


def build_r10_business_facts(state, run):
    """节点 10 有三个原子项：采用标准识别、申明与比照表存在、比照表覆盖。

    登记本按节点取一个构建器，三份事实在这里合并输出，各读各的资料表；
    一份来源含糊不牵连另一份。
    """
    facts = _build(101, state, run)
    for node_id in (102, 103):
        facts["r10"].update(_build(node_id, state, run)["r10"])
    return facts


def build_r56_business_facts(state, run):
    """节点 56 有两个原子项：证明文件审查与现场选用安装核对。

    登记本按节点取一个构建器，两份事实在这里合并输出，各读各的资料表；
    一份来源含糊不牵连另一份。
    """
    facts = _build(561, state, run)
    facts["r56"].update(_build(562, state, run)["r56"])
    return facts


def build_r57_business_facts(state, run):
    return _build(57, state, run)


def build_r58_business_facts(state, run):
    return _build(58, state, run)


def build_r43_business_facts(state, run):
    return _build(43, state, run)


def build_r44_business_facts(state, run):
    return _build(44, state, run)


def build_r46_business_facts(state, run):
    return _build(46, state, run)


def build_r47_business_facts(state, run):
    return _build(47, state, run)


def build_r48_business_facts(state, run):
    return _build(48, state, run)


def build_r49_business_facts(state, run):
    return _build(49, state, run)


def build_r50_business_facts(state, run):
    return _build(50, state, run)


def build_r52_business_facts(state, run):
    return _build(52, state, run)


def build_r53_business_facts(state, run):
    """节点 53 有两个原子项：AC-R53-01 布管与连接方式、AC-R53-02 连接设备的管道。

    登记本按节点取一个构建器，所以两份事实在这里合并输出，各自读自己的资料表；
    一份来源含糊不牵连另一份。
    """
    facts = _build(53, state, run)
    equipment = _build(530, state, run)
    facts["r53"].update(equipment["r53"])
    return facts


def build_r54_business_facts(state, run):
    return _build(54, state, run)


def build_r55_business_facts(state, run):
    return _build(55, state, run)
