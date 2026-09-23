"""Projectless review helpers accepting only minimal structured certificate fields.

No document upload, OCR, repository, object storage, jobs or result cache.
The calling AI platform keeps original documents and performs OCR before calling.
"""
from __future__ import annotations

import logging
import re
import unicodedata
from contextvars import ContextVar
from datetime import date
from typing import Any

from libs.review_orchestrator.deterministic_tools import check_certificate_validity

RETENTION = {"serverStoresInput": False, "serverStoresResult": False,
             "temporaryFiles": "none", "externalProvider": None}
_PRIVATE_REGISTRY_LOOKUP: ContextVar[bool] = ContextVar("private_registry_lookup", default=False)


class _PrivateRegistryLogFilter(logging.Filter):
    def filter(self, record):
        return not _PRIVATE_REGISTRY_LOOKUP.get()


# CNSE uses GET parameters containing identity numbers. HTTPX INFO request logs
# and HTTPCore DEBUG traces would otherwise persist those fields. The ContextVar
# suppresses only this lookup's transport logs, preserving concurrent requests.
for _logger_name in ("httpx", "httpcore.connection", "httpcore.http11", "httpcore.http2",
                     "httpcore.proxy", "httpcore.socks"):
    logging.getLogger(_logger_name).addFilter(_PrivateRegistryLogFilter())


class InspectionServiceError(ValueError):
    def __init__(self, message: str, *, status: int = 400, reason: str = "INVALID_INPUT"):
        super().__init__(message)
        self.status, self.reason = status, reason


def service_capabilities() -> dict[str, Any]:
    return {
        "schemaVersion": "inspection-services-v1", "projectRequired": False,
        "documentUploadAccepted": False, "ocrProvided": False,
        "retention": RETENTION,
        "rules": {"available": True, "source": "业务节点描述 v3"},
        "certificateValidity": {"available": True, "authenticityVerified": False},
        "certificateRegistry": {"available": True, "requiresExplicitExternalConsent": True,
                                "source": "cnse_platform", "externalProviderRetention": "not_controlled"},
    }


def _date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise InspectionServiceError("日期须为 YYYY-MM-DD。")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise InspectionServiceError("日期无效。") from None


def _strings(values: Any) -> None:
    if not isinstance(values, list) or len(values) > 100 or any(
        not isinstance(value, str) or not value.strip() or len(value) > 1000 for value in values
    ):
        raise InspectionServiceError("范围须为不超过 100 项的非空字符串数组。")


def _normalized_text(value: str) -> str:
    # Compatibility normalization preserves meaning: Ⅰ/Ⅱ -> I/II, full-width
    # letters -> ASCII; Chinese, punctuation and internal word boundaries remain.
    return " ".join(unicodedata.normalize("NFKC", value).split())


def _aggregate_status(statuses: list[str]) -> str:
    if "failed" in statuses:
        return "failed"
    if not statuses or "evidence_insufficient" in statuses:
        return "evidence_insufficient"
    return "passed"


def _certificate_dimensions(item: dict[str, Any], payload: dict[str, Any], start: date | None,
                            reference: str) -> None:
    date_status = item["result"]
    if not item.get("validFrom"):
        item["checks"].append({"code": "valid_from_present", "passed": False,
                               "actual": None, "expected": "present", "reason": "evidence_insufficient"})
        date_status = _aggregate_status([date_status, "evidence_insufficient"])
    else:
        target = start.isoformat() if start else reference
        # Legacy date checking skips validFrom if validUntil is absent, and when
        # checking a reference date. Cover both without treating an unknown as true.
        if (not start or not item.get("validUntil")) and item["validFrom"] > target:
            item["checks"].append({"code": "valid_from_covers_reference_date", "passed": False,
                                   "actual": item["validFrom"], "expected": target})
            date_status = "failed"
    dimensions = {"dateValidity": date_status, "holderMatch": "not_requested", "scopeMatch": "not_requested"}
    expected_holder = _normalized_text(payload.get("expectedHolder", ""))
    if expected_holder:
        actual_holder = _normalized_text(item.get("holder") or "")
        holder_matches = actual_holder == expected_holder
        dimensions["holderMatch"] = "evidence_insufficient" if not actual_holder else "passed" if holder_matches else "failed"
        item["checks"].append({"code": "holder_exact_match", "passed": holder_matches,
                               "actual": item.get("holder"), "expected": payload["expectedHolder"]})
    required_scopes = {_normalized_text(value) for value in payload.get("requiredScopes", [])}
    if required_scopes:
        actual_scopes = {_normalized_text(value) for value in item.get("scopes", [])}
        matches = required_scopes <= actual_scopes
        dimensions["scopeMatch"] = "evidence_insufficient" if not actual_scopes else "passed" if matches else "failed"
        item["checks"].append({"code": "scope_exact_items_present", "passed": matches,
                               "actual": sorted(actual_scopes), "expected": sorted(required_scopes),
                               "missingItems": sorted(required_scopes - actual_scopes)})
    item["dimensionResults"] = dimensions
    item["result"] = _aggregate_status([value for value in dimensions.values() if value != "not_requested"])


