"""P10 N-19/N-20：制造许可证平台核实自动产出 registryVerifications（替代人工填 manualRegistryVerifications）。

两条查询路径（2026-09-06 生产容器实测）：
- 许可证编号直查：remotePubQuery.json?keyword=<许可证编号> 返回 type=organization 的完整许可记录
  （zsbh 证书编号、dwmc 单位、czzt 证照状态、zsxkxm 许可项目、zsxkfw 许可范围、zsyxq 有效期至、
  tyshxydm 统一社会信用代码）→ 能直接判 verified_match / verified_mismatch / not_found；
- 单位名称查询：orgSearchData.json 只返回 单位名称 / 发证机关 / 证书有效期 / 单位类别，不带编号与范围
  → 只能判 not_found 与登记状态，许可证号无法比对 → unable_to_verify，字段带回供人工补比对。
候选有编号就走第一条，没有才退回第二条。平台连续查询会 403，同一编号/单位只查一次。

自动记录 attested=False、source=cnse_platform；人工核验记录（attested=True）永远覆盖自动记录。
平台故障（验证码识别失败、上游不可用）→ unable_to_verify + platformError，不阻塞审查。
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any

from libs.contracts.responses import server_time
from libs.integrations.cnse_client import (
    CnseConfigurationError,
    CnseProtocolError,
    CnseRecognitionError,
    CnseRequestError,
)
from libs.integrations.external_registry_queries import (
    configured_cnse_origin,
    query_cnse_organization_license,
    query_cnse_organizations,
)

AUTO_SOURCE = "cnse_platform"
_ORG_SUFFIXES = ("有限责任公司", "股份有限公司", "有限公司", "公司")


def auto_verify_enabled() -> bool:
    return str(os.getenv("AICHECK_R12_AUTO_VERIFY") or "true").strip().lower() not in {"0", "false", "no", "off"}


def _normalize_org(value: Any) -> str:
    text = re.sub(r"[\s（）()·\-—]", "", str(value or ""))
    for suffix in _ORG_SUFFIXES:
        if text.endswith(suffix):
            text = text[: -len(suffix)]
            break
    return text


def _normalize_license(value: Any) -> str:
    return "".join(character for character in str(value or "").upper() if character.isalnum())


def _parse_date(value: Any) -> date | None:
    text = str(value or "").strip()
    match = re.match(r"(\d{4})[-./年](\d{1,2})[-./月](\d{1,2})", text)
    if not match:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def _registry_status(valid_until: str, *, today: date | None = None) -> str:
    end = _parse_date(valid_until)
    if end is None:
        return "unknown"
    return "active" if end >= (today or datetime.now(UTC).date()) else "expired"


_LICENSE_STATUS = {"有效": "active", "注销": "revoked", "吊销": "revoked", "撤销": "revoked", "暂停": "suspended", "失效": "expired", "过期": "expired"}


def verification_from_license_record(
    candidate: dict[str, Any], lookup: dict[str, Any], *, today: date | None = None
) -> dict[str, Any]:
    """许可证编号直查（remotePubQuery type=organization）→ R12 验证记录。

    编号能查到即平台登记了这张证；outcome 由"登记单位是否就是证书上的单位"决定：
    一致 → verified_match；不一致 → verified_mismatch（证是别家的）；查不到 → not_found。
    """
    base = {
        "candidateId": str(candidate.get("candidateId") or ""),
        "source": AUTO_SOURCE,
        "attested": False,
        "sourceUrl": f"{configured_cnse_origin()}/info-pub/pub",
        "queriedAt": server_time(),
        "lookupBy": "licenseNo",
    }
    if not lookup.get("found"):
        return {**base, "outcome": "not_found", "registryStatus": "unknown", "comment": "公示平台按许可证编号未查到登记记录。"}
    record = lookup.get("record") if isinstance(lookup.get("record"), dict) else {}
    czzt = str(record.get("czzt") or "").strip()
    status = _LICENSE_STATUS.get(czzt)
    if status is None:
        status = _registry_status(str(record.get("zsyxq") or ""), today=today)
    elif status == "active" and _registry_status(str(record.get("zsyxq") or ""), today=today) == "expired":
        status = "expired"  # 平台 czzt 对已到期证书仍可能标"有效"，以到期日为准（与 validFlag 同坑）
    scope = " ".join(part for part in (record.get("zsxkxm"), record.get("zsxkfw"), record.get("zsxkfwDesc")) if part) or str(record.get("xkxm") or "")
    result = {
        **base,
        "registryLicenseNo": str(record.get("zsbh") or ""),
        "registryOrganizationName": str(record.get("dwmc") or ""),
        "registryIssuer": str(record.get("fzjg") or ""),
        "registryStatus": status,
        "registryStatusRaw": czzt,
        "registryScopeRaw": scope,
        "registryLicenseCategory": str(record.get("xklb") or ""),
        "registryValidFrom": str(record.get("zsfzrq") or ""),
        "registryValidUntil": str(record.get("zsyxq") or ""),
        "registryCreditCode": str(record.get("tyshxydm") or ""),
        "platformOrgId": str(record.get("dwid") or ""),
    }
    same_org = _normalize_org(record.get("dwmc")) == _normalize_org(candidate.get("organizationName"))
    if same_org or not str(candidate.get("organizationName") or "").strip():
        return {**result, "outcome": "verified_match"}
    return {**result, "outcome": "verified_mismatch", "comment": "平台登记的持证单位与证书上的单位名称不一致。"}


def match_organization_rows(rows: list[dict[str, Any]], organization_name: str) -> list[dict[str, Any]]:
    """平台按关键字模糊匹配，可能返回同名子公司；只留规范化后名称一致的行。"""
    target = _normalize_org(organization_name)
    if not target:
        return []
    return [row for row in rows if isinstance(row, dict) and _normalize_org(row.get("dwmc")) == target]


def verification_from_rows(
    candidate: dict[str, Any],
    rows: list[dict[str, Any]],
    *,
    detail: dict[str, Any] | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    """把平台行（和可选的许可明细）翻成 R12 验证记录（字段与人工核验一致）。"""
    matched = match_organization_rows(rows, str(candidate.get("organizationName") or ""))
    base = {
        "candidateId": str(candidate.get("candidateId") or ""),
        "source": AUTO_SOURCE,
        "attested": False,
        "sourceUrl": f"{configured_cnse_origin()}/info-pub/pub",
        "queriedAt": server_time(),
        "platformRowCount": len(rows),
        "matchedRowCount": len(matched),
    }
    if not matched:
        return {**base, "outcome": "not_found", "registryStatus": "unknown", "comment": "公示平台按单位名称未查到该单位。"}
    # 同一单位可能有多张证（多行）：取有效期最晚的一行作为登记状态依据
    best = max(matched, key=lambda row: _parse_date(row.get("zsyxq")) or date.min)
    record = {
        **base,
        "registryOrganizationName": str(best.get("dwmc") or ""),
        "registryIssuer": str(best.get("fzjg") or ""),
        "registryValidUntil": str(best.get("zsyxq") or ""),
        "registryStatus": _registry_status(str(best.get("zsyxq") or ""), today=today),
        "registryUpdatedAt": str(best.get("sjgxsj") or ""),
        "platformOrgId": str(best.get("dwid") or ""),
    }
    if not detail:
        return {
            **record,
            "outcome": "unable_to_verify",
            "comment": "公示平台已查到该单位与证书有效期，但单位查询不返回许可证编号与许可范围，需人工核对编号与范围。",
        }
    registry_no = _normalize_license(detail.get("licenseNo"))
    candidate_no = _normalize_license(candidate.get("licenseNo"))
    record.update(
        {
            "registryLicenseNo": str(detail.get("licenseNo") or ""),
            "registryScopeRaw": str(detail.get("scope") or ""),
            "registryValidFrom": str(detail.get("validFrom") or record.get("registryValidFrom") or ""),
            "registryValidUntil": str(detail.get("validUntil") or record.get("registryValidUntil") or ""),
        }
    )
    if detail.get("status"):
        record["registryStatus"] = str(detail["status"])
    if registry_no and candidate_no and registry_no == candidate_no:
        return {**record, "outcome": "verified_match"}
    return {**record, "outcome": "verified_mismatch", "comment": "平台登记的许可证编号与证书上的编号不一致。"}


def _platform_error(exc: BaseException) -> str:
    if isinstance(exc, CnseRecognitionError):
        return "CNSE_RECOGNITION_FAILED"
    if isinstance(exc, CnseConfigurationError):
        return "CNSE_SERVICE_MISCONFIGURED"
    return "CNSE_UPSTREAM_FAILED"


_USE_DEFAULT: Any = object()


def auto_verify_candidates(
    candidates: list[dict[str, Any]],
    *,
    query: Callable[[str], dict[str, Any]] = _USE_DEFAULT,
    license_query: Callable[[str], dict[str, Any]] | None = _USE_DEFAULT,
    detail_lookup: Callable[[str, dict[str, Any]], dict[str, Any] | None] | None = None,
    today: date | None = None,
) -> list[dict[str, Any]]:
    """逐个候选证照查平台：有许可证编号先按编号直查（能比对编号与单位），否则按单位名称查；
    同一编号/单位只查一次。平台故障不抛，记 unable_to_verify + platformError。"""
    # 缺省在调用时解析模块级函数，测试与运行时都能整体替换（monkeypatch）
    if query is _USE_DEFAULT:
        query = query_cnse_organizations
    if license_query is _USE_DEFAULT:
        license_query = query_cnse_organization_license
    cache: dict[str, dict[str, Any]] = {}
    license_cache: dict[str, dict[str, Any]] = {}
    results: list[dict[str, Any]] = []
    for candidate in candidates:
        if not isinstance(candidate, dict) or not candidate.get("candidateId"):
            continue
        license_no = _normalize_license(candidate.get("licenseNo"))
        if license_no and license_query is not None:
            if license_no not in license_cache:
                try:
                    license_cache[license_no] = {"lookup": license_query(str(candidate.get("licenseNo")))}
                except (CnseRecognitionError, CnseConfigurationError, CnseRequestError, CnseProtocolError) as exc:
                    license_cache[license_no] = {"error": _platform_error(exc)}
            cached_license = license_cache[license_no]
            if cached_license.get("error"):
                results.append(
                    {
                        "candidateId": str(candidate["candidateId"]),
                        "source": AUTO_SOURCE,
                        "attested": False,
                        "outcome": "unable_to_verify",
                        "registryStatus": "unknown",
                        "platformError": cached_license["error"],
                        "lookupBy": "licenseNo",
                        "comment": "公示平台查询失败，需人工核验。",
                        "queriedAt": server_time(),
                    }
                )
            else:
                results.append(verification_from_license_record(candidate, cached_license["lookup"], today=today))
            continue
        name = str(candidate.get("organizationName") or "").strip()
        if not name:
            results.append(
                {
                    "candidateId": str(candidate["candidateId"]),
                    "source": AUTO_SOURCE,
                    "attested": False,
                    "outcome": "unable_to_verify",
                    "registryStatus": "unknown",
                    "comment": "证书上未识别出单位名称，无法在平台按单位查询。",
                    "queriedAt": server_time(),
                }
            )
            continue
        key = _normalize_org(name)
        if key not in cache:
            try:
                cache[key] = {"rows": list(query(name).get("rows") or [])}
            except CnseRecognitionError:
                cache[key] = {"error": "CNSE_RECOGNITION_FAILED"}
            except CnseConfigurationError:
                cache[key] = {"error": "CNSE_SERVICE_MISCONFIGURED"}
            except (CnseRequestError, CnseProtocolError):
                cache[key] = {"error": "CNSE_UPSTREAM_FAILED"}
        cached = cache[key]
        if cached.get("error"):
            results.append(
                {
                    "candidateId": str(candidate["candidateId"]),
                    "source": AUTO_SOURCE,
                    "attested": False,
                    "outcome": "unable_to_verify",
                    "registryStatus": "unknown",
                    "platformError": cached["error"],
                    "comment": "公示平台查询失败，需人工核验。",
                    "queriedAt": server_time(),
                }
            )
            continue
        rows = cached["rows"]
        detail = None
        if detail_lookup is not None:
            matched = match_organization_rows(rows, name)
            org_id = str(matched[0].get("dwid") or "") if matched else ""
            if org_id:
                try:
                    detail = detail_lookup(org_id, candidate)
                except (CnseRecognitionError, CnseConfigurationError, CnseRequestError, CnseProtocolError):
                    detail = None
        results.append(verification_from_rows(candidate, rows, detail=detail, today=today))
    return results


def merge_registry_verifications(
    manual: list[dict[str, Any]], automatic: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """人工核验（attested）永远覆盖自动记录；自动记录只补人工没填的候选。"""
    by_candidate: dict[str, dict[str, Any]] = {}
    for item in automatic:
        if isinstance(item, dict) and item.get("candidateId"):
            by_candidate[str(item["candidateId"])] = item
    for item in manual:
        if isinstance(item, dict) and item.get("candidateId"):
            by_candidate[str(item["candidateId"])] = item
    return list(by_candidate.values())
