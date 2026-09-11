"""证书事实的平台侧：拿全国特种设备公示平台（CNSE）的登记记录核对并补强 OCR 抽出来的证书。

## 为什么必须有

`search_cnse_persons` 早就能用、在 10 个节点的工具清单里，可 54 次有权限的运行里零次调用——
它只挂在模型可选的工具表上，从没进过事实链。2026-09-11 两件实测把它逼成必需品：

- 焊工证的合格项目代号被 OCR 认坏：`CTAF-Fe II-6G-3/57-FetS…`（GTAW→CTAF、SMAW→SHAV、
  Fef3J→FefBJ），五个项目全是这种串。解码器现在会拒掉它们，但拒掉之后节点 24 也就永远
  证据不足。平台按身份证号返回的是登记原文，绕开 OCR。
- 许可证/焊工证的 OCR 字段全部没有置信度（MinerU VLM 通道 `provider_confidence_unavailable`），
  grounding 只能判「需人工判断」。平台登记记录是权威来源，这里的 1.0 是它配得上的
  ——与 `certificate_facts.certificate_evidence_links` 给已核验引用的口径一致。

## 做什么

对 `build_certificate_facts` 去重后的每条证书：
- 单位许可证（设计/安装/无损检测机构）：证书编号形如 TS1844171-2028 → 按编号直查
  → `r12_registry.verification_from_license_record`（与 R12 人工核验记录同形）；
  outcome=verified_match 时用平台的有效期、许可范围补/校 OCR 值，并挂一条 confidence=1.0 的证据。
- 焊工证 / 检测人员证：证件编号=身份证号（18 位）→ 四步取全部证书（licList）
  → 现行焊工项目代号替换 OCR 代号、有效期取最早到期的现行项目。

## 边界

- 平台失败（验证码、限流 403、超时）一律软失败：保留 OCR 事实，记 platformError；从不抛。
- 同一编号/身份证 24 小时内只查一次：`state["cnse_lookup_cache"]`，全库持久化。
  平台连续查询会 403（2026-09-06 实测），69 节点 × 多项目的扫描一次就能把它打挂。
- 回放（`run["replay"]`）与开关关闭时不碰网。离线回放本来也走不到这里
  （replay_review_acceptance 只调 NDT_FACT_BUILDERS），这是双保险。
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timedelta
from typing import Any

from libs.contracts.responses import server_time
from libs.integrations.cnse_client import CnseApiError

CACHE_KEY = "cnse_lookup_cache"
CACHE_TTL = timedelta(hours=24)
PLATFORM_SOURCE = "cnse_platform"
_ORG_LICENSE_NO = re.compile(r"^TS\d{7}-\d{4}$")
_ID_NUMBER = re.compile(r"^\d{17}[\dXx]$")
_ORG_LICENSE_TYPES = frozenset({"design_license", "installation_license", "ndt_agency_approval"})
_PERSON_TYPES = frozenset({"welder_certificate", "ndt_personnel_certificate"})


def platform_verify_enabled() -> bool:
    return str(os.getenv("AICHECK_CERT_PLATFORM_VERIFY") or "true").strip().lower() not in {"0", "false", "no", "off"}


def _now() -> datetime:
    return datetime.strptime(server_time(), "%Y-%m-%d %H:%M:%S")


def _cached_lookup(state: dict[str, Any], kind: str, key: str, query) -> dict[str, Any]:
    """24 小时内同一键只查一次；平台错误也缓存（避免把限流越打越死），但只缓 1 小时。"""
    cache = state.setdefault(CACHE_KEY, [])
    now = _now()
    for entry in cache:
        if not isinstance(entry, dict) or entry.get("kind") != kind or entry.get("key") != key:
            continue
        try:
            queried_at = datetime.strptime(str(entry.get("queriedAt")), "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
        ttl = timedelta(hours=1) if entry.get("error") else CACHE_TTL
        if now - queried_at <= ttl:
            return entry
    entry: dict[str, Any] = {"kind": kind, "key": key, "queriedAt": server_time()}
    try:
        entry["result"] = query(key)
    except CnseApiError as exc:
        entry["error"] = exc.__class__.__name__
        entry["message"] = str(exc)[:160]
    except Exception as exc:  # noqa: BLE001 -- 事实构建不能因平台异常整段崩掉
        entry["error"] = exc.__class__.__name__
        entry["message"] = str(exc)[:160]
    cache[:] = [item for item in cache if not (isinstance(item, dict) and item.get("kind") == kind and item.get("key") == key)]
    cache.append(entry)
    _persist_cache(state)
    return entry


def _persist_cache(state: dict[str, Any]) -> None:
    try:
        from libs.db.repository import flush_state, repo

        if state is repo.state:
            flush_state({CACHE_KEY})
    except Exception:  # noqa: BLE001 -- 缓存落库失败只是下次多查一次，不影响判定
        return


def _platform_evidence(version_id: str, file_name: str, quoted: str, source_url: str) -> dict[str, Any]:
    from libs.review_orchestrator.certificate_facts import _evidence

    evidence = _evidence(version_id, file_name, 0, None, quoted, confidence=1.0, confidence_unavailable=False)
    evidence.update({"source": PLATFORM_SOURCE, "sourceUrl": source_url, "pageNo": 0})
    return evidence


def _verify_org_license(state: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
    from libs.integrations.external_registry_queries import configured_cnse_origin, query_cnse_organization_license
    from libs.review_orchestrator.certificate_facts import _split_scopes, parse_date
    from libs.review_orchestrator.r12_registry import verification_from_license_record

    license_no = str(record.get("certificateNo") or "").strip().upper()
    entry = _cached_lookup(state, "org_license", license_no, query_cnse_organization_license)
    if entry.get("error"):
        return {**record, "platformVerification": {"source": PLATFORM_SOURCE, "outcome": "unable_to_verify",
                                                   "platformError": entry["error"], "lookupBy": "licenseNo", "queriedAt": entry.get("queriedAt")}}
    verification = verification_from_license_record(
        {"candidateId": license_no, "organizationName": record.get("holder") or "", "licenseNo": license_no},
        entry.get("result") or {},
    )
    updated = {**record, "platformVerification": verification}
    if verification.get("outcome") != "verified_match":
        return updated
    valid_until = parse_date(verification.get("registryValidUntil"), month_end=True)
    if valid_until:
        updated["validUntil"] = valid_until.isoformat()
        updated.setdefault("sources", {})["validUntil"] = PLATFORM_SOURCE
    registry_scopes = _split_scopes(str(verification.get("registryScopeRaw") or ""))
    if registry_scopes:
        updated["scopes"] = list(dict.fromkeys([*registry_scopes, *(record.get("scopes") or [])]))
        updated.setdefault("sources", {})["scopes"] = PLATFORM_SOURCE
    if not record.get("holder") and verification.get("registryOrganizationName"):
        updated["holder"] = verification["registryOrganizationName"]
    quoted = "；".join(
        f"{label}：{verification.get(key)}"
        for label, key in (("平台登记单位", "registryOrganizationName"), ("许可证编号", "registryLicenseNo"),
                           ("许可范围", "registryScopeRaw"), ("有效期至", "registryValidUntil"), ("登记状态", "registryStatus"))
        if verification.get(key)
    )
    updated["evidence"] = [*(record.get("evidence") or []),
                           _platform_evidence(str(record.get("documentVersionId") or ""), str(record.get("fileName") or ""),
                                              quoted, f"{configured_cnse_origin()}/info-pub/pub")]
    return updated


def _verify_person(state: dict[str, Any], record: dict[str, Any], *, reference_date) -> dict[str, Any]:
    from libs.integrations.external_registry_queries import configured_cnse_origin, query_cnse_persons
    from libs.review_orchestrator.certificate_facts import parse_date
    from libs.review_orchestrator.runtime_tools import _is_welder_license, _license_is_current, _split_welder_items

    id_number = str(record.get("certificateNo") or "").strip().upper()
    entry = _cached_lookup(state, "person", id_number, query_cnse_persons)
    base = {"source": PLATFORM_SOURCE, "lookupBy": "idNumber", "queriedAt": entry.get("queriedAt")}
    if entry.get("error"):
        return {**record, "platformVerification": {**base, "outcome": "unable_to_verify", "platformError": entry["error"]}}
    result = entry.get("result") or {}
    licenses = [item for item in (result.get("licenses") or []) if isinstance(item, dict)]
    lookup = result.get("licenseLookup") if isinstance(result.get("licenseLookup"), dict) else {}
    if lookup.get("status") != "completed":
        # 只拿到首条记录：一人多证时平台排第一的可能是起重机指挥（李卫伍，2026-09-06 实测），
        # 不能据此改写 OCR 的项目代号，也不能判「无焊工证」。
        return {**record, "platformVerification": {**base, "outcome": "unable_to_verify",
                                                   "platformError": f"license_list_{lookup.get('status') or 'not_attempted'}"}}
    welder = [item for item in licenses if _is_welder_license(item)] if record.get("certificateType") == "welder_certificate" else licenses
    current = [item for item in welder if _license_is_current(item, reference_date)]
    if not current:
        return {**record, "platformVerification": {**base, "outcome": "not_found", "platformLicenseCount": len(licenses),
                                                   "comment": "公示平台没有返回截至施焊日期现行的项目，不能据此判为无证，需人工到平台复核。"}}
    codes: list[str] = []
    for item in current:
        codes.extend(_split_welder_items(str(item.get("czxm") or "")))
    codes = list(dict.fromkeys(code for code in codes if code))
    valid_until = min((parse_date(str(item.get("yxrqz") or item.get("yxrq") or ""), month_end=True) for item in current
                       if parse_date(str(item.get("yxrqz") or item.get("yxrq") or ""), month_end=True)), default=None)
    updated = {**record, "platformVerification": {**base, "outcome": "verified_match", "platformLicenseCount": len(licenses),
                                                  "currentLicenseCount": len(current), "registryItems": codes,
                                                  "registryValidUntil": valid_until.isoformat() if valid_until else None}}
    if codes:
        updated["qualificationCodes"] = codes
        updated["scopes"] = codes
        updated.setdefault("sources", {})["qualificationCodes"] = PLATFORM_SOURCE
    if valid_until:
        updated["validUntil"] = valid_until.isoformat()
        updated.setdefault("sources", {})["validUntil"] = PLATFORM_SOURCE
    person = result.get("person") if isinstance(result.get("person"), dict) else {}
    if not record.get("holder") and person.get("ryxm"):
        updated["holder"] = str(person["ryxm"])
    quoted = "；".join(filter(None, [f"持证人：{person.get('ryxm')}" if person.get("ryxm") else "",
                                    f"现行项目：{' / '.join(codes)}" if codes else "",
                                    f"有效期至：{valid_until.isoformat()}" if valid_until else ""]))
    updated["evidence"] = [*(record.get("evidence") or []),
                           _platform_evidence(str(record.get("documentVersionId") or ""), str(record.get("fileName") or ""),
                                              quoted, f"{configured_cnse_origin()}/info-pub/pub")]
    return updated


def verify_certificate_records(
    state: dict[str, Any], profile: dict[str, Any], certificates: list[dict[str, Any]], *, review_run: dict[str, Any] | None
) -> list[dict[str, Any]]:
    """给每条证书补上平台侧；不碰网的情况原样返回。"""
    if not certificates or not platform_verify_enabled() or (review_run or {}).get("replay") is True:
        return certificates
    from libs.contracts.responses import business_today
    from libs.review_orchestrator.certificate_facts import parse_date

    reference = parse_date((review_run or {}).get("workDate") or (review_run or {}).get("reviewDate")) or business_today()
    certificate_type = str(profile.get("certificateType") or "")
    output: list[dict[str, Any]] = []
    for record in certificates:
        number = str(record.get("certificateNo") or "").strip().upper()
        if certificate_type in _ORG_LICENSE_TYPES and _ORG_LICENSE_NO.match(number):
            output.append(_verify_org_license(state, record))
        elif certificate_type in _PERSON_TYPES and _ID_NUMBER.match(number):
            output.append(_verify_person(state, record, reference_date=reference))
        else:
            output.append(record)
    return output