def certificate_validity(payload: dict[str, Any]) -> dict[str, Any]:
    allowed = {"certificates", "expectedHolder", "requiredScopes", "periodStart", "periodEnd", "referenceDate"}
    if set(payload) - allowed:
        raise InspectionServiceError("存在不支持的证件核验字段。")
    certificates = payload.get("certificates")
    if not isinstance(certificates, list) or len(certificates) > 100:
        raise InspectionServiceError("certificates 须为不超过 100 项的数组。")
    _strings(payload.get("requiredScopes", []))
    if not isinstance(payload.get("expectedHolder", ""), str) or len(payload.get("expectedHolder", "")) > 1000:
        raise InspectionServiceError("持有人名称无效。")
    start, end = _date(payload.get("periodStart")), _date(payload.get("periodEnd"))
    reference_date = _date(payload.get("referenceDate"))
    if bool(start) != bool(end) or (start and end and start > end):
        raise InspectionServiceError("业务起止日期须同时提供且起始不得晚于结束。")
    if not start and not reference_date:
        raise InspectionServiceError("请提供业务核验日期 referenceDate 或完整业务起止日期，不使用当前日期替代施焊日期。")
    for certificate in certificates:
        if not isinstance(certificate, dict) or set(certificate) - {"certificateNo", "holder", "validFrom", "validUntil", "scopes"}:
            raise InspectionServiceError("证件仅接受编号、持有人、有效日期及范围字段。")
        for field in ("certificateNo", "holder"):
            if not isinstance(certificate.get(field, ""), str) or len(certificate.get(field, "")) > 1000:
                raise InspectionServiceError("证件编号或持有人无效。")
        valid_from, valid_until = _date(certificate.get("validFrom")), _date(certificate.get("validUntil"))
        if valid_from and valid_until and valid_from > valid_until:
            raise InspectionServiceError("证件有效日期区间无效。")
        _strings(certificate.get("scopes", []))
    # The legacy scope normalizer drops Chinese and Roman-numeral distinctions,
    # and legacy holder matching permits substrings. Use only its date checks.
    effective_reference = reference_date.isoformat() if reference_date else end.isoformat()
    output = check_certificate_validity({**payload, "expectedHolder": None, "requiredScopes": [],
                                         "referenceDate": effective_reference})
    # Neither field is required for these explicitly selected checks; issuer is
    # intentionally outside the minimal input contract. Do not emit always-missing
    # legacy warnings or imply that an explicit reference date is a fallback.
    output["warnings"] = [warning for warning in output.get("warnings", [])
                          if warning == "no_certificate_extracted"]
    reference = output["facts"]["referenceDate"]
    for item in output["facts"]["certificates"]:
        _certificate_dimensions(item, payload, start, reference)
    checked_dimensions = ["dateValidity"]
    if _normalized_text(payload.get("expectedHolder", "")):
        checked_dimensions.append("holderMatch")
    if payload.get("requiredScopes"):
        checked_dimensions.append("scopeMatch")
    unchecked_dimensions = [name for name in ("holderMatch", "scopeMatch", "authenticity") if name not in checked_dimensions]
    output["facts"]["expectedHolder"] = payload.get("expectedHolder")
    output["facts"]["requiredScopes"] = sorted({_normalized_text(value) for value in payload.get("requiredScopes", [])})
    output["facts"]["dateBasis"] = "business_period" if start else "explicit_reference_date"
    output["facts"]["referenceDateSource"] = "provided" if reference_date else "period_end"
    output["facts"].pop("reason", None)
    output["result"] = _aggregate_status([item["result"] for item in output["facts"]["certificates"]])
    output["checks"] = [check for item in output["facts"]["certificates"] for check in item["checks"]]
    output["ruleVersion"] = "inspection-certificate-fields-v2"
    output["summary"] = {"checkCount": len(output["checks"]),
                         "passedCount": sum(bool(item.get("passed")) for item in output["checks"]),
                         "failedCount": sum(not item.get("passed") for item in output["checks"])}
    return {**output, "authenticityVerified": False,
            "checkedDimensions": checked_dimensions, "uncheckedDimensions": unchecked_dimensions,
            "scopeMatching": "NFKC_normalized_exact_items_only",
            "limitation": "仅汇总请求核验的字段维度。范围仅核对完整项目字符串，不判技术互认或实际作业覆盖；未请求的维度未核验，通过不代表证件真实或正式监检结论。",
            "retention": RETENTION}


def certificate_registry(payload: dict[str, Any]) -> dict[str, Any]:
    from libs.integrations.external_registry_queries import (
        query_cnse_organization_license,
        query_cnse_persons,
    )

    if set(payload) != {"kind", "identifier", "allowExternalQuery"} or payload.get("allowExternalQuery") is not True:
        raise InspectionServiceError("登记查询须明确授权向全国特种设备公示平台发送证件标识。")
    kind, identifier = payload.get("kind"), payload.get("identifier")
    pattern = r"\d{17}[\dXx]" if kind == "person" else r"TS\d{7}-\d{4}"
    if not isinstance(kind, str) or kind not in {"person", "organization_license"} or not isinstance(identifier, str) or not re.fullmatch(pattern, identifier):
        raise InspectionServiceError("登记查询类型或证件标识无效。")
    log_token = _PRIVATE_REGISTRY_LOOKUP.set(True)
    try:
        query = query_cnse_persons if kind == "person" else query_cnse_organization_license
        records = query(identifier)
    except Exception:  # noqa: BLE001 -- provider exception messages may include identity fields
        raise InspectionServiceError("登记平台暂不可查询；不能据此认定证件无效。",
                                     status=503, reason="REGISTRY_UNAVAILABLE") from None
    finally:
        _PRIVATE_REGISTRY_LOOKUP.reset(log_token)
    return {"kind": kind, "source": "cnse_platform", "records": records,
            "authenticityConclusion": "manual_confirmation_required",
            "retention": {**RETENTION, "externalProvider": "cnse_platform",
                          "externalProviderRetention": "not_controlled"}}
