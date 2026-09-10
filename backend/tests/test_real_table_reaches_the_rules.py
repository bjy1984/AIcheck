"""生產庫裡真實的、沒有 businessSchema 的表，要能一路走到規則手上。

表格內容原樣取自生產庫 ocr_parse_results（2026-09-10 抽出），不是造的。
"""

from copy import deepcopy

from libs.review_document_scope import freeze_document_scope
from libs.review_orchestrator.installation_domain_facts import build_r43_business_facts
from libs.review_orchestrator.ndt_table_facts import read_ndt_tables

CERTIFICATE_ROWS = [
    {
        "厂家": "福建宁德正上管业科技有限公司",
        "序号": "1",
        "元件名称": "不锈钢无缝钢管",
        "材质/标准": "材质:S30408标准:GB/T14976-2025",
        "规格/炉批号": "规格: Φ89×3.0 钢号:06Cr19Ni10(304)",
        "制造许可证编号": "TS2735332-2030",
        "型式试验证书编号": "TSX71101004320260043",
        "产品质量证明书编号": "20260213951",
    }
]


def state_and_run(rows=None, business_schema=None):
    table = {
        "tableId": "MINERU-TABLE-3DCDFCCFEC2D4D1C",
        "pageNo": 1,
        "bbox": [0, 0, 100, 100],
        "structureConfidence": 0.9,
        "normalizedRows": deepcopy(CERTIFICATE_ROWS if rows is None else rows),
    }
    if business_schema:
        table["businessSchema"] = business_schema
    state = {
        "documents": [{"id": "MAT", "projectId": "P1", "tenantId": "T1"}],
        "versions": [{"id": "MAT-V1", "documentId": "MAT", "tenantId": "T1"}],
        "ocr_parse_results": [
            {"documentVersionId": "MAT-V1", "tenantId": "T1", "tables": [table]}
        ],
    }
    run = {"projectId": "P1", "tenantId": "T1", "nodeId": 43, "inputDocumentVersionIds": ["MAT-V1"]}
    run["documentScopeSnapshot"] = freeze_document_scope(run, state)
    return state, run


def test_an_unlabelled_real_table_is_recognised_at_read_time():
    state, run = state_and_run()
    rows = read_ndt_tables(state, run, {"material_certificate_domains": "domains"}, node_id=43)["domains"]
    assert len(rows) == 1
    assert rows[0]["objectId"] == "20260213951"
    assert rows[0]["certificate"]["documentNo"] == "20260213951"
    assert rows[0]["certificate"]["materialGrade"] == "S30408"
    assert rows[0]["recordVersionId"] == "MAT-V1"
    assert rows[0]["evidenceRefs"][0]["documentVersionId"] == "MAT-V1"


def test_the_real_row_reaches_r43_as_a_scoped_domain():
    state, run = state_and_run()
    facts = build_r43_business_facts(state, run)["r43"]["materialCertificate"]
    assert facts["scope"]["objectId"] == "20260213951"
    assert facts["domains"][0]["certificate"]["materialGrade"] == "S30408"
    assert facts["standardRules"]["domains"]["materialCertificate"]["checks"]


def test_a_table_ocr_already_labelled_is_left_alone():
    """既有分類優先；簽名只補 OCR 沒認出來的表，不覆蓋既有結論。"""
    state, run = state_and_run(business_schema="material_certificate_domains")
    rows = read_ndt_tables(state, run, {"material_certificate_domains": "domains"}, node_id=43)["domains"]
    # 走既有分類時原樣讀取，中文列名保留，不經簽名對映。
    assert rows[0]["产品质量证明书编号"] == "20260213951"


def test_an_unrelated_real_table_is_not_dragged_in():
    unrelated = [{"序号": "1", "核查项目": "设计/安装资质", "见证资料": "TS证", "完成状态(√/×)": "√"}]
    state, run = state_and_run(rows=unrelated)
    rows = read_ndt_tables(state, run, {"material_certificate_domains": "domains"}, node_id=43)["domains"]
    assert rows == []
