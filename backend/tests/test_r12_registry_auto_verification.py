"""P10 N-19/N-20：制造许可证平台核实自动产出 registryVerifications；人工记录永远覆盖自动记录。"""

from __future__ import annotations

from datetime import date

from libs.integrations.cnse_client import CnseRecognitionError
from libs.review_orchestrator import r12_registry

ROWS = [
    {"dwid": "e9f9127a", "fzjg": "广东省市场监督管理局", "zsyxq": "2028-01-17", "dwmc": "广东政和工程有限公司", "dwlb": "特种设备生产单位", "sjgxsj": "2024-07-16", "zsyxqyz": ""},
    {"dwid": "6e808a2b", "fzjg": "广东省市场监督管理局", "zsyxq": "2021-01-17", "dwmc": "广东政和工程有限公司", "dwlb": "特种设备生产单位", "sjgxsj": "2019-07-16", "zsyxqyz": ""},
    {"dwid": "zzz", "fzjg": "x", "zsyxq": "2030-01-01", "dwmc": "广东政和工程有限公司东莞分公司", "dwlb": "", "sjgxsj": "", "zsyxqyz": ""},
]
CANDIDATE = {"candidateId": "R12LIC-1", "organizationName": "广东政和工程有限公司", "licenseNo": "TS1844171-2028"}
TODAY = date(2026, 9, 6)


def test_rows_without_detail_give_status_but_not_a_licence_verdict() -> None:
    record = r12_registry.verification_from_rows(CANDIDATE, ROWS, today=TODAY)
    assert record["outcome"] == "unable_to_verify", "单位查询不带许可证号，不能宣称核验通过"
    assert record["registryOrganizationName"] == "广东政和工程有限公司"
    assert record["registryValidUntil"] == "2028-01-17", "多张证取有效期最晚的一张"
    assert record["registryStatus"] == "active"
    assert record["matchedRowCount"] == 2, "同名分公司不算同一单位"
    assert record["attested"] is False and record["source"] == "cnse_platform"


def test_missing_organization_is_not_found_and_expired_is_flagged() -> None:
    assert r12_registry.verification_from_rows(CANDIDATE, [], today=TODAY)["outcome"] == "not_found"
    expired = r12_registry.verification_from_rows(CANDIDATE, [ROWS[1]], today=TODAY)
    assert expired["registryStatus"] == "expired"


def test_detail_enables_licence_number_comparison() -> None:
    matched = r12_registry.verification_from_rows(
        CANDIDATE, ROWS, detail={"licenseNo": "TS1844171-2028", "scope": "GC1", "validUntil": "2028-01-17"}, today=TODAY
    )
    assert matched["outcome"] == "verified_match" and matched["registryScopeRaw"] == "GC1"
    mismatched = r12_registry.verification_from_rows(CANDIDATE, ROWS, detail={"licenseNo": "TS9999999-2030"}, today=TODAY)
    assert mismatched["outcome"] == "verified_mismatch"


def test_auto_verify_queries_each_organization_once_and_survives_platform_errors() -> None:
    calls: list[str] = []

    def query(name: str) -> dict:
        calls.append(name)
        if name.startswith("坏"):
            raise CnseRecognitionError("captcha")
        return {"rows": ROWS}

    candidates = [
        CANDIDATE,
        {**CANDIDATE, "candidateId": "R12LIC-2"},
        {"candidateId": "R12LIC-3", "organizationName": "坏单位有限公司", "licenseNo": "TS1"},
        {"candidateId": "R12LIC-4", "organizationName": "", "licenseNo": "TS2"},
    ]
    results = r12_registry.auto_verify_candidates(candidates, query=query, license_query=None, today=TODAY)
    assert calls == ["广东政和工程有限公司", "坏单位有限公司"], "同一单位只查一次"
    by_id = {item["candidateId"]: item for item in results}
    assert by_id["R12LIC-1"]["outcome"] == "unable_to_verify" and by_id["R12LIC-2"]["registryStatus"] == "active"
    assert by_id["R12LIC-3"]["outcome"] == "unable_to_verify" and by_id["R12LIC-3"]["platformError"] == "CNSE_RECOGNITION_FAILED"
    assert by_id["R12LIC-4"]["outcome"] == "unable_to_verify"


