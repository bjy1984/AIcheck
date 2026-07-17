from __future__ import annotations

import re
from typing import Any

from libs.review_orchestrator.deterministic_tools import check, result


R17_RULE_VERSION = "r17-arrival-acceptance-tsg-d7006-2020-v1"
_PASS = {"accepted", "approved", "qualified", "passed", "符合", "合格", "通过"}


def evaluate_r17_arrival_acceptance_batch_coverage(arguments: dict[str, Any]) -> dict[str, Any]:
    design_items = _records(arguments.get("designItems"))
    records = _records(arguments.get("acceptanceRecords"))
    if not design_items:
        return _insufficient("evaluate_r17_arrival_acceptance_batch_coverage", "r17_design_items_missing")
    matrix, checks = [], []
    failed = incomplete = False
    for index, item in enumerate(design_items, 1):
        matches = _matches(item, records)
        identity_ready = _present(_first(item, "batchNo", "heatNo", "serialNo")) or (
            _present(_first(item, "productName", "componentType")) and _present(item.get("specification"))
        )
        if not identity_ready:
            incomplete = True
            status, reasons = "evidence_insufficient", ["design_item_identity_incomplete"]
        elif not matches:
            failed = True
            status, reasons = "failed", ["arrival_acceptance_record_missing"]
        elif len(matches) > 1 and not _has_unique_trace_match(item, matches):
            incomplete = True
            status, reasons = "evidence_insufficient", ["acceptance_record_match_ambiguous"]
        else:
            status, reasons = "passed", []
        checks.append(check(f"component_{index}_arrival_acceptance_covered", status == "passed", [record.get("recordId") for record in matches], "one_matching_arrival_acceptance_record"))
        matrix.append({"componentItemId": _id(item, index), "matchedRecordIds": [record.get("recordId") for record in matches], "result": status, "reasonCodes": reasons})
    output = result("evaluate_r17_arrival_acceptance_batch_coverage", _aggregate(failed, incomplete), facts={"acceptanceCoverageMatrix": matrix}, checks=checks, rule_version=R17_RULE_VERSION)
    output["acceptanceCoverageMatrix"] = matrix
    return output


def evaluate_r17_acceptance_procedure(arguments: dict[str, Any]) -> dict[str, Any]:
    records = _records(arguments.get("acceptanceRecords"))
    if not records:
        return _insufficient("evaluate_r17_acceptance_procedure", "acceptance_records_missing")
    required_steps = tuple(arguments.get("requiredSteps") or ("certificate_checked", "identity_checked", "appearance_checked", "dimension_checked", "conclusion_recorded"))
    matrix, checks = [], []
    failed = incomplete = False
    for index, record in enumerate(records, 1):
        procedure_approved = _truth(_first(record, "procedureApproved", "qualitySystemProcedureApproved"))
        completed = _string_set(record.get("completedSteps") or record.get("inspectionItems"))
        missing_steps = [step for step in required_steps if not _step_present(completed, step)]
        conclusion = _first(record, "conclusion", "acceptanceConclusion")
        signatures = _string_set(record.get("signatureRoles"))
        missing_roles = [role for role in ("inspector", "receiver") if not _role_present(signatures, role)]
        if procedure_approved is False or missing_steps or missing_roles or (_present(conclusion) and not _accepted(conclusion)):
            failed = True
            status = "failed"
        elif procedure_approved is None or not _present(conclusion):
            incomplete = True
            status = "evidence_insufficient"
        else:
            status = "passed"
        checks.extend([
            check(f"acceptance_{index}_procedure_approved", procedure_approved is True, procedure_approved, True),
            check(f"acceptance_{index}_required_steps", not missing_steps, missing_steps, list(required_steps)),
            check(f"acceptance_{index}_signature_roles", not missing_roles, missing_roles, ["inspector", "receiver"]),
            check(f"acceptance_{index}_conclusion", _accepted(conclusion), conclusion, "accepted"),
        ])
        matrix.append({"recordId": record.get("recordId"), "missingSteps": missing_steps, "missingSignatureRoles": missing_roles, "result": status})
    output = result("evaluate_r17_acceptance_procedure", _aggregate(failed, incomplete), facts={"acceptanceProcedureMatrix": matrix}, checks=checks, rule_version=R17_RULE_VERSION)
    output["acceptanceProcedureMatrix"] = matrix
    return output


