"""按规则包里冻结的判据逐域核对——这些规则共用的一套判定语义。

为什么要抽出来：2026-09-10 的逐条核查发现，23 条规则的 27 个原子项虽然绑定里写着
专用工具名，实际都落到通用解释器，而通用解释器要求的 ruleChecks **全仓没有任何地方
产生**。缺的不是配置，是产生配置的机制。

R09 的 designSpecialRequirementRules 与 R11 的 constructionPlanProcessRules 是唯二
走通的样板：判据冻结进规则包，事实侧按 actualPath 解析，工具自己不推导限值。
这个模块把那套语义抽成可复用的一份，后续规则接入只需要三件事——
规则包里冻结判据、事实侧组装 domains、绑定指向一个薄封装。

四种结果的边界（各规则一致，不允许各自解释）：
- 该写没写（requiredPaths 缺项、或整个领域缺席）→ **不符合**。资料本来就该有这一项，
  算成缺证据等于替被审查方开脱。
- 写了但不满足判据 → 不符合。
- 适用性判不了（applicabilityPath 既不是 True 也不是 False）→ 证据不足，不按不适用放过。
- 明确不适用 → 不适用。
另外：派生布尔取不到值时保持未决，不当成 False 也不当成 True；证据不是所选版本、
对象含糊、领域重复或未知，一律证据不足，不挑第一行。
"""
from __future__ import annotations

from copy import deepcopy

from libs.review_orchestrator.deterministic_tools import check, result
from libs.review_tools.r39_tools import _refs, _text


def evaluate_frozen_domains(tool_name, arguments, *, rule_version, scope_fields, version_field, code_prefix):
    """`arguments` 需带 projectId、scope、standardRules（冻结判据）、domains（事实）。"""
    # business_tools 会导入登记本模块的工具，模块级互相导入会成环，这里延迟取。
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
        facts = {"processChecks": rows, "scope": "selected_object_only",
                 "wholeRuleAcceptance": "not_evaluated",
                 "selectionIssues": deepcopy(arguments.get("selectionIssues") or [])}
        facts.update(extra_facts or {})
        output = result(tool_name, status, facts=facts,
                        checks=[check(row["code"], row["result"] == "passed", row["result"], "passed") for row in rows],
                        rule_version=rule_version)
        output["evidenceRefs"] = [ref for row in rows for ref in row["evidenceRefs"]]
        return output

    scope = arguments.get("scope")
    if (not isinstance(scope, dict) or any(not _text(scope.get(key)) for key in scope_fields)
            or scope["projectId"] != arguments.get("projectId")):
        add(f"{code_prefix}_scope_missing", "evidence_insufficient")
        return finish()

    frozen = arguments.get("standardRules")
    domains_spec = (frozen or {}).get("domains") if isinstance(frozen, dict) else None
    if not isinstance(domains_spec, dict) or not domains_spec:
        add(f"{code_prefix}_standard_rules_missing", "evidence_insufficient")
        return finish()

    supplied = arguments.get("domains")
    if not isinstance(supplied, list) or not supplied:
        add(f"{code_prefix}_domains_missing", "evidence_insufficient")
        return finish()

    seen: set[str] = set()
    by_domain: dict[str, dict] = {}
    for row in supplied:
        name = row.get("domain") if isinstance(row, dict) else None
        if (not _text(name) or name in seen or not isinstance(row, dict)
                or any(row.get(key) != scope[key] for key in scope_fields)):
            add(f"{code_prefix}_domain_conflict", "evidence_insufficient")
            return finish()
        seen.add(name)
        by_domain[name] = row
    unknown = sorted(seen - set(domains_spec))
    if unknown:
        add(f"{code_prefix}_unknown_domain", "evidence_insufficient", actual=unknown, expected=sorted(domains_spec))
        return finish()

    evaluated_domains = []
    for domain_name, spec in domains_spec.items():
        row = by_domain.get(domain_name)
        prefix = safe_code(domain_name)
        if row is None:
            add(f"{prefix}_domain_missing", "failed", expected="covered_by_document")
            continue
        refs = _refs(row)
        if not refs or any(ref.get("documentVersionId") != scope[version_field] for ref in refs):
            add(f"{prefix}_evidence_not_from_selected_document", "evidence_insufficient", refs)
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


def frozen_rules_for_rule(rule_id: str, key: str, run=None):
    """从规则包里取某条规则冻结的判据块；取不到返回空字典，让工具报"判据缺失"。"""
    from libs.business_pack.loader import DEFAULT_BUSINESS_PACK_ID, load_business_pack

    pack = load_business_pack(str((run or {}).get("businessPackId") or DEFAULT_BUSINESS_PACK_ID))
    for package in pack.get("standardClausePackages") or []:
        if isinstance(package, dict) and str(package.get("sourceRuleId") or "") == rule_id:
            rules = package.get(key)
            return deepcopy(rules) if isinstance(rules, dict) else {}
    return {}
