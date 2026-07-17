from __future__ import annotations

import re
from typing import Any

from libs.review_orchestrator.deterministic_tools import check, decimal, result
from libs.review_tools.material_standard_profiles import resolve_material_standard_profile


R18_RULE_VERSION = "r18-material-retest-and-ndt-tsg-d7006-2020-v1"
_PASS = {"accepted", "approved", "qualified", "passed", "符合", "合格", "通过"}


def classify_r18_material_test_applicability(arguments: dict[str, Any]) -> dict[str, Any]:
    items = _records(arguments.get("designItems"))
    if not items:
        return _insufficient("classify_r18_material_test_applicability", "r18_design_items_missing")
    matrix, checks = [], []
    incomplete = applicable = 0
    for index, item in enumerate(items, 1):
        retest = _truth(_first(item, "requiresMaterialRetest", "materialRetestRequired"))
        ndt = _truth(_first(item, "requiresMaterialNdt", "materialNdtRequired"))
        reasons = _string_list(item.get("materialTestTriggerReasons"))
        known = isinstance(retest, bool) and isinstance(ndt, bool)
        if not known:
            incomplete += 1
        if retest or ndt:
            applicable += 1
        checks.append(check(f"component_{index}_material_test_applicability_known", known, {"retest": retest, "ndt": ndt, "triggerReasons": reasons}, "explicit_boolean_requirements_and_trigger_reasons"))
        matrix.append({"componentItemId": _id(item, index), "materialRetestRequired": retest, "materialNdtRequired": ndt, "triggerReasons": reasons, "result": "passed" if known else "evidence_insufficient"})
    business_result = "evidence_insufficient" if incomplete else "passed" if applicable else "not_applicable"
    output = result("classify_r18_material_test_applicability", business_result, facts={"applicabilityMatrix": matrix, "applicableItemCount": applicable}, checks=checks, rule_version=R18_RULE_VERSION)
    output["applicabilityMatrix"] = matrix
    return output


def resolve_r18_material_test_requirement_profile(arguments: dict[str, Any]) -> dict[str, Any]:
    items = _records(arguments.get("designItems"))
    if not items:
        return _insufficient("resolve_r18_material_test_requirement_profile", "r18_design_items_missing")
    matrix, checks = [], []
    incomplete, applicable = False, 0
    for index, item in enumerate(items, 1):
        retest = _truth(_first(item, "requiresMaterialRetest", "materialRetestRequired"))
        ndt = _truth(_first(item, "requiresMaterialNdt", "materialNdtRequired"))
        if retest is False and ndt is False:
            matrix.append({"componentItemId": _id(item, index), "result": "not_applicable"})
            continue
        applicable += 1
        standard_profile = resolve_material_standard_profile(_first(item, "standardRef", "acceptanceStandard"))
        required_retest_items = _string_list(item.get("requiredRetestItems"))
        required_ndt_methods = _string_list(item.get("requiredMaterialNdtMethods"))
        acceptance_limits = _records(item.get("acceptanceLimits"))
        known = isinstance(retest, bool) and isinstance(ndt, bool) and standard_profile is not None
        if retest and not required_retest_items:
            known = False
        if ndt and not required_ndt_methods:
            known = False
        if (required_retest_items or required_ndt_methods) and not acceptance_limits and _truth(item.get("requiresNumericAcceptance")) is True:
            known = False
        incomplete |= not known
        checks.append(check(f"component_{index}_material_test_requirements_frozen", known, {"standardRef": _first(item, "standardRef", "acceptanceStandard"), "requiredRetestItems": required_retest_items, "requiredNdtMethods": required_ndt_methods, "acceptanceLimitCount": len(acceptance_limits)}, "standard_profile_and_explicit_test_requirements"))
        matrix.append({"componentItemId": _id(item, index), "standardProfile": standard_profile, "requiredRetestItems": required_retest_items, "requiredMaterialNdtMethods": required_ndt_methods, "acceptanceLimits": acceptance_limits, "result": "passed" if known else "evidence_insufficient"})
    business_result = "not_applicable" if not applicable else "evidence_insufficient" if incomplete else "passed"
    output = result("resolve_r18_material_test_requirement_profile", business_result, facts={"requirementMatrix": matrix}, checks=checks, rule_version=R18_RULE_VERSION)
    output["requirementMatrix"] = matrix
    return output


