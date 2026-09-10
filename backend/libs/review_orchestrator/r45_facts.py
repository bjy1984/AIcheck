"""R45 防腐层电火花检测：显式对象、来源不可含糊，判据只从规则包冻结值来。

沿用 R11 的口径：同一 scope 出现多行就是来源含糊，不挑第一行；判据取不到就把
standardRules 留空，让工具报"判据缺失"，不在这里编。
"""
from copy import deepcopy

from libs.review_orchestrator.ndt_table_facts import read_ndt_tables
from libs.review_orchestrator.source_coverage import selected_source_issues
from libs.review_tools.r45_holiday_test import SCOPE_FIELDS, frozen_holiday_test_rules

TABLES = {"coating_holiday_test_domains": "holidayDomains"}


def build_r45_business_facts(state, run):
    issues = selected_source_issues(state, run, node_id=45)
    rows = read_ndt_tables(state, run, TABLES, node_id=45)["holidayDomains"]
    scope = None
    domains = []
    for row in rows:
        key = {field: row.get(field) for field in SCOPE_FIELDS}
        if scope is None:
            scope = key
        elif key != scope:
            return {"r45": {"holidayTest": {"projectId": run["projectId"], "scope": None, "standardRules": {},
                                            "domains": [], "selectionIssues": deepcopy(issues),
                                            "sourceIssues": ["r45_source_object_conflict"]}}}
        domains.append(deepcopy(row))
    return {"r45": {"holidayTest": {"projectId": run["projectId"], "scope": deepcopy(scope), "domains": domains,
                                    "standardRules": frozen_holiday_test_rules(run),
                                    "selectionIssues": deepcopy(issues)}}}
