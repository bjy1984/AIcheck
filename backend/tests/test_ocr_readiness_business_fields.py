"""就绪度不能只看「有文本 + 有坐标」（线上审计 L-3b）。

线上实测一份资料：

    ocrReadiness.status : "ready"        ← 系统告诉监检「证据就绪」
    artifactIntegrity   : true
    bbox 覆盖率          : 100%
    字段名               : OCR文本, OCR文本2 … OCR文本5
    字段置信度           : 全部 0.0

监检打开只看到五条编号文本片段，对审查毫无用处——而指标是绿的。
这类「指标绿了、事情没成」是最贵的失败：它不报错，只是让人做出错误判断。
"""

from __future__ import annotations

from typing import Any

import pytest

from libs.ocr_readiness import (
    build_document_ocr_readiness,
    business_field_rows,
    is_placeholder_field_name,
)


@pytest.mark.parametrize(
    "name",
    ["OCR文本", "OCR文本2", "文本3", "片段1", "text_1", "fragment", "field_12"],
)
def test_placeholder_names_are_recognized(name: str) -> None:
    assert is_placeholder_field_name(name)


@pytest.mark.parametrize("name", ["证书编号", "设计压力", "有效期", "焊工姓名", "材料牌号"])
def test_business_field_names_are_not_flagged(name: str) -> None:
    assert not is_placeholder_field_name(name)


def test_business_field_rows_filters_only_placeholders() -> None:
    rows = [
        {"fieldName": "OCR文本", "fieldValue": "第一段"},
        {"fieldName": "证书编号", "fieldValue": "TS6J-2024-03158"},
        {"fieldName": "OCR文本2", "fieldValue": "第二段"},
    ]
    kept = business_field_rows(rows)
    assert [item["fieldName"] for item in kept] == ["证书编号"]


class _FakeRepo:
    def __init__(self, parse_result: dict[str, Any]) -> None:
        self.state = {"ocr_parse_results": [parse_result], "parse_results": [parse_result]}


def _readiness(fields: list[dict[str, Any]]) -> dict[str, Any]:
    parse_result = {
        "id": "PR-1",
        "parseResultId": "PR-1",
        "documentVersionId": "DV-1",
        "status": "success",
        "fields": fields,
        "fragments": [{"text": "正文", "bbox": [1, 2, 3, 4], "pageNo": 1}],
        "finishedAt": "2026-08-13 10:00:00",
    }
    document = {"id": "DOC-1", "currentVersionId": "DV-1", "currentOcrStatus": "已识别"}
    return build_document_ocr_readiness(_FakeRepo(parse_result), document)


def test_all_placeholder_fields_are_flagged_as_not_extracted() -> None:
    """全是占位命名 = 没做字段识别。

    注意这里**不改 status**：status=ready 的语义是「产物完整且可定位」，
    有文字有坐标就成立，那是既有契约（test_ocr_readiness.py 钉住）。
    业务字段可用性是另一件事，单独给信号，由界面如实呈现。
    """
    readiness = _readiness(
        [
            {"fieldName": f"OCR文本{i or ''}", "fieldValue": f"第{i or 1}段", "bbox": [1, 2, 3, 4], "pageNo": 1}
            for i in range(5)
        ]
    )
    codes = {str(item.get("code")) for item in readiness["blockingReasons"]}
    assert "OCR_BUSINESS_FIELDS_NOT_EXTRACTED" in codes, codes
    assert readiness["businessFieldCount"] == 0
    assert readiness["businessFieldsExtracted"] is False


def test_real_business_fields_do_not_raise_the_advisory() -> None:
    """只要有一个真字段就算识别出来了，不该再提示「未识别业务字段」。"""
    readiness = _readiness(
        [
            {"fieldName": "OCR文本", "fieldValue": "正文片段", "bbox": [1, 2, 3, 4], "pageNo": 1},
            {"fieldName": "证书编号", "fieldValue": "TS6J-2024-03158", "bbox": [5, 6, 7, 8], "pageNo": 1},
        ]
    )
    assert readiness["status"] == "ready", readiness
    assert readiness["businessFieldCount"] == 1
    assert readiness["businessFieldsExtracted"] is True
    codes = {str(item.get("code")) for item in readiness["blockingReasons"]}
    assert "OCR_BUSINESS_FIELDS_NOT_EXTRACTED" not in codes


def test_business_field_count_is_exposed_for_the_ui() -> None:
    """界面要能区分「10 个字段」和「10 个片段、0 个业务字段」。"""
    readiness = _readiness([{"fieldName": "OCR文本", "fieldValue": "x", "bbox": [1, 2, 3, 4]}])
    assert "businessFieldCount" in readiness
    assert readiness["fieldCount"] == 1
    assert readiness["businessFieldCount"] == 0


def test_fragments_only_result_is_not_ready() -> None:
    """线上实际形态：parse_result.fields 为空，只有 fragments。

    落库时 fields_from_fragments() 会把前 5 个正文片段编号成 OCR文本1..5
    （libs/db/repository.py），于是 readiness 里 fieldCount=0、状态 ready，
    界面上却显示「识别字段 (5)」——三处口径互相矛盾，而监检看到的是「就绪」。
    """
    readiness = _readiness([])
    assert readiness["fieldCount"] == 0
    assert readiness["businessFieldCount"] == 0
    assert readiness["businessFieldsExtracted"] is False
    codes = {str(item.get("code")) for item in readiness["blockingReasons"]}
    assert "OCR_BUSINESS_FIELDS_NOT_EXTRACTED" in codes, codes
