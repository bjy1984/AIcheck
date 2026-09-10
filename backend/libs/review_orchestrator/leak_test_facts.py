"""R64／R66／R67 泄漏试验的事实构建：显式对象、来源不可含糊。

沿用 R11／R45 的口径：同一 scope 出现多行就是来源含糊，不挑第一行；
判据取不到就把 standardRules 留空，让工具报"判据缺失"，不在这里编。
"""
from copy import deepcopy

from libs.review_orchestrator.ndt_table_facts import read_ndt_tables
from libs.review_orchestrator.source_coverage import selected_source_issues
from libs.review_tools.leak_test_rules import SCOPE_FIELDS, frozen_leak_rules

_NODES = {
    64: ("leak_alternative_test_domains", "alternativeTest", "evaluate_r64_alternative_test", "r64"),
    66: ("leak_test_condition_domains", "leakTestConditions", "evaluate_r66_leak_test_conditions", "r66"),
    67: ("leak_test_method_domains", "leakTestMethod", "evaluate_r67_leak_test_method", "r67"),
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
                                   "standardRules": frozen_leak_rules(tool_name, run),
                                   "selectionIssues": deepcopy(issues)}}}


def build_r64_business_facts(state, run):
    return _build(64, state, run)


def build_r66_business_facts(state, run):
    return _build(66, state, run)


def build_r67_business_facts(state, run):
    return _build(67, state, run)
