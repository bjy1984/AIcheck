"""材料／元件记录的身份字段：不拿表头、整张表、别的当事方或标签残留当值。

2026-09-23 本地七项目快照上，Jev 事实核对与本地合理性检查暴露：
- R16 元件核查记录：证书编号＝「监督检验证书编号 产品质量证明书编号」（表头），
  产品名称＝一串栏目名，生产厂家＝整张表；表格行里正确的值被文档级垃圾压过。
- R16/R21 质量证明书：生产厂家＝「需方单位:佛山市佛润钢铁有限公司」（买方）。
- R13 型式试验证书：产品名称＝「（品种） 无缝钢管」，制造单位＝「名称 云南…有限公司」。
"""
from __future__ import annotations

from apps.ocr_service.service import quality_certificate_manufacturer
from libs.review_orchestrator.material_facts import extract_quality_certificates
from libs.review_orchestrator.r13_facts import _common_document_fields, _labeled_value


def _state(fields, fragments, tables=()):
    return {"documents": [{"id": "D", "projectId": "P", "fileName": "核查记录.pdf"}],
            "versions": [{"id": "V", "documentId": "D"}],
            "ocr_parse_results": [{"documentVersionId": "V", "status": "success", "fields": list(fields),
                                   "fragments": [{"pageNo": 1, "text": text} for text in fragments],
                                   "tables": list(tables)}]}


def test_table_row_values_win_over_header_text_captured_at_document_level():
    header = "序号 元件名称 材质/标准 规格/炉批号 厂家 产品质量证明书编号"
    table = {"tableId": "T", "headers": header.split(),
             "normalizedRows": [{"序号": "1", "元件名称": "不锈钢无缝钢管", "材质/标准": "材质:S30408",
                                 "规格/炉批号": "规格:DN80", "厂家": "福建宁德正上管业科技有限公司",
                                 "产品质量证明书编号": "20260213951"}]}
    fields = [{"fieldCode": "manufacturer", "fieldName": "生产厂家", "fieldValue": f"常用管道元件核查记录\n{header}"}]
    state = _state(fields, ["常用管道元件核查记录", f"{header.replace('产品质量证明书编号', '监督检验证书编号 产品质量证明书编号')}"],
                   [table])
    records = extract_quality_certificates(state, state["ocr_parse_results"][0])
    assert [(r.get("certificateNo"), r.get("productName"), r.get("manufacturerName")) for r in records] == [
        ("20260213951", "不锈钢无缝钢管", "福建宁德正上管业科技有限公司")]


def test_other_party_is_never_the_manufacturer():
    assert (quality_certificate_manufacturer([("需方单位:佛山市佛润钢铁有限公司", {}), ("产品质量证明书", {})]) is None)
    assert quality_certificate_manufacturer([("生产厂家：示例钢管制造有限公司", {})])["text"] == "示例钢管制造有限公司"
    assert quality_certificate_manufacturer([("常用管道元件核查记录\n序号 元件名称 厂家\n1 钢管 示例钢管制造有限公司", {})]) is None
    stored = [{"fieldCode": "manufacturer", "fieldName": "生产厂家", "fieldValue": "需方单位:佛山市佛润钢铁有限公司"}]
    common, _items = _common_document_fields(_state(stored, ["产品质量证明书"]), _state(stored, ["产品质量证明书"])["ocr_parse_results"][0])
    assert "manufacturer" not in common


def test_label_residue_and_sentences_are_not_values():
    assert _labeled_value("产品名称（品种） 无缝钢管", ("产品名称",)) == "无缝钢管"
    assert _labeled_value("制造单位名称 云南曲靖钢铁集团凤凰钢铁有限公司", ("制造单位",)) == "云南曲靖钢铁集团凤凰钢铁有限公司"
    assert _labeled_value("制造单位有责任保证产品符合安全技术规范", ("制造单位",)) is None


def test_numbers_inside_html_cells_are_kept_and_header_cells_dropped():
    fields = [{"fieldCode": "certificateNo", "fieldValue": "</td><td>ST2026051706G002</td></tr><tr><td>本批"},
              {"fieldCode": "batchNo", "fieldValue": 'LotNo.</td><td rowspan="3">牌号SteelGrade</td>'},
              {"fieldCode": "productName", "fieldValue": "</td><td>公称压力</td><td>公称尺寸</td>"}]
    state = _state(fields, ["质量证明书"])
    common, _items = _common_document_fields(state, state["ocr_parse_results"][0])
    assert common.get("certificateNo") == "ST2026051706G002"
    assert "batchNo" not in common and "productName" not in common