def evaluate_r18_material_retest_report_completeness(arguments: dict[str, Any]) -> dict[str, Any]:
    return _evaluate_report_completeness(arguments, report_kind="retest")


def evaluate_r18_material_ndt_report_completeness(arguments: dict[str, Any]) -> dict[str, Any]:
    return _evaluate_report_completeness(arguments, report_kind="ndt")


def evaluate_r18_material_report_approval_procedure(arguments: dict[str, Any]) -> dict[str, Any]:
    reports = [*_records(arguments.get("retestReports")), *_records(arguments.get("materialNdtReports"))]
    if not reports:
        items = _records(arguments.get("designItems"))
        if items and all(
            _truth(_first(item, "requiresMaterialRetest", "materialRetestRequired")) is False
            and _truth(_first(item, "requiresMaterialNdt", "materialNdtRequired")) is False
            for item in items
        ):
            return result("evaluate_r18_material_report_approval_procedure", "not_applicable", facts={"applicableReportCount": 0}, checks=[], rule_version=R18_RULE_VERSION)
        return _insufficient("evaluate_r18_material_report_approval_procedure", "applicable_material_reports_missing")
    matrix, checks = [], []
    failed = incomplete = False
    for index, report in enumerate(reports, 1):
        procedure_approved = _truth(_first(report, "procedureApproved", "approvalProcedureCompliant"))
        required_roles = _string_list(report.get("requiredSignatureRoles")) or ["tester", "reviewer", "approver"]
        actual_roles = {_norm(item) for item in _string_list(report.get("signatureRoles"))}
        missing_roles = [role for role in required_roles if not _approval_role_present(actual_roles, role)]
        if procedure_approved is False or missing_roles:
            failed = True
            status = "failed"
        elif procedure_approved is None:
            incomplete = True
            status = "evidence_insufficient"
        else:
            status = "passed"
        checks.extend([
            check(f"report_{index}_approval_procedure", procedure_approved is True, procedure_approved, True),
            check(f"report_{index}_signature_roles", not missing_roles, missing_roles, required_roles),
        ])
        matrix.append({"reportId": _first(report, "reportId", "recordId"), "missingSignatureRoles": missing_roles, "result": status})
    output = result("evaluate_r18_material_report_approval_procedure", _aggregate(failed, incomplete), facts={"approvalProcedureMatrix": matrix}, checks=checks, rule_version=R18_RULE_VERSION)
    output["approvalProcedureMatrix"] = matrix
    return output


