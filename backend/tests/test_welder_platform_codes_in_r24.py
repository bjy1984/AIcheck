"""节点 24/29 的焊工事实要用平台登记的项目代号，否则 OCR 坏码把整段判定拖死。

2026-09-12 线上实测：OCR 把代号认成 CTAF/SHAW/PTAV，decode_welder_qualification 全拒，
`all_codes_decoded` 实际 0/要求 4，AC-R24-01..04 一律证据不足。平台按身份证返回登记原文，
但它只进了 certificate_facts 那条链——r24/r29 的焊工事实是另一个 builder 建的。
"""
from __future__ import annotations

import pytest

from libs.review_orchestrator.r24_r34_facts import build_r24_business_facts

PLATFORM = {
    "person": {"ryxm": "姜军"},
    "licenses": [{"zslb": "特种设备作业人员证", "czxm": "GTAW-FeII-6G-3/57-FefS-02/11/12和SMAW-FeII-6G(K)-9/57-Fef3J",
                  "yxrqz": "2029-09-30", "validFlag": "1"}],
    "licenseLookup": {"status": "completed"},
}


def _state() -> dict:
    return {
        "documents": [{"id": "DOC-W", "projectId": "P-1", "currentVersionId": "DV-W",
                       "fileName": "10.姜军焊工证.pdf", "materialTypeCode": "welder_certificate"}],
        "versions": [{"id": "DV-W", "documentId": "DOC-W"}],
        "projects": [{"id": "P-1"}],
        "ocr_parse_results": [{
            "documentVersionId": "DV-W", "status": "success", "profileId": "generic_document_v1",
            "fields": [
                {"fieldCode": "welder_name", "fieldName": "焊工姓名", "fieldValue": "姜军", "pageNo": 1, "bbox": [1, 1, 2, 2], "confidence": 0.78},
                {"fieldCode": "certificate_no", "fieldName": "证书编号", "fieldValue": "511621198504208836", "pageNo": 1, "bbox": [1, 1, 2, 2], "confidence": 0.78},
                {"fieldCode": "qualified_items", "fieldName": "合格项目", "fieldValue": "CTAF-Fe II-6G-3/57-FetS-02/11/12", "pageNo": 1, "bbox": [1, 1, 2, 2], "confidence": 0.78},
            ],
            "fragments": [],
        }],
    }


def _run() -> dict:
    return {"projectId": "P-1", "nodeId": 24, "inputDocumentVersionIds": ["DV-W"], "workDate": "2026-09-12"}


@pytest.fixture(autouse=True)
def _platform_on(monkeypatch):
    monkeypatch.setenv("AICHECK_CERT_PLATFORM_VERIFY", "on")


def test_平台核到时用登记原文替换OCR坏码(monkeypatch):
    monkeypatch.setattr("libs.integrations.external_registry_queries.query_cnse_persons", lambda sfzh: {**PLATFORM, "idNumber": sfzh})
    facts = build_r24_business_facts(_state(), _run())["r24"]
    codes = [code.upper() for code in facts["qualificationCodes"]]
    assert "GTAW-FEII-6G-3/57-FEFS-02/11/12" in codes and "SMAW-FEII-6G(K)-9/57-FEF3J" in codes
    assert not any("CTAF" in code for code in codes), "OCR 坏码必须被平台原文替换"
    cert = facts["certificates"][0]
    assert cert["platformVerification"]["outcome"] == "verified_match"
    assert cert["sources"]["qualificationCodes"] == "cnse_platform"
    assert cert["validUntil"] == "2029-09-30"


def test_平台不通时原样保留OCR不冒充(monkeypatch):
    from libs.integrations.cnse_client import CnseRequestError

    def boom(_sfzh):
        raise CnseRequestError("403 Forbidden")

    monkeypatch.setattr("libs.integrations.external_registry_queries.query_cnse_persons", boom)
    facts = build_r24_business_facts(_state(), _run())["r24"]
    assert facts["qualificationCodes"] == ["CTAF-Fe II-6G-3/57-FetS-02/11/12"]
    assert facts["certificates"][0]["platformVerification"]["outcome"] == "unable_to_verify"


def test_焊工事实在界面上有中文标签():
    """原来 factId 是 r24-certificates-1、value 是 None，界面上就是一串代号加一段 JSON。"""
    facts = build_r24_business_facts(_state(), {**_run(), "replay": True})
    fact = next(item for item in facts["judgment"]["claimedFacts"] if item["factId"].startswith("r24-certificates"))
    # 标签优先给人名——监检看的是「哪个焊工」，不是一串身份证号。
    assert fact["label"] == "焊工证 姜军"
    assert fact["value"] == "511621198504208836"


def test_一个焊工一条证_空模板行不成事实():
    """OCR 把两名焊工的资料拆成 15 行、其中 10 行只有「自 年 月至 年 月」这种空模板，
    界面上就成了「事实与证据 共 17 条」的噪声，核验也被迫对 15 张「证」逐一判有效期。"""
    state = _state()
    parse = state["ocr_parse_results"][0]
    parse["tables"] = [{
        "pageNo": 1,
        "rows": [
            {"姓名": "姜军", "证书编号": "511621198504208836", "项目代号": "CTAF-Fe II-6G-3/57-FetS-02/11/12", "有效期": "自2025年10月至2029年09月"},
            {"姓名": "姜军", "证书编号": "511621198504208836", "有效期": "自 年 月至 年 月"},
            {"姓名": "姜军", "证书编号": "511621198504208836", "发证机关(章)": "批准日期"},
        ],
    }]
    facts = build_r24_business_facts(state, {**_run(), "replay": True})["r24"]
    assert len(facts["certificates"]) == 1, "同一个证件号只应有一条证"
    cert = facts["certificates"][0]
    assert "自 年 月至 年 月" not in str(cert.get("validUntil") or ""), "占位有效期不能当成抽到了"
    quote = cert["evidence"]["quotedText"]
    assert not quote.startswith("{"), "引文要给人读，不是 json.dumps"
    assert cert["evidence"]["fileName"] == "10.姜军焊工证.pdf" and cert["evidence"]["documentId"] == "DOC-W"
