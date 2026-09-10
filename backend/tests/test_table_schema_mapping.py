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
# 生產庫裡形似無損檢測比例表的資料，但追來源後確認是種子資料（tableId 為
# TABLE-PARSE-FDE-*，被掛在焊工資格證等不相干文件下）。這裡留著它，是要釘住
# **不得**因為表頭看起來合理就認出來——沒有對應簽名時就該認不出。
SEEDED_NDT_ROW = {"介质": "天然气", "管道号": "PL8301", "公称直径": "DN100", "检测比例": "10%"}


def table(rows, **extra):
    return {"tableId": "T1", "pageNo": 3, "normalizedRows": rows, **extra}


def signature(name):
    return next(item for item in SIGNATURES if item["businessSchema"] == name)


def test_real_certificate_table_is_recognised():
    assert classify_table(table([CERTIFICATE_ROW]), SIGNATURES) == "material_certificate_domains"


def test_a_table_with_no_signature_is_not_recognised():
    """簽名撤掉之後就該認不出來；表頭再像也不能猜。"""
    assert classify_table(table([SEEDED_NDT_ROW]), SIGNATURES) is None
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


# 百分比解析器目前沒有簽名在用（ndt_plan_items 撤掉了），但程式還在，
# 而且是「不猜」規矩最容易破功的地方，所以直接測它。
PERCENT_SIGNATURE = {
    "businessSchema": "probe",
    "fields": [{"path": "ratioPercent", "columns": ["检测比例"], "parse": "percent"}],
}


def test_a_clean_percentage_becomes_a_number():
    assert map_row({"检测比例": "10%"}, PERCENT_SIGNATURE)["ratioPercent"] == 10.0


@pytest.mark.parametrize(
    "value", ["约10%", "10~20%", "10", "", "百分之十", "-5%", "120%", True, None, "10%%"]
)
def test_anything_that_is_not_a_clean_percentage_is_refused(value):
    """約數和範圍不是數；工具要的是數，猜一個進去比缺著更糟。"""
    assert "ratioPercent" not in map_row({"检测比例": value}, PERCENT_SIGNATURE)