def evaluate_r18_material_test_results_and_traceability(arguments: dict[str, Any]) -> dict[str, Any]:
    items = _records(arguments.get("designItems"))
    reports = [*_records(arguments.get("retestReports")), *_records(arguments.get("materialNdtReports"))]
    if not items:
        return _insufficient("evaluate_r18_material_test_results_and_traceability", "r18_design_items_missing")
    matrix, checks = [], []
    failed = incomplete = False
    applicable = 0
    for index, item in enumerate(items, 1):
        retest = _truth(_first(item, "requiresMaterialRetest", "materialRetestRequired"))
        ndt = _truth(_first(item, "requiresMaterialNdt", "materialNdtRequired"))
        if retest is False and ndt is False:
            matrix.append({"componentItemId": _id(item, index), "result": "not_applicable"})
            continue
        applicable += 1
        matches = _matches(item, reports)
        if not matches:
            failed = True
            matrix.append({"componentItemId": _id(item, index), "result": "failed", "reasonCodes": ["required_material_report_missing"]})
            continue
        item_failed = item_incomplete = False
        comparisons = []
        limits = _records(item.get("acceptanceLimits"))
        for report in matches:
            batch_ok = _same(_first(item, "batchNo", "heatNo", "serialNo"), _first(report, "batchNo", "heatNo", "serialNo"))
            expected_sample = item.get("sampleNo")
            report_sample = report.get("sampleNo")
            sample_ok = _same(expected_sample, report_sample) if _present(expected_sample) else (
                _present(report_sample) or str(report.get("recordKind") or "") == "material_ndt"
            )
            trace_ok = batch_ok and sample_ok
            conclusion = _first(report, "conclusion", "testConclusion", "inspectionConclusion")
            conclusion_known = _present(conclusion)
            conclusion_ok = _accepted(conclusion) if conclusion_known else False
            if not trace_ok or (conclusion_known and not conclusion_ok):
                item_failed = True
            elif not conclusion_known:
                item_incomplete = True
            checks.extend([
                check(f"component_{index}_{_safe(_first(report, 'reportId', 'recordId'))}_traceability", trace_ok, {"itemBatch": _first(item, "batchNo", "heatNo"), "reportBatch": _first(report, "batchNo", "heatNo"), "reportSample": report.get("sampleNo")}, "same_batch_heat_and_sample_chain"),
                check(f"component_{index}_{_safe(_first(report, 'reportId', 'recordId'))}_conclusion", conclusion_ok, conclusion, "accepted"),
            ])
            report_results = _result_map(report.get("testResults"))
            for limit in limits:
                limit_report_kind = _norm(limit.get("reportKind"))
                actual_report_kind = _norm(report.get("recordKind"))
                if limit_report_kind and limit_report_kind not in {actual_report_kind, "retest" if actual_report_kind == "materialretest" else "ndt" if actual_report_kind == "materialndt" else actual_report_kind}:
                    continue
                code = str(limit.get("itemCode") or limit.get("name") or "")
                actual = decimal(report_results.get(_norm(code)))
                minimum, maximum = decimal(limit.get("minimum")), decimal(limit.get("maximum"))
                if actual is None:
                    item_incomplete = True
                    passed = False
                else:
                    passed = (minimum is None or actual >= minimum) and (maximum is None or actual <= maximum)
                    item_failed |= not passed
                comparisons.append({"reportId": _first(report, "reportId", "recordId"), "itemCode": code, "actual": actual, "minimum": minimum, "maximum": maximum, "passed": passed})
                checks.append(check(f"component_{index}_{_safe(code)}_within_limits", passed, actual, {"minimum": minimum, "maximum": maximum}))
        failed |= item_failed
        incomplete |= item_incomplete
        matrix.append({"componentItemId": _id(item, index), "matchedReportIds": [_first(report, "reportId", "recordId") for report in matches], "comparisons": comparisons, "result": "failed" if item_failed else "evidence_insufficient" if item_incomplete else "passed"})
    business_result = "not_applicable" if not applicable else _aggregate(failed, incomplete)
    output = result("evaluate_r18_material_test_results_and_traceability", business_result, facts={"testResultMatrix": matrix}, checks=checks, rule_version=R18_RULE_VERSION)
    output["testResultMatrix"] = matrix
    return output


