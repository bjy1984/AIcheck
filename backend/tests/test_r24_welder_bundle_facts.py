"""节点 24 的焊工事实：合订本按人分开，旧版抽取器落库的字段和表格按原文重算。

2026-09-23 本地七项目快照：三名焊工的证合订成一份，r24 事实里李卫伍带着赵相军的
身份证号（整份文件层面的 OCR 字段是对合订本整体抽的）；另一份焊工证的有效期
还是旧版抽取器落库的 2027.04.20（把名单里的日期拼错了，原文是 2027-04-30）。
"""
from __future__ import annotations

import pytest

from libs.review_orchestrator.r24_r34_facts import build_r24_business_facts


@pytest.fixture(autouse=True)
def _platform_off(monkeypatch):
    monkeypatch.setenv("AICHECK_CERT_PLATFORM_VERIFY", "off")


def _state(fragments, fields=(), tables=()):
    return {
        "documents": [{"id": "DOC-W", "projectId": "P-1", "currentVersionId": "DV-W",
                       "fileName": "焊工证.pdf", "materialTypeCode": "welder_certificate"}],
        "versions": [{"id": "DV-W", "documentId": "DOC-W"}],
        "projects": [{"id": "P-1"}],
        "ocr_parse_results": [{"documentVersionId": "DV-W", "status": "success", "profileId": "generic_document_v1",
                               "fields": list(fields), "tables": list(tables),
                               "fragments": [{"pageNo": 1, "text": text} for text in fragments]}],
    }


def _run():
    return {"projectId": "P-1", "nodeId": 24, "inputDocumentVersionIds": ["DV-W"], "workDate": "2026-09-12"}


def test_bundled_cards_become_one_record_per_welder_with_their_own_id():
    fragments = ["焊工清单", "张三焊工证", "姓名 张三", "证件编号 110101199001010011",
                 "李四焊工证", "姓名 李四", "证件编号 110101199202020022"]
    # 旧 OCR 对整份合订本抽出的字段：姓名是李四，证号却是张三的。
    mixed = [{"fieldCode": "welder_name", "fieldName": "姓名", "fieldValue": "李四", "pageNo": 1},
             {"fieldCode": "welder_certificate_no", "fieldName": "证件编号", "fieldValue": "110101199001010011",
              "pageNo": 1}]
    certificates = build_r24_business_facts(_state(fragments, mixed), _run())["r24"]["certificates"]
    assert sorted((item.get("welderName"), item.get("welderCertificateNo")) for item in certificates) == [
        ("张三", "110101199001010011"), ("李四", "110101199202020022")]


def test_stored_fields_and_table_from_the_old_extractor_are_recomputed():
    fragments = ["序号 姓名 持证项目 有效期限 发证单位",
                 "1 方力 GTAW-FeⅣ-6G-2/57-FefS-02/10/12 2027-04-30 示例市市场监督管理局"]
    stale_fields = [{"fieldCode": "approval_date", "fieldName": "批准日期", "fieldValue": "2027.04.30", "pageNo": 1},
                    {"fieldCode": "valid_until", "fieldName": "有效日期", "fieldValue": "2027.04.20", "pageNo": 1}]
    stale_table = {"tableId": "welder_qualified_item_table_profile", "extractionMethod": "ocr.welder_certificate.extract",
                   "headers": ["序号", "作业项目代号", "批准日期", "有效日期", "有效性"],
                   "normalizedRows": [{"itemNo": 1, "operationItemCode": "GTAW-FeⅣ-6G-2/57-FefS-02/10/12",
                                       "approvalDate": "2027.04.30", "validUntil": "2027.04.20"}]}
    certificates = build_r24_business_facts(_state(fragments, stale_fields, [stale_table]), _run())["r24"]["certificates"]
    assert [item.get("validUntil") for item in certificates] == ["2027.04.30"]


def test_heuristic_score_does_not_stand_in_for_missing_ocr_confidence():
    # 焊工证抽取器固定给 0.78；引擎声明不报分时，这个分数不能让证据门判「符合」。
    state = _state(["张三焊工证", "姓名 张三", "证件编号 110101199001010011",
                    "李四焊工证", "姓名 李四", "证件编号 110101199202020022"])
    state["ocr_parse_results"][0]["quality"] = {"reasons": ["provider_confidence_unavailable"]}
    judgment = build_r24_business_facts(state, _run())["judgment"]
    assert judgment["claimedFacts"] and all(fact.get("confidenceUnavailable") for fact in judgment["claimedFacts"])


def test_a_document_title_is_not_a_procedure_number():
    # 本地快照：PQR/报告编号抽成了「焊接工艺评定任务书」。
    from libs.review_orchestrator.r24_r34_facts import _extract_records

    state = _state(["焊接工艺评定任务书"], [
        {"fieldCode": "reportNo", "fieldName": "报告编号", "fieldValue": "焊接工艺评定任务书", "pageNo": 1},
        {"fieldCode": "wpsNo", "fieldName": "WPS编号", "fieldValue": "WPS2024-02", "pageNo": 1}])
    records = _extract_records(state, state["ocr_parse_results"][0], "R25", "pqr")
    assert records and not any(record.get("reportNo") or record.get("pqrNo") for record in records)
    assert records[0].get("wpsNo") == "WPS2024-02"


def test_every_qualified_item_on_one_card_survives_the_merge():
    # 平台关着时，一张证上的多个合格项目全靠抽取器生成的表；
    # 原来每行都继承整份文件的首项代号，合并后只剩第一项。
    first, second = "GTAW-FeⅡ-6G-3/159-FefS-02/11/12", "SMAW-FeⅡ-6G(K)-12/159-Fef3J"
    fragments = ["姓名 赵俊祥", "证件编号 510602197603143578", "作业项目代号 批准日期 有效日期",
                 f"{first} 2024.11.13 2028.10.31", f"{second} 2023.02.17 2027.02.16"]
    facts = build_r24_business_facts(_state(["\n".join(fragments)]), _run())["r24"]
    assert [item.get("qualificationCodes") for item in facts["certificates"]] == [[first, second]]
    assert facts["qualificationCodes"] == [first, second]
