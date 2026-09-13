"""公示平台进事实链：核得上的证书用登记原文补强，核不上的保留 OCR，从不碰网也从不崩。

2026-09-11：search_cnse_persons 在 10 个节点的工具清单里、54 次运行零次调用——
它只在模型可选的工具表上，从没进过事实链。焊工证 OCR 代号被认坏（CTAF/SHAV/FefBJ）、
许可证 OCR 字段全无置信度，两条路都通向「平台登记记录才是权威来源」。
"""
from __future__ import annotations

import pytest

from libs.integrations.cnse_client import CnseRequestError
from libs.review_orchestrator import certificate_platform_verify as cpv
from libs.review_orchestrator.certificate_facts import build_certificate_facts

ORG_RECORD = {
    "zsbh": "TS1844171-2028", "dwmc": "广东政和工程有限公司", "czzt": "有效", "fzjg": "广东省市场监督管理局",
    "xklb": "特种设备设计", "zsxkfw": "压力管道设计 GC1 GC2 GB1 GB2", "zsfzrq": "2024-01-18", "zsyxq": "2028-01-17",
}


def _license_state(*, ocr_scopes_text: str = "压力管道设计") -> dict:
    return {
        "documents": [{"id": "DOC-LIC", "projectId": "P-1", "currentVersionId": "DV-LIC",
                       "fileName": "广东政和设计院压力管道设计资质.png", "materialTypeCode": "design_license"}],
        "versions": [{"id": "DV-LIC", "documentId": "DOC-LIC"}],
        "projects": [{"id": "P-1", "designOrgName": "广东政和工程有限公司"}],
        "ocr_parse_results": [{
            "documentVersionId": "DV-LIC", "status": "success", "profileId": "qualification_certificate_v1",
            "quality": {"reasons": ["provider_confidence_unavailable"]},
            "fields": [
                {"fieldCode": "certificate_no", "fieldName": "许可证编号", "fieldValue": "TS1844171-2028", "pageNo": 1, "bbox": [1, 1, 2, 2], "confidence": 0.0},
                {"fieldCode": "organization_name", "fieldName": "单位名称", "fieldValue": "广东政和工程有限公司", "pageNo": 1, "bbox": [1, 1, 2, 2], "confidence": 0.0},
                {"fieldCode": "license_scope", "fieldName": "许可范围", "fieldValue": ocr_scopes_text, "pageNo": 1, "bbox": [1, 1, 2, 2], "confidence": 0.0},
                {"fieldCode": "valid_until", "fieldName": "有效期至", "fieldValue": "2028年1月", "pageNo": 1, "bbox": [1, 1, 2, 2], "confidence": 0.0},
            ],
            "fragments": [],
        }],
    }


def _welder_state() -> dict:
    return {
        "documents": [{"id": "DOC-W", "projectId": "P-1", "currentVersionId": "DV-W", "fileName": "10.姜军焊工证.pdf", "materialTypeCode": "welder_certificate"}],
        "versions": [{"id": "DV-W", "documentId": "DOC-W"}],
        "projects": [{"id": "P-1"}],
        "ocr_parse_results": [{
            "documentVersionId": "DV-W", "status": "success", "profileId": "generic_document_v1",
            "quality": {"reasons": ["provider_confidence_unavailable"]},
            "fields": [
                {"fieldCode": "welder_name", "fieldName": "姓名", "fieldValue": "姜军", "pageNo": 1, "bbox": [1, 1, 2, 2], "confidence": 0.78},
                {"fieldCode": "certificate_no", "fieldName": "证件编号", "fieldValue": "511621198504208836", "pageNo": 1, "bbox": [1, 1, 2, 2], "confidence": 0.78},
                {"fieldCode": "welder_operation_item_code", "fieldName": "项目代号", "fieldValue": "CTAF-Fe II-6G-3/57-FetS-02/11/12", "pageNo": 1, "bbox": [1, 1, 2, 2], "confidence": 0.78},
            ],
            "fragments": [],
        }],
    }


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """任何用例都不许真的碰平台；没打桩就调到这里直接失败。"""
    def boom(*_args, **_kwargs):
        raise AssertionError("测试里不许真的查公示平台")
    monkeypatch.setattr("libs.integrations.external_registry_queries.query_cnse_organization_license", boom)
    monkeypatch.setattr("libs.integrations.external_registry_queries.query_cnse_persons", boom)
    # conftest 把开关默认关掉（别的用例不该碰平台）；本文件专门测它，显式打开。
    monkeypatch.setenv("AICHECK_CERT_PLATFORM_VERIFY", "on")