def _evaluate_report_completeness(arguments: dict[str, Any], *, report_kind: str) -> dict[str, Any]:
    tool_name = f"evaluate_r18_material_{'retest' if report_kind == 'retest' else 'ndt'}_report_completeness"
    items = _records(arguments.get("designItems"))
    reports = _records(arguments.get("retestReports" if report_kind == "retest" else "materialNdtReports"))
    if not items:
        return _insufficient(tool_name, "r18_design_items_missing")
    matrix, checks = [], []
    failed = incomplete = False
    applicable = 0
    for index, item in enumerate(items, 1):
        required = _truth(_first(item, "requiresMaterialRetest", "materialRetestRequired") if report_kind == "retest" else _first(item, "requiresMaterialNdt", "materialNdtRequired"))
        if required is False:
            matrix.append({"componentItemId": _id(item, index), "result": "not_applicable"})
            continue
        if required is None:
            incomplete = True
            matrix.append({"componentItemId": _id(item, index), "result": "evidence_insufficient", "reasonCodes": [f"material_{report_kind}_requirement_unknown"]})
            continue
        applicable += 1
        matches = _matches(item, reports)
        required_items = _string_list(item.get("requiredRetestItems" if report_kind == "retest" else "requiredMaterialNdtMethods"))
        actual_items = {_norm(value) for report in matches for value in _string_list(report.get("testItems") or report.get("methods"))}
        missing_items = [value for value in required_items if _norm(value) not in actual_items]
        if not matches or missing_items:
            failed = True
            status = "failed"
        elif not required_items:
            incomplete = True
            status = "evidence_insufficient"
        else:
            status = "passed"
        checks.extend([
            check(f"component_{index}_{report_kind}_report_present", bool(matches), [_first(report, "reportId", "recordId") for report in matches], "matching_report"),
            check(f"component_{index}_{report_kind}_items_complete", not missing_items and bool(required_items), missing_items, required_items),
        ])
        matrix.append({"componentItemId": _id(item, index), "matchedReportIds": [_first(report, "reportId", "recordId") for report in matches], "missingItems": missing_items, "result": status})
    business_result = "not_applicable" if not applicable and not incomplete else _aggregate(failed, incomplete)
    output = result(tool_name, business_result, facts={"reportCompletenessMatrix": matrix}, checks=checks, rule_version=R18_RULE_VERSION)
    output["reportCompletenessMatrix"] = matrix
    return output


def _matches(item: dict[str, Any], reports: list[dict[str, Any]]) -> list[dict[str, Any]]:
    trace = _first(item, "batchNo", "heatNo", "serialNo")
    if _present(trace):
        matched = [report for report in reports if _same(trace, _first(report, "batchNo", "heatNo", "serialNo"))]
        if matched:
            return matched
    return [report for report in reports if _same(_first(item, "productName", "componentType"), _first(report, "productName", "componentType")) and _same(item.get("specification"), report.get("specification"))]


def _result_map(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return {_norm(key): item for key, item in value.items()}
    return {_norm(item.get("itemCode") or item.get("name")): item.get("value") for item in _records(value)}


def _records(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _first(value: dict[str, Any], *keys: str) -> Any:
    return next((value.get(key) for key in keys if _present(value.get(key))), None)


def _present(value: Any) -> bool:
    return value not in (None, "", [], {})


def _norm(value: Any) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", str(value or "").lower())


def _same(left: Any, right: Any) -> bool:
    return _present(left) and _present(right) and _norm(left) == _norm(right)


def _truth(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    normalized = _norm(value)
    if normalized in {"true", "yes", "是", "有", "需要", "适用"}:
        return True
    if normalized in {"false", "no", "否", "无", "不需要", "不适用"}:
        return False
    return None


def _accepted(value: Any) -> bool:
    normalized = _norm(value)
    return any(_norm(item) in normalized for item in _PASS)


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        value = re.split(r"[,，;；、\n]", value)
    return [str(item).strip() for item in value or [] if str(item).strip()] if isinstance(value, (list, tuple, set)) else []


def _safe(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").lower()).strip("_") or "report"


def _approval_role_present(actual: set[str], expected: str) -> bool:
    aliases = {
        "tester": ("tester", "试验", "检测", "检验"),
        "reviewer": ("reviewer", "审核", "复核"),
        "approver": ("approver", "批准", "审批"),
    }
    return any(_norm(alias) in actual_role for alias in aliases.get(expected, (expected,)) for actual_role in actual)


def _id(item: dict[str, Any], index: int) -> str:
    return str(item.get("componentItemId") or item.get("itemId") or f"R18-ITEM-{index}")


def _aggregate(failed: bool, incomplete: bool) -> str:
    return "failed" if failed else "evidence_insufficient" if incomplete else "passed"


def _insufficient(tool_name: str, reason: str) -> dict[str, Any]:
    output = result(tool_name, "evidence_insufficient", facts={}, checks=[], rule_version=R18_RULE_VERSION)
    output["warnings"] = [reason]
    return output
