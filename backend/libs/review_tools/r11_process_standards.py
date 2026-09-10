"""R11-03：施工方案里的焊接、试验内容是否满足施工标准要求。

原先 AC-R11-03 只绑通用的 evaluate_construction_plan，等于没有专用判定。这里按 R11
既有的口径补上：显式对象、来源不可含糊、判据取自规则包里冻结的
`constructionPlanProcessRules`——工具自己不推导限值，也不猜适用性。

与 R09 的关系：R09 问"设计文件有没有写、写得够不够"，这里问"施工方案有没有把它落下来"。
数值判据同源（同一批冻结值），所以复用 business_tools 的 evaluate_rule_check 与 read_path，
不另写一套比较语义。

四种结果的边界：
- 该写没写（requiredPaths 缺项）→ 不符合，不是证据不足。方案本来就该写。
- 写了但低于标准 → 不符合。
- 适用性判不了（applicabilityPath 既不是 True 也不是 False）→ 证据不足，不按不适用放过。
- 明确不适用 → 不适用。
"""
from __future__ import annotations

from copy import deepcopy

from libs.review_orchestrator.deterministic_tools import check, result
from libs.review_tools.r39_tools import _refs, _text

RULE_VERSION = "r11-construction-plan-process-standards-v1"
SCOPE_FIELDS = ("projectId", "objectType", "objectId", "planVersionId")


def evaluate_r11_process_standards(arguments):
    # business_tools 会导入本模块登记工具，模块级互相导入会成环，这里延迟取。
    from libs.review_tools.business_tools import (
        evaluate_rule_check,
        is_present,
        read_path,
        safe_code,
    )

    rows: list[dict] = []

    def add(code, status, refs=(), *, actual=None, expected=None):
        rows.append({"code": code, "result": status, "actual": actual, "expected": expected,
                     "evidenceRefs": deepcopy(list(refs))})

    def finish(extra_facts=None):
        statuses = {row["result"] for row in rows}
        if "failed" in statuses:
            status = "failed"
        elif "evidence_insufficient" in statuses:
            status = "evidence_insufficient"
        elif statuses == {"not_applicable"}:
            status = "not_applicable"
        elif not statuses:
            status = "evidence_insufficient"
        else:
            status = "passed"
        if arguments.get("selectionIssues") and status in {"passed", "not_applicable"}:
            status = "evidence_insufficient"
        facts = {"processChecks": rows, "scope": "selected_plan_object_only",
                 "wholeRuleAcceptance": "not_evaluated",
                 "selectionIssues": deepcopy(arguments.get("selectionIssues") or [])}
        facts.update(extra_facts or {})
        output = result("evaluate_r11_process_standards", status, facts=facts,
                        checks=[check(row["code"], row["result"] == "passed", row["result"], "passed") for row in rows],
                        rule_version=RULE_VERSION)
        output["evidenceRefs"] = [ref for row in rows for ref in row["evidenceRefs"]]
        return output

    scope = arguments.get("scope")
    if (not isinstance(scope, dict) or any(not _text(scope.get(key)) for key in SCOPE_FIELDS)
            or scope["projectId"] != arguments.get("projectId")):
        add("r11_process_scope_missing", "evidence_insufficient")
        return finish()

    frozen = arguments.get("standardRules")
    domains_spec = (frozen or {}).get("domains") if isinstance(frozen, dict) else None
    if not isinstance(domains_spec, dict) or not domains_spec:
        add("r11_process_standard_rules_missing", "evidence_insufficient")
        return finish()

    supplied = arguments.get("domains")
    if not isinstance(supplied, list) or not supplied:
        add("r11_process_plan_domains_missing", "evidence_insufficient")
        return finish()

    seen: set[str] = set()
    by_domain: dict[str, dict] = {}
    for row in supplied:
        name = row.get("domain") if isinstance(row, dict) else None
        if (not _text(name) or name in seen or not isinstance(row, dict)
                or any(row.get(key) != scope[key] for key in SCOPE_FIELDS)):
            add("r11_process_domain_conflict", "evidence_insufficient")
            return finish()
        seen.add(name)
        by_domain[name] = row
    unknown = sorted(seen - set(domains_spec))
    if unknown:
        add("r11_process_unknown_domain", "evidence_insufficient", actual=unknown, expected=sorted(domains_spec))
        return finish()

    evaluated_domains = []
    for domain_name, spec in domains_spec.items():
        row = by_domain.get(domain_name)
        prefix = safe_code(domain_name)
        if row is None:
            # 冻结规则要求覆盖这个领域，方案里没有它——该写没写。
            add(f"{prefix}_domain_missing", "failed", expected="covered_by_plan")
            continue
        refs = _refs(row)
        if not refs or any(ref.get("documentVersionId") != scope["planVersionId"] for ref in refs):
            add(f"{prefix}_evidence_not_from_selected_plan", "evidence_insufficient", refs)
            continue
        applicable = row.get("applicable")
        if applicable is False:
            add(f"{prefix}_not_applicable", "not_applicable", refs)
            continue
        if applicable is not True:
            add(f"{prefix}_applicability_unknown", "evidence_insufficient", refs, actual=applicable)
            continue
        evaluated_domains.append(domain_name)
        for path in spec.get("requiredPaths") or []:
            actual = read_path(row, path)
            add(f"{prefix}_{safe_code(path)}", "passed" if is_present(actual) else "failed",
                refs, actual=actual, expected="specified")
        for index, rule in enumerate(spec.get("checks") or [], 1):
            code = f"{prefix}_{safe_code(rule.get('code') or index)}"
            actual_path = str(rule.get("actualPath") or "").strip()
            if not actual_path or not _text(rule.get("standardRef")) or not _text(rule.get("operator")):
                add(f"{code}_rule_invalid", "evidence_insufficient")
                continue
            if "applicabilityPath" in rule:
                flag = read_path(row, str(rule["applicabilityPath"]))
                if flag is False:
                    add(code, "not_applicable", refs)
                    continue
                if flag is not True:
                    add(code, "evidence_insufficient", refs, actual=flag, expected="known_applicability")
                    continue
            actual = read_path(row, actual_path)
            # 派生布尔判据（比例是否达标、验收级别是否达标）取不到值时不能当成 False。
            if rule.get("operator") == "equals" and isinstance(rule.get("expected"), bool) and actual is None:
                add(code, "evidence_insufficient", refs, expected=rule.get("expected"))
                continue
            evaluated = evaluate_rule_check({**rule, "actual": actual, "code": code})
            if evaluated is None:
                add(f"{code}_operator_unsupported", "evidence_insufficient", refs)
                continue
            add(code, "passed" if evaluated.get("passed") else "failed", refs,
                actual=actual, expected=rule.get("expected", "meets_standard"))

    return finish({"evaluatedDomains": evaluated_domains,
                   "standardReview": deepcopy((frozen or {}).get("sourceReview") or {})})