def test_许可证核得上_用平台登记补范围与有效期_证据是1点0(monkeypatch):
    calls = []
    monkeypatch.setattr("libs.integrations.external_registry_queries.query_cnse_organization_license",
                        lambda no: calls.append(no) or {"licenseNo": no, "found": True, "record": ORG_RECORD})
    state = _license_state()
    facts = build_certificate_facts(state, "P-1", 1, ["DV-LIC"])
    cert = facts["certificateFacts"]["certificates"][0]
    assert cert["platformVerification"]["outcome"] == "verified_match"
    assert cert["validUntil"] == "2028-01-17", "OCR 只到月，平台给了到日"
    assert {"GC1", "GC2", "GB1", "GB2"} <= set(cert["scopes"])
    assert cert["sources"]["scopes"] == "cnse_platform"
    platform_evidence = [item for item in cert["evidence"] if item.get("source") == "cnse_platform"]
    assert len(platform_evidence) == 1
    assert platform_evidence[0]["confidence"] == 1.0 and platform_evidence[0]["confidenceUnavailable"] is False
    assert "TS1844171-2028" in platform_evidence[0]["quotedText"]
    # 进了 judgment：这条证书的事实现在有分了，grounding 不再只能「需人工判断」。
    fact = facts["judgment"]["claimedFacts"][0]
    assert platform_evidence[0]["evidenceRefId"] in fact["evidenceRefIds"]
    assert fact["confidenceUnavailable"] is False
    assert calls == ["TS1844171-2028"]


def test_平台查不到_保留OCR事实_不冒充(monkeypatch):
    monkeypatch.setattr("libs.integrations.external_registry_queries.query_cnse_organization_license",
                        lambda no: {"licenseNo": no, "found": False, "record": {}})
    cert = build_certificate_facts(_license_state(), "P-1", 1, ["DV-LIC"])["certificateFacts"]["certificates"][0]
    assert cert["platformVerification"]["outcome"] == "not_found"
    assert cert["validUntil"] == "2028-01-01"  # OCR「2028年1月」按月初，未被平台覆盖
    assert all(item.get("source") != "cnse_platform" for item in cert["evidence"])


def test_平台故障是软失败_不崩不改(monkeypatch):
    def broken(_no):
        raise CnseRequestError("403 Forbidden")
    monkeypatch.setattr("libs.integrations.external_registry_queries.query_cnse_organization_license", broken)
    cert = build_certificate_facts(_license_state(), "P-1", 1, ["DV-LIC"])["certificateFacts"]["certificates"][0]
    assert cert["platformVerification"]["outcome"] == "unable_to_verify"
    assert cert["platformVerification"]["platformError"] == "CnseRequestError"
    assert cert["validUntil"] == "2028-01-01"


def test_同一编号24小时只查一次_错误也缓存(monkeypatch):
    calls = []
    monkeypatch.setattr("libs.integrations.external_registry_queries.query_cnse_organization_license",
                        lambda no: calls.append(no) or {"licenseNo": no, "found": True, "record": ORG_RECORD})
    state = _license_state()
    build_certificate_facts(state, "P-1", 1, ["DV-LIC"])
    build_certificate_facts(state, "P-1", 1, ["DV-LIC"])
    assert calls == ["TS1844171-2028"], "第二次应命中 state['cnse_lookup_cache']"
    assert state["cnse_lookup_cache"][0]["kind"] == "org_license"
    # 必须有稳定 id：没有 id 的条目落库按列表下标当主键，列表一重排就与另一个进程撞
    # ConcurrentPersistenceError（2026-09-12 部署实测：API 容器起不来）。
    assert state["cnse_lookup_cache"][0]["id"].startswith("CNSE-")
    build_certificate_facts(state, "P-1", 1, ["DV-LIC"])
    assert [item["id"] for item in state["cnse_lookup_cache"]] == [state["cnse_lookup_cache"][0]["id"]], "同一键重查只留一条，id 不变"