def resolve_r17_sampling_retest_requirement(arguments: dict[str, Any]) -> dict[str, Any]:
    design_items = _records(arguments.get("designItems"))
    if not design_items:
        return _insufficient("resolve_r17_sampling_retest_requirement", "r17_design_items_missing")
    rules = _records(arguments.get("samplingRules"))
    matrix, checks = [], []
    incomplete = False
    required_count = 0
    for index, item in enumerate(design_items, 1):
        explicit = _truth(_first(item, "requiresSamplingRetest", "samplingRetestRequired"))
        source = "design_or_acceptance_fact"
        required = explicit
        if required is None:
            rule = _matching_rule(item, rules)
            if rule:
                required = _truth(rule.get("required"))
                source = str(rule.get("sourceClause") or "frozen_sampling_rule")
        if required is None:
            incomplete = True
        elif required:
            required_count += 1
        checks.append(check(f"component_{index}_sampling_requirement_known", isinstance(required, bool), source if required is not None else None, "explicit_design_fact_or_frozen_rule"))
        matrix.append({"componentItemId": _id(item, index), "samplingRetestRequired": required, "requirementSource": source if required is not None else None, "result": "passed" if required is not None else "evidence_insufficient"})
    business_result = "evidence_insufficient" if incomplete else "passed" if required_count else "not_applicable"
    output = result("resolve_r17_sampling_retest_requirement", business_result, facts={"samplingRequirementMatrix": matrix, "requiredItemCount": required_count}, checks=checks, rule_version=R17_RULE_VERSION)
    output["samplingRequirementMatrix"] = matrix
    return output


def evaluate_r17_sampling_witness_chain(arguments: dict[str, Any]) -> dict[str, Any]:
    design_items = _records(arguments.get("designItems"))
    witness_records = _records(arguments.get("witnessRecords"))
    retest_reports = _records(arguments.get("samplingRetestReports"))
    if not design_items:
        return _insufficient("evaluate_r17_sampling_witness_chain", "r17_design_items_missing")
    rules = _records(arguments.get("samplingRules"))
    matrix, checks = [], []
    failed = incomplete = False
    applicable = 0
    for index, item in enumerate(design_items, 1):
        required = _truth(_first(item, "requiresSamplingRetest", "samplingRetestRequired"))
        if required is None:
            rule = _matching_rule(item, rules)
            required = _truth((rule or {}).get("required"))
        if required is False:
            matrix.append({"componentItemId": _id(item, index), "result": "not_applicable"})
            continue
        if required is None:
            incomplete = True
            matrix.append({"componentItemId": _id(item, index), "result": "evidence_insufficient", "reasonCodes": ["sampling_requirement_unknown"]})
            continue
        applicable += 1
        witnesses, reports = _matches(item, witness_records), _matches(item, retest_reports)
        if not witnesses or not reports:
            failed = True
            status = "failed"
        else:
            witness = witnesses[0]
            report = reports[0]
            same_sample = _same(_first(witness, "sampleNo"), _first(report, "sampleNo"))
            roles = _string_set(witness.get("witnessRoles"))
            role_complete = any(role in roles for role in {_norm("inspector"), _norm("monitoring_inspector"), _norm("监检人员"), _norm("见证人员")})
            if not _present(_first(witness, "sampleNo")) or not _present(_first(report, "sampleNo")):
                incomplete = True
                status = "evidence_insufficient"
            elif not same_sample or not role_complete:
                failed = True
                status = "failed"
            else:
                status = "passed"
            checks.extend([
                check(f"component_{index}_sample_identity", same_sample, _first(report, "sampleNo"), _first(witness, "sampleNo")),
                check(f"component_{index}_sampling_witness_role", role_complete, sorted(roles), "inspector_or_monitoring_inspector"),
            ])
        matrix.append({"componentItemId": _id(item, index), "witnessRecordIds": [record.get("recordId") for record in witnesses], "retestReportIds": [record.get("reportId") for record in reports], "result": status})
    business_result = "not_applicable" if not applicable and not incomplete else _aggregate(failed, incomplete)
    output = result("evaluate_r17_sampling_witness_chain", business_result, facts={"samplingWitnessMatrix": matrix}, checks=checks, rule_version=R17_RULE_VERSION)
    output["samplingWitnessMatrix"] = matrix
    return output