def test_manual_attested_records_override_automatic_ones() -> None:
    merged = r12_registry.merge_registry_verifications(
        manual=[{"candidateId": "R12LIC-1", "outcome": "verified_match", "attested": True}],
        automatic=[{"candidateId": "R12LIC-1", "outcome": "not_found"}, {"candidateId": "R12LIC-2", "outcome": "not_found"}],
    )
    by_id = {item["candidateId"]: item for item in merged}
    assert by_id["R12LIC-1"]["outcome"] == "verified_match" and by_id["R12LIC-2"]["outcome"] == "not_found"


LICENSE_RECORD = {
    "czzt": "有效", "dwid": "e9f9127a", "dwlb": "生产单位", "dwmc": "广东政和工程有限公司", "fzjg": "广东省市场监督管理局",
    "xklb": "境内地方局发证", "xkxm": "压力管道设计设计", "zsxkxm": "压力管道设计", "zsxkfw": "", "zsxkfwDesc": "",
    "zsfzrq": "2024-01-02", "zsyxq": "2028-01-17", "zsbgrq": "", "tyshxydm": "914401017792068107", "sqlb": "换证", "validFlag": "1", "sjgxsj": "2024-07-16",
    "zsbh": "TS1844171-2028",
}


def test_licence_number_lookup_verifies_match_mismatch_and_not_found() -> None:
    lookup = {"found": True, "record": LICENSE_RECORD}
    matched = r12_registry.verification_from_license_record(CANDIDATE, lookup, today=TODAY)
    assert matched["outcome"] == "verified_match"
    assert matched["registryLicenseNo"] == "TS1844171-2028" and matched["registryScopeRaw"] == "压力管道设计"
    assert matched["registryStatus"] == "active" and matched["registryValidUntil"] == "2028-01-17"
    assert matched["registryCreditCode"] == "914401017792068107"
    other = r12_registry.verification_from_license_record({**CANDIDATE, "organizationName": "别家工程有限公司"}, lookup, today=TODAY)
    assert other["outcome"] == "verified_mismatch"
    assert r12_registry.verification_from_license_record(CANDIDATE, {"found": False}, today=TODAY)["outcome"] == "not_found"
    # 平台 czzt 对到期证书仍可能标"有效"：以到期日为准
    expired = r12_registry.verification_from_license_record(CANDIDATE, {"found": True, "record": {**LICENSE_RECORD, "zsyxq": "2025-01-01"}}, today=TODAY)
    assert expired["registryStatus"] == "expired"


def test_auto_verify_prefers_licence_lookup_and_caches_per_number() -> None:
    license_calls: list[str] = []
    name_calls: list[str] = []

    def license_query(no: str) -> dict:
        license_calls.append(no)
        return {"found": True, "record": LICENSE_RECORD}

    def query(name: str) -> dict:
        name_calls.append(name)
        return {"rows": ROWS}

    candidates = [CANDIDATE, {**CANDIDATE, "candidateId": "R12LIC-2"}, {"candidateId": "R12LIC-5", "organizationName": "广东政和工程有限公司", "licenseNo": ""}]
    results = r12_registry.auto_verify_candidates(candidates, query=query, license_query=license_query, today=TODAY)
    assert license_calls == ["TS1844171-2028"], "同一编号只查一次"
    assert name_calls == ["广东政和工程有限公司"], "没有编号的候选退回按单位名称查"
    by_id = {item["candidateId"]: item for item in results}
    assert by_id["R12LIC-1"]["outcome"] == "verified_match" and by_id["R12LIC-2"]["outcome"] == "verified_match"
    assert by_id["R12LIC-5"]["outcome"] == "unable_to_verify" and by_id["R12LIC-5"]["registryStatus"] == "active"


def test_dispatcher_tool_uses_licence_lookup_and_flags_human_confirmation(monkeypatch) -> None:
    from libs.review_orchestrator.runtime_tools import dispatch_runtime_tool

    monkeypatch.setattr(r12_registry, "query_cnse_organization_license", lambda no: {"found": True, "record": LICENSE_RECORD})
    result = dispatch_runtime_tool({}, "verify_org_license", {"name": "广东政和工程有限公司", "expectedLicenseNo": "TS1844171-2028"})
    assert result["status"] == "succeeded" and result["outcome"] == "verified_match"
    assert result["requiresHumanConfirmation"] is False
    assert result["verification"]["registryScopeRaw"] == "压力管道设计"
    other = dispatch_runtime_tool({}, "verify_org_license", {"name": "别家有限公司", "expectedLicenseNo": "TS1844171-2028"})
    assert other["outcome"] == "verified_mismatch" and other["requiresHumanConfirmation"] is True
    assert dispatch_runtime_tool({}, "verify_org_license", {"name": ""})["status"] == "failed"
