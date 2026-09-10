"""R63 柔性分析与 R68 吹扫清洗的事实构建：显式对象、来源不可含糊。

沿用 R11／R45／泄漏试验的口径：同一 scope 出现多行就是来源含糊，不挑第一行；
判据取不到就把 standardRules 留空，让工具报"判据缺失"，不在这里编。
"""
from copy import deepcopy

from libs.review_orchestrator.ndt_table_facts import read_ndt_tables
from libs.review_orchestrator.source_coverage import selected_source_issues
from libs.review_tools.r63_stress_analysis import (
    SCOPE_FIELDS as R63_SCOPE_FIELDS,
    frozen_stress_analysis_rules,
)
from libs.review_tools.r68_blowing_cleaning import (
    SCOPE_FIELDS as R68_SCOPE_FIELDS,
    frozen_blowing_cleaning_rules,
)

_NODES = {
    63: ("stress_analysis_domains", "stressAnalysis", "r63", R63_SCOPE_FIELDS, frozen_stress_analysis_rules),
    68: ("blowing_cleaning_domains", "blowingCleaning", "r68", R68_SCOPE_FIELDS, frozen_blowing_cleaning_rules),
}


def _build(node_id, state, run):
    table_name, fact_key, namespace, scope_fields, frozen_rules = _NODES[node_id]
    issues = selected_source_issues(state, run, node_id=node_id)
    rows = read_ndt_tables(state, run, {table_name: "domains"}, node_id=node_id)["domains"]
    scope = None
    domains = []
    for row in rows:
        key = {field: row.get(field) for field in scope_fields}
        if scope is None:
            scope = key
        elif key != scope:
            return {namespace: {fact_key: {"projectId": run["projectId"], "scope": None, "standardRules": {},
                                           "domains": [], "selectionIssues": deepcopy(issues),
                                           "sourceIssues": [f"{namespace}_source_object_conflict"]}}}
        domains.append(deepcopy(row))
    return {namespace: {fact_key: {"projectId": run["projectId"], "scope": deepcopy(scope), "domains": domains,
                                   "standardRules": frozen_rules(run),
                                   "selectionIssues": deepcopy(issues)}}}


def build_r63_business_facts(state, run):
    return _build(63, state, run)


def build_r68_business_facts(state, run):
    return _build(68, state, run)