def evaluate_r17_nonconformance_control(arguments: dict[str, Any]) -> dict[str, Any]:
    records = _records(arguments.get("acceptanceRecords"))
    if not records:
        return _insufficient("evaluate_r17_nonconformance_control", "acceptance_records_missing")
    applicable_records = [record for record in records if not _accepted(_first(record, "conclusion", "acceptanceConclusion"))]
    if not applicable_records:
        return result("evaluate_r17_nonconformance_control", "not_applicable", facts={"nonconformingRecordCount": 0}, checks=[], rule_version=R17_RULE_VERSION)
    matrix, checks = [], []
    failed = incomplete = False
    for index, record in enumerate(applicable_records, 1):
        isolated = _truth(_first(record, "isolated", "quarantined"))
        disposition = _first(record, "disposition", "nonconformanceDisposition")
        release_approved = _truth(_first(record, "releaseApproved", "concessionReleaseApproved"))
        release_disposition = _norm(disposition) in {_norm("released"), _norm("concession_release"), _norm("让步接收"), _norm("放行")}
        if isolated is False or not _present(disposition) or (release_disposition and release_approved is not True):
            failed = True
            status = "failed"
        elif isolated is None:
            incomplete = True
            status = "evidence_insufficient"
        else:
            status = "passed"
        checks.append(check(f"nonconformance_{index}_controlled", status == "passed", {"isolated": isolated, "disposition": disposition, "releaseApproved": release_approved}, "isolated_disposition_recorded_and_release_approved"))
        matrix.append({"recordId": record.get("recordId"), "result": status})
    output = result("evaluate_r17_nonconformance_control", _aggregate(failed, incomplete), facts={"nonconformanceControlMatrix": matrix}, checks=checks, rule_version=R17_RULE_VERSION)
    output["nonconformanceControlMatrix"] = matrix
    return output


def _matches(item: dict[str, Any], records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    trace = _first(item, "batchNo", "heatNo", "serialNo")
    if _present(trace):
        matches = [record for record in records if _same(trace, _first(record, "batchNo", "heatNo", "serialNo"))]
        if matches:
            return matches
    return [record for record in records if _same(_first(item, "productName", "componentType"), _first(record, "productName", "componentType")) and _same(item.get("specification"), record.get("specification"))]


def _matching_rule(item: dict[str, Any], rules: list[dict[str, Any]]) -> dict[str, Any] | None:
    standard = _norm(_first(item, "standardRef", "acceptanceStandard"))
    product = _norm(_first(item, "productName", "componentType"))
    return next((rule for rule in rules if (not rule.get("standardRef") or _norm(rule.get("standardRef")) == standard) and (not rule.get("productType") or _norm(rule.get("productType")) in product)), None)


def _has_unique_trace_match(item: dict[str, Any], records: list[dict[str, Any]]) -> bool:
    trace = _first(item, "batchNo", "heatNo", "serialNo")
    return bool(trace) and sum(1 for record in records if _same(trace, _first(record, "batchNo", "heatNo", "serialNo"))) == 1


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
    if normalized in {"true", "yes", "present", "是", "有", "已完成", "已批准"}:
        return True
    if normalized in {"false", "no", "missing", "否", "无", "未完成", "未批准"}:
        return False
    return None


def _accepted(value: Any) -> bool:
    normalized = _norm(value)
    return any(_norm(item) in normalized for item in _PASS)


def _string_set(value: Any) -> set[str]:
    if isinstance(value, str):
        value = re.split(r"[,，;；、\n]", value)
    return {_norm(item) for item in value or []} if isinstance(value, (list, tuple, set)) else set()


def _step_present(actual: set[str], expected: str) -> bool:
    aliases = {
        "certificate_checked": ("certificatechecked", "质量证明核验", "质保书核验", "质量证明文件检查"),
        "identity_checked": ("identitychecked", "身份标识核验", "标识检查", "炉批号检查"),
        "appearance_checked": ("appearancechecked", "外观检查", "外观验收"),
        "dimension_checked": ("dimensionchecked", "尺寸检查", "规格尺寸检查"),
        "conclusion_recorded": ("conclusionrecorded", "结论记录", "验收结论"),
    }
    return any(_norm(alias) in actual for alias in aliases.get(expected, (expected,)))


def _role_present(actual: set[str], expected: str) -> bool:
    aliases = {
        "inspector": ("inspector", "检验员", "验收人员", "检查人员"),
        "receiver": ("receiver", "接收人员", "收料员", "材料员"),
    }
    return any(_norm(alias) in actual for alias in aliases.get(expected, (expected,)))


def _id(item: dict[str, Any], index: int) -> str:
    return str(item.get("componentItemId") or item.get("itemId") or f"R17-ITEM-{index}")


def _aggregate(failed: bool, incomplete: bool) -> str:
    return "failed" if failed else "evidence_insufficient" if incomplete else "passed"


def _insufficient(tool_name: str, reason: str) -> dict[str, Any]:
    output = result(tool_name, "evidence_insufficient", facts={}, checks=[], rule_version=R17_RULE_VERSION)
    output["warnings"] = [reason]
    return output
