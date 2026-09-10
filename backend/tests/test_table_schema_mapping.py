"""表頭全部取自生產庫真實資料（2026-09-10 抽出），不是造的。"""

import pytest

from libs.table_schema_mapping import (
    build_domain_rows,
    classify_table,
    load_signatures,
    map_row,
)

SIGNATURES = load_signatures()

# 廣東 LNG 支線改造的材料質量證明文件匯總表，原樣。
CERTIFICATE_ROW = {
    "厂家": "福建宁德正上管业科技有限公司",
    "序号": "1",
    "元件名称": "不锈钢无缝钢管",
    "材质/标准": "材质:S30408标准:GB/T14976-2025",
    "规格/炉批号": "规格: Φ89×3.0 钢号:06Cr19Ni10(304)",
    "制造许可证编号": "TS2735332-2030",
    "型式试验证书编号": "TSX71101004320260043",
    "产品质量证明书编号": "20260213951",
}
# 無損檢測比例表，原樣。
NDT_ROW = {"介质": "天然气", "管道号": "PL8301", "公称直径": "DN100", "检测比例": "10%"}


def table(rows, **extra):
    return {"tableId": "T1", "pageNo": 3, "normalizedRows": rows, **extra}


def signature(name):
    return next(item for item in SIGNATURES if item["businessSchema"] == name)


def test_real_certificate_table_is_recognised():
    assert classify_table(table([CERTIFICATE_ROW]), SIGNATURES) == "material_certificate_domains"


def test_real_ndt_ratio_table_is_recognised():
    assert classify_table(table([NDT_ROW]), SIGNATURES) == "ndt_plan_items"


@pytest.mark.parametrize(
    "row",
    [
        # 生產庫裡其他真實的未分類表，一張都不該被認成上面兩種。
        {"许可参数": "--", "许可项目": "压力管道设计", "许可子项目": "公用管道(GB2)"},
        {"内容": "PL8306", "项目": "关联管线"},
        {"序号": "一", "材料名称": "管材"},
        {"变更(备案)事项": "企业类型变更", "原登记变更(备案)事项": "有限责任公司"},
        {"序号": "1", "核查项目": "设计/安装资质", "见证资料": "TS证", "完成状态(√/×)": "√"},
    ],
)
def test_unrelated_real_tables_are_left_unlabelled(row):
    assert classify_table(table([row]), SIGNATURES) is None


def test_an_empty_table_is_not_guessed_at():
    assert classify_table(table([]), SIGNATURES) is None


def test_certificate_fields_reach_the_paths_the_criteria_read():
    mapped = map_row(CERTIFICATE_ROW, signature("material_certificate_domains"))
    assert mapped["certificate"]["documentNo"] == "20260213951"
    # 「材质:S30408标准:GB/T14976-2025」必須切開，否則牌號裡混進標準號。
    assert mapped["certificate"]["materialGrade"] == "S30408"


def test_a_column_that_maps_to_nothing_stays_absent_rather_than_guessed():
    row = {key: value for key, value in CERTIFICATE_ROW.items() if key != "材质/标准"}
    mapped = map_row(row, signature("material_certificate_domains"))
    assert "materialGrade" not in mapped["certificate"]


def test_percent_strings_become_numbers_because_the_tool_rejects_strings():
    mapped = map_row(NDT_ROW, signature("ndt_plan_items"))
    assert mapped["ratioPercent"] == 10.0
    assert mapped["objectId"] == "PL8301"


@pytest.mark.parametrize("value", ["约10%", "10~20%", "10", "", "百分之十", "-5%", "120%", True])
def test_a_ratio_that_is_not_a_clean_percentage_is_refused(value):
    mapped = map_row({**NDT_ROW, "检测比例": value}, signature("ndt_plan_items"))
    assert "ratioPercent" not in mapped


def test_domain_rows_carry_the_scope_and_evidence_the_checks_require():
    rows = build_domain_rows(
        table([CERTIFICATE_ROW]),
        signature("material_certificate_domains"),
        project_id="P-2026-GDLNG-002",
        document_version_id="DV-1",
    )
    assert len(rows) == 1
    row = rows[0]
    for key in ("projectId", "objectType", "objectId", "recordVersionId"):
        assert row[key]
    assert row["recordVersionId"] == "DV-1"
    assert row["domain"] == "materialCertificate"
    assert row["applicable"] is True
    assert row["evidenceRefs"] == [
        {"documentVersionId": "DV-1", "pageNo": 3, "tableId": "T1", "rowIndex": 0}
    ]


def test_a_row_with_no_object_identity_produces_nothing():
    rows = build_domain_rows(
        table([{**CERTIFICATE_ROW, "产品质量证明书编号": "  "}]),
        signature("material_certificate_domains"),
        project_id="P1",
        document_version_id="DV-1",
    )
    assert rows == []


def test_the_judgment_booleans_are_still_absent_after_mapping():
    """第 1、2 層補完，第 3 層仍然空著——這是預期的，不是遺漏。"""
    rows = build_domain_rows(
        table([CERTIFICATE_ROW]),
        signature("material_certificate_domains"),
        project_id="P1",
        document_version_id="DV-1",
    )
    certificate = rows[0]["certificate"]
    for judgment in (
        "certificatesAndMarksReviewed",
        "gradeMatchesSpecification",
        "requiredProcessingAndTestsEvidenced",
    ):
        assert judgment not in certificate


def test_signature_headers_are_normalised_across_ocr_punctuation():
    row = {"产品质量证明书编号": "X1", "元件名称 ": "管", "材质／标准": "材质:S1"}
    assert classify_table(table([row]), SIGNATURES) == "material_certificate_domains"