def test_焊工证按身份证取全部证书_现行项目替换OCR坏码(monkeypatch):
    monkeypatch.setattr("libs.integrations.external_registry_queries.query_cnse_persons", lambda sfzh: {
        "idNumber": sfzh,
        "person": {"ryxm": "姜军", "fzjg": "南京江北新区管理委员会市场监督管理局"},
        "licenses": [
            {"zslb": "特种设备作业人员证", "czxm": "GTAW-FeII-6G-3/57-FefS-02/11/12和SMAW-FeII-6G(K)-9/57-Fef3J", "yxrqz": "2028-10-30", "validFlag": "1"},
            {"zslb": "特种设备作业人员证", "czxm": "GTAW-FeI-2G-2/25-FefS-02/11/12", "yxrqz": "2020-01-01", "validFlag": "1"},
            {"zslb": "起重机指挥", "czxm": "Q1", "yxrqz": "2029-01-01", "validFlag": "1"},
        ],
        "licenseLookup": {"status": "completed"},
    })
    facts = build_certificate_facts(_welder_state(), "P-1", 24, ["DV-W"], review_run={"projectId": "P-1", "nodeId": 24, "inputDocumentVersionIds": ["DV-W"], "workDate": "2026-09-11"})
    cert = facts["certificateFacts"]["certificates"][0]
    assert cert["platformVerification"]["outcome"] == "verified_match"
    # _split_welder_items 会把代号转大写；decode_welder_code 也转，大小写不携带信息。
    codes = [code.upper() for code in cert["qualificationCodes"]]
    assert "GTAW-FEII-6G-3/57-FEFS-02/11/12" in codes and "SMAW-FEII-6G(K)-9/57-FEF3J" in codes
    assert not any("CTAF" in code for code in codes), "OCR 坏码被平台原文替换"
    assert not any("FEI-2G" in code for code in codes), "2020 年到期的不算现行"
    assert not any(code == "Q1" for code in codes), "起重机指挥不是焊工项目"
    assert cert["validUntil"] == "2028-10-30"


def test_只拿到首条记录时不改写(monkeypatch):
    """李卫伍那次：平台排第一的是起重机指挥，全表没取到——不能据此改 OCR，也不能判无证。"""
    monkeypatch.setattr("libs.integrations.external_registry_queries.query_cnse_persons", lambda sfzh: {
        "idNumber": sfzh, "person": {"ryxm": "李卫伍"}, "licenses": [], "licenseLookup": {"status": "failed", "reason": "CnseProtocolError"},
    })
    cert = build_certificate_facts(_welder_state(), "P-1", 24, ["DV-W"])["certificateFacts"]["certificates"][0]
    assert cert["platformVerification"]["outcome"] == "unable_to_verify"
    assert cert["platformVerification"]["platformError"] == "license_list_failed"
    # 通用抽取路径把项目代号放在 scopes（legacy namespace 再映射成 qualificationCodes）。
    assert any("CTAF" in code for code in cert.get("scopes") or []), "OCR 值原样保留"


def test_开关关闭与回放都不碰网(monkeypatch):
    monkeypatch.setenv("AICHECK_CERT_PLATFORM_VERIFY", "off")
    cert = build_certificate_facts(_license_state(), "P-1", 1, ["DV-LIC"])["certificateFacts"]["certificates"][0]
    assert "platformVerification" not in cert
    monkeypatch.setenv("AICHECK_CERT_PLATFORM_VERIFY", "on")
    cert = build_certificate_facts(_license_state(), "P-1", 1, ["DV-LIC"],
                                   review_run={"projectId": "P-1", "nodeId": 1, "inputDocumentVersionIds": ["DV-LIC"], "replay": True})["certificateFacts"]["certificates"][0]
    assert "platformVerification" not in cert


def test_不像编号的证书不查():
    assert cpv._ORG_LICENSE_NO.match("TS1844171-2028") and not cpv._ORG_LICENSE_NO.match("粤TS-001")
    assert cpv._ID_NUMBER.match("511621198504208836") and not cpv._ID_NUMBER.match("HG-2026-0830")


def test_证件号查到的是别人时不覆盖也不标已核验(monkeypatch):
    """2026-09-13 线上实测：「焊工证 李卫伍」挂上的平台证据是「持证人：赵相军」。

    证件号是 OCR 读出来的，读错一位就查到别人；照抄回来等于把另一个人的合格项目
    安到这名焊工头上，比查不到危险得多。
    """
    monkeypatch.setattr("libs.integrations.external_registry_queries.query_cnse_persons", lambda sfzh: {
        "idNumber": sfzh,
        "person": {"ryxm": "赵相军"},
        "licenses": [{"zslb": "特种设备作业人员证", "czxm": "GTAW-FeIV-6G-3/55-FefS-02/10/12", "yxrqz": "2029-01-01", "validFlag": "1"}],
        "licenseLookup": {"status": "completed"},
    })
    state = _welder_state()
    state["ocr_parse_results"][0]["fields"][0]["fieldValue"] = "李卫伍"
    cert = build_certificate_facts(state, "P-1", 24, ["DV-W"])["certificateFacts"]["certificates"][0]
    verification = cert["platformVerification"]
    assert verification["outcome"] == "verified_mismatch"
    assert verification["registryHolder"] == "赵相军" and verification["claimedHolder"] == "李卫伍"
    assert not any("GTAW-FEIV-6G" in str(code).upper() for code in cert.get("qualificationCodes") or []), "不许把别人的项目覆盖过来"
    assert all(item.get("source") != "cnse_platform" for item in cert.get("evidence") or []), "不许标成平台已核验"


def test_人证不符不许判核验通过(monkeypatch):
    """2026-09-13 用户截图：公示平台那列红着「与平台登记不一致」，结论列却绿着「核验通过」。

    `check_certificate_validity` 只看有效期与许可范围，人证不符没进它的判定——
    这是判定问题，不是显示问题。
    """
    from libs.review_orchestrator.deterministic_tools import check_certificate_validity

    result = check_certificate_validity({
        "certificateType": "welder_certificate",
        "referenceDate": "2026-09-13",
        "certificates": [{
            "certificateNo": "410521198609180550", "holder": "李卫伍", "validUntil": "2028-11-30",
            "platformVerification": {"outcome": "verified_mismatch", "registryHolder": "赵相军"},
        }],
    })
    assert result["result"] == "evidence_insufficient"
    cert = result["facts"]["certificates"][0]
    assert cert["result"] == "evidence_insufficient"
    assert any(c["code"].endswith("holder_matches_registry") and not c["passed"] for c in cert["checks"])


def test_单位证书的登记名要显示出来():
    """2026-09-13 线上审计：P-2026-ECD202 节点 3 的 TS7310417-2026。

    单位证书走 r12_registry，登记名字段是 `registryOrganizationName`；
    `check_certificate_validity` 原来只读 `registryHolder`，界面上「与平台登记一致」
    这条的实际值就是空的——监检看到的是「平台查不到」，实际是「平台登记的是另一家单位」。
    """
    from libs.review_orchestrator.deterministic_tools import check_certificate_validity

    result = check_certificate_validity({
        "certificateType": "ndt_org_certificate",
        "referenceDate": "2026-09-13",
        "certificates": [{
            "certificateNo": "TS7310417-2026", "holder": "某某检测有限公司", "validUntil": "2026-12-10",
            "platformVerification": {
                "outcome": "verified_mismatch",
                "registryOrganizationName": "另一家检测有限公司",
            },
        }],
    })
    cert = result["facts"]["certificates"][0]
    registry_check = next(c for c in cert["checks"] if c["code"].endswith("holder_matches_registry"))
    assert registry_check["passed"] is False
    assert registry_check["actual"] == "另一家检测有限公司", "登记单位名不能是空的"
    assert registry_check["expected"] == "某某检测有限公司"
