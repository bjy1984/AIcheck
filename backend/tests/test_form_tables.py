"""掃描件固定表格的重建：只按簽名宣告的表名與表頭，只用 OCR 原字。

版面取自七項目快照裡恒基達鑫交工資料第 16、18 頁的真實片段座標（macOS Vision），
包括 OCR 把相鄰兩格認成一個片段、表尾簽字與日期、同名表頭這些真實情況。
"""

import pytest

from libs.ocr.form_tables import form_tables, reconstruct_form_table
from libs.review_orchestrator.ndt_fact_builders import NDT_FACT_BUILDERS
from libs.review_orchestrator.ndt_table_facts import _signatures
from libs.review_tools.installation_domain_rules import evaluate_r47_static_grounding
from libs.table_schema_mapping import map_row


def _frag(text, x0, y0, x1, y1, confidence=1.0, page=16):
    return {"id": f"F-{page}-{x0}-{y0}", "pageNo": page, "text": text, "bbox": [x0, y0, x1, y1],
            "confidence": confidence}


GROUNDING_PAGE = [
    _frag("表A.0.10管道静电接地测试记录", 191, 73, 408, 92, 0.5),
    _frag("工程编号：/", 76, 119, 126, 133),
    _frag("法兰或螺拴接头", 202, 146, 264, 157), _frag("系统接地", 408, 145, 444, 157, 0.5),
    _frag("管线号", 93, 165, 120, 176), _frag("跨线接头", 211, 166, 248, 178), _frag("接地线", 375, 166, 403, 177),
    _frag("接头型式", 139, 176, 176, 187), _frag("规格", 193, 186, 211, 197), _frag("材质", 244, 186, 263, 197),
    _frag("电阻值", 292, 176, 319, 187), _frag("规格", 352, 186, 370, 197), _frag("材质", 412, 186, 430, 197),
    _frag("对地电阻值", 463, 176, 510, 187),
    _frag("PL8303-100", 75, 206, 122, 217, 0.5), _frag("螺拴接头", 139, 207, 176, 218),
    _frag("M10*25", 186, 207, 218, 217), _frag("不锈钢螺栓", 231, 207, 277, 218), _frag("0.029", 288, 207, 319, 218, 0.3),
    _frag("6mm？", 352, 206, 372, 218, 0.5), _frag("铜芯软绞线", 400, 207, 445, 218), _frag("0.029", 471, 207, 500, 218, 0.3),
    _frag("PL8306-100", 75, 226, 122, 237, 0.5), _frag("螺拴接头", 139, 226, 176, 239),
    _frag("M10*25", 182, 227, 218, 237, 0.5), _frag("不锈钢螺栓", 232, 227, 277, 239), _frag("0.019", 290, 226, 320, 239, 0.3),
    _frag("6mm？", 352, 226, 372, 239, 0.5), _frag("铜芯软绞线", 400, 227, 445, 239), _frag("0.029", 472, 227, 500, 239, 0.3),
    # 表尾：簽字落在行鍵欄的正下方，不能被當成一列。
    _frag("施工人员：王超", 80, 716, 160, 741, 0.3), _frag("2021 年4月1", 422, 736, 508, 749, 0.3),
]

BLOWING_PAGE = [
    _frag("A.0.17管道系统吹扫与清洗检查记录", 180, 71, 417, 91, 0.5, page=18),
    _frag("管道", 144, 141, 164, 151, page=18), _frag("工作", 182, 141, 202, 152, page=18),
    _frag("吹洗", 357, 134, 391, 146, 0.3, page=18), _frag("化学清洗（脱脂）", 449, 134, 521, 146, 0.5, page=18),
    _frag("序号", 66, 144, 84, 157, page=18), _frag("管线号", 99, 146, 127, 157, page=18),
    _frag("等级", 144, 152, 164, 163, page=18), _frag("介质", 182, 152, 200, 163, page=18),
    _frag("起点", 226, 147, 244, 157, page=18), _frag("终点", 271, 146, 295, 158, page=18),
    _frag("压力Mpa", 309, 155, 351, 166, page=18), _frag("介质", 348, 155, 369, 166, page=18),
    _frag("流速M/s", 367, 155, 411, 168, 0.5, page=18), _frag("鉴定", 411, 155, 435, 166, 0.5, page=18),
    _frag("介质", 442, 155, 466, 168, page=18), _frag("方法", 473, 155, 494, 166, page=18),
    _frag("鉴定", 507, 157, 527, 168, page=18),
    _frag("1", 71, 177, 81, 187, page=18), _frag("PL8303-100", 81, 177, 138, 187, 0.5, page=18),
    _frag("MIB", 145, 177, 163, 187, page=18), _frag("化工品", 177, 176, 205, 187, page=18),
    _frag("P8301A|四区交换站", 220, 177, 304, 187, 0.5, page=18), _frag("0.2 洁净水", 310, 177, 373, 188, 0.3, page=18),
    _frag("2", 387, 176, 397, 190, page=18), _frag("合格", 414, 176, 435, 188, page=18),
    _frag("/", 451, 176, 460, 188, 0.5, page=18), _frag("/", 483, 177, 489, 186, 0.5, page=18),
    _frag("/", 515, 177, 521, 187, 0.5, page=18),
    # OCR 把序号与管线号认成一个片段。
    _frag("2 PL8306-100", 71, 196, 138, 207, 0.5, page=18), _frag("MIB", 145, 197, 163, 207, 0.5, page=18),
    _frag("化工品", 177, 196, 207, 207, 0.5, page=18), _frag("P8301B", 220, 197, 252, 207, page=18),
    _frag("四区交换站", 249, 196, 304, 207, 0.5, page=18), _frag("0.2 洁净水", 317, 197, 374, 208, 0.3, page=18),
    _frag("2", 390, 197, 398, 207, page=18), _frag("合格", 416, 196, 435, 208, page=18),
    _frag("/", 451, 196, 460, 208, 0.5, page=18), _frag("/", 483, 197, 489, 206, 0.5, page=18),
    _frag("/", 515, 197, 521, 207, 0.5, page=18),
    _frag("管线复位（含垫片、盲板等）检查：符合要求", 65, 626, 248, 639, 0.5, page=18),
]


def _signature(name):
    return next(item for item in _signatures() if item["businessSchema"] == name)


def _form(name):
    return {**_signature(name)["form"], "id": name}


def test_grounding_record_is_rebuilt_row_by_row_from_the_scanned_page():
    table = reconstruct_form_table(GROUNDING_PAGE, _form("static_grounding_domains"), page_no=16)
    assert [row["管线号"] for row in table["normalizedRows"]] == ["PL8303-100", "PL8306-100"]
    first = table["normalizedRows"][0]
    assert (first["接头型式"], first["跨线接头电阻值"], first["接地线材质"], first["对地电阻值"]) == (
        "螺拴接头", "0.029", "铜芯软绞线", "0.029")
    assert table["normalizedRows"][1]["跨线接头电阻值"] == "0.019"
    # 置信度取整列最低的片段，交給證據門：0.30 會交人工，不會被當成可靠讀數。
    assert first["confidence"] == 0.3
    # 表的範圍不含表尾簽字。
    assert table["pageNo"] == 16 and table["bbox"][3] < 300


def test_quoted_table_uses_only_the_words_printed_on_the_page():
    table = reconstruct_form_table(GROUNDING_PAGE, _form("static_grounding_domains"), page_no=16)
    printed = {fragment["text"] for fragment in GROUNDING_PAGE}
    cells = [cell for cell in table["html"].replace("</td>", "\x00").replace("<td>", "").replace("<tr>", "")
             .replace("</tr>", "").replace("<table>", "").replace("</table>", "").split("\x00") if cell]
    assert cells and all(cell in printed for cell in cells)
    assert "跨线接头电阻值" not in table["html"]


def test_cells_merged_by_ocr_are_split_back_into_their_columns():
    table = reconstruct_form_table(BLOWING_PAGE, _form("blowing_cleaning_domains"), page_no=18)
    rows = table["normalizedRows"]
    assert [row["管线号"] for row in rows] == ["PL8303-100", "PL8306-100"]
    assert rows[1]["序号"] == "2"
    assert (rows[0]["起点"], rows[0]["终点"]) == ("P8301A", "四区交换站")
    assert (rows[0]["吹洗压力Mpa"], rows[0]["吹洗介质"], rows[0]["吹洗鉴定"]) == ("0.2", "洁净水", "合格")
    assert rows[0]["化学清洗介质"] == "/"
    # 表尾那行字落不進管线号欄，也不符合管線號的樣子。
    assert len(rows) == 2


def test_a_missing_header_column_means_no_table_at_all():
    page = [fragment for fragment in GROUNDING_PAGE if fragment["text"] != "对地电阻值"]
    assert reconstruct_form_table(page, _form("static_grounding_domains"), page_no=16) is None


def test_a_page_without_the_form_title_or_with_two_titles_is_not_rebuilt():
    no_title = [fragment for fragment in GROUNDING_PAGE if "静电接地" not in fragment["text"]]
    assert reconstruct_form_table(no_title, _form("static_grounding_domains"), page_no=16) is None
    twice = [*GROUNDING_PAGE, _frag("表A.0.10管道静电接地测试记录", 191, 400, 408, 420)]
    assert reconstruct_form_table(twice, _form("static_grounding_domains"), page_no=16) is None


def test_headers_out_of_the_declared_order_are_not_this_form():
    swapped = [({**fragment, "bbox": [463, 176, 510, 187]} if fragment["text"] == "接头型式"
                else {**fragment, "bbox": [139, 176, 186, 187]} if fragment["text"] == "对地电阻值" else fragment)
               for fragment in GROUNDING_PAGE]
    assert reconstruct_form_table(swapped, _form("static_grounding_domains"), page_no=16) is None


def test_form_tables_only_look_at_signatures_that_declare_a_form():
    found = form_tables({"fragments": GROUNDING_PAGE + BLOWING_PAGE}, _signatures())
    assert sorted((table["pageNo"], signature["businessSchema"]) for table, signature in found) == [
        (16, "static_grounding_domains"), (18, "blowing_cleaning_domains")]


@pytest.mark.parametrize(("value", "expected"), [("0.029", 0.029), ("0.03Ω", 0.03), (" 1 ", 1.0)])
def test_a_clean_number_becomes_a_number(value, expected):
    signature = _signature("static_grounding_domains")
    assert map_row({"对地电阻值": value}, signature)["measurement"]["groundResistanceOhm"] == expected


@pytest.mark.parametrize("value", ["约0.03", "0.02~0.03", "≤0.03", "0.O29", "/", ""])
def test_anything_that_is_not_one_clean_number_is_left_out(value):
    assert map_row({"对地电阻值": value}, _signature("static_grounding_domains")) == {}


def test_a_slash_in_a_form_cell_is_not_a_value():
    mapped = map_row({"吹洗介质": "/", "吹洗鉴定": "合格"}, _signature("blowing_cleaning_domains"))
    assert mapped == {"acceptance": {"conclusion": "合格"}}


def _state(tables=None):
    return {
        "documents": [{"id": "D", "projectId": "P", "tenantId": "T", "fileName": "交工资料.pdf"}],
        "versions": [{"id": "V", "documentId": "D", "tenantId": "T"}],
        "ocr_parse_results": [{"id": "O", "documentVersionId": "V", "tenantId": "T", "status": "success",
                               "fragments": GROUNDING_PAGE, "tables": tables or []}],
    }


def _run(**extra):
    return {"projectId": "P", "tenantId": "T", "nodeId": 47, "reviewMode": "formal",
            "inputDocumentVersionIds": ["V"], "reviewRunId": "RUN", **extra}


def test_two_pipelines_on_one_record_are_not_picked_for_the_reviewer():
    facts = NDT_FACT_BUILDERS[47](_state(), _run())["r47"]["staticGrounding"]
    assert facts["domains"] == [] and facts["sourceIssues"] == ["r47_source_object_conflict"]


def test_selected_pipeline_gets_its_own_values_with_page_and_quote():
    facts = NDT_FACT_BUILDERS[47](_state(), _run(selectedObjectIds=["PL8306-100"]))["r47"]["staticGrounding"]
    (domain,) = facts["domains"]
    assert domain["objectId"] == "PL8306-100" and domain["domain"] == "staticGrounding"
    assert domain["installation"] == {"connectionMethod": "螺拴接头"}
    assert domain["measurement"] == {"maxJointBondingResistanceOhm": 0.019, "groundResistanceOhm": 0.029}
    ref = domain["evidenceRefs"][0]
    assert ref["documentVersionId"] == "V" and ref["pageNo"] == 16 and ref["confidence"] == 0.3
    assert "PL8306-100 | 螺拴接头" in ref["quotedText"]
    # 表上沒寫的接地位置不出現，也不宣告適用：規則維持證據不足，不因多讀了記錄就變嚴或放寬。
    assert "groundingLocation" not in domain["installation"] and "applicable" not in domain
    result = evaluate_r47_static_grounding({"projectId": "P", **{key: facts[key] for key in (
        "scope", "standardRules", "domains", "selectionIssues")}})
    assert [(row["code"], row["result"]) for row in result["facts"]["processChecks"]] == [
        ("staticgrounding_applicability_unknown", "evidence_insufficient")]


def test_an_ocr_table_of_the_same_kind_is_not_read_twice():
    ocr_table = {"tableId": "MINERU-1", "pageNo": 16, "businessSchema": "static_grounding_domains",
                 "html": "<table><tr><td>管线号</td></tr><tr><td>PL8303-100</td></tr></table>",
                 "normalizedRows": [{"projectId": "P", "objectType": "pipeline", "objectId": "PL8303-100",
                                     "recordVersionId": "V", "domain": "staticGrounding"}]}
    facts = NDT_FACT_BUILDERS[47](_state([ocr_table]), _run(selectedObjectIds=["PL8303-100"]))["r47"]["staticGrounding"]
    assert len(facts["domains"]) == 1 and facts["domains"][0]["evidenceRefs"][0]["tableId"] == "MINERU-1"


# 第 17 頁：橫向表格直著掃描，文字由下往上讀（座標取自真實片段，只留表頭與兩列）。
LEAK_PAGE = [
    _frag("A. 0.16管道系统压力试验和泄漏性试验记录", 66, 272, 86, 570, 0.5, page=17),
    _frag("工程名称：恒基达鑫一二期装车站新增两套卸车系统项目", 106, 207, 117, 445, page=17),
    _frag("序号", 319, 760, 332, 782, page=17), _frag("管线号", 319, 716, 332, 746, 0.5, page=17),
    _frag("管道", 314, 673, 326, 695, page=17), _frag("等级", 325, 673, 339, 695, page=17),
    _frag("设计参数", 310, 569, 324, 610, page=17),
    _frag("压力", 329, 637, 342, 659, page=17), _frag("温度", 329, 587, 342, 609, 0.5, page=17),
    _frag("介质", 329, 528, 343, 552, page=17), _frag("起点", 320, 473, 331, 494, page=17),
    _frag("终点", 319, 415, 331, 436, page=17),
    _frag("压力试验", 310, 292, 323, 334, page=17), _frag("压力", 329, 355, 342, 377, page=17),
    _frag("介质", 329, 302, 340, 323, page=17), _frag("结论", 329, 248, 340, 269, 0.5, page=17),
    _frag("泄漏性试验", 309, 121, 321, 171, page=17), _frag("压力", 329, 192, 340, 212, page=17),
    _frag("介质", 329, 132, 340, 153, page=17), _frag("结论", 328, 77, 339, 98, page=17),
    _frag("PL8303-100", 347, 703, 361, 757, page=17), _frag("MIB", 347, 674, 362, 696, 0.5, page=17),
    _frag("0.55Mpa", 347, 626, 362, 668, 0.5, page=17), _frag("50%c", 347, 587, 361, 609, 0.5, page=17),
    _frag("化工品", 347, 524, 361, 555, 0.5, page=17), _frag("P8301A", 348, 467, 359, 500, 0.5, page=17),
    _frag("四区交换站", 347, 400, 359, 449, page=17), _frag("0.825Mpa", 347, 344, 361, 388, 0.5, page=17),
    _frag("洁净水", 347, 295, 359, 327, 0.5, page=17), _frag("合格", 347, 248, 358, 269, page=17),
    _frag("0.55Mpa", 347, 182, 358, 220, 0.5, page=17), _frag("空气", 346, 132, 357, 153, page=17),
    _frag("合格", 346, 78, 357, 98, page=17),
    _frag("PL8306-100", 365, 703, 380, 757, page=17), _frag("MIB", 365, 674, 379, 696, 0.5, page=17),
    _frag("0.55Mpa", 367, 628, 379, 668, 0.5, page=17), _frag("50°c", 365, 587, 379, 609, 0.5, page=17),
    _frag("化工品", 365, 526, 378, 555, page=17), _frag("P8301B", 367, 466, 379, 500, 0.5, page=17),
    _frag("四区交换站", 365, 400, 378, 449, page=17), _frag("0.825Mpa", 365, 344, 379, 388, 0.5, page=17),
    _frag("洁净水", 365, 296, 378, 327, 0.5, page=17), _frag("合格", 365, 248, 376, 269, page=17),
    _frag("0.55Mpa", 365, 182, 378, 221, 0.5, page=17), _frag("空气", 365, 132, 376, 153, page=17),
    _frag("合格", 365, 77, 375, 98, page=17),
]


def test_a_form_scanned_sideways_is_turned_upright_before_reading():
    table = reconstruct_form_table(LEAK_PAGE, _form("leak_test_method_domains"), page_no=17)
    rows = table["normalizedRows"]
    assert [row["管线号"] for row in rows] == ["PL8303-100", "PL8306-100"]
    assert (rows[0]["压力试验压力"], rows[0]["压力试验介质"], rows[0]["压力试验结论"]) == ("0.825Mpa", "洁净水", "合格")
    assert (rows[1]["泄漏性试验压力"], rows[1]["泄漏性试验介质"], rows[1]["泄漏性试验结论"]) == ("0.55Mpa", "空气", "合格")
    # 範圍回到原頁座標：豎排的表頭與兩列，不含表名與工程名稱。
    assert table["bbox"] == [319, 77, 380, 782]


def test_a_sideways_page_is_read_in_the_one_direction_its_headers_allow():
    turned = [{**fragment, "bbox": [500 - fragment["bbox"][2], 860 - fragment["bbox"][3],
                                    500 - fragment["bbox"][0], 860 - fragment["bbox"][1]]} for fragment in LEAK_PAGE]
    # 整頁轉 180° 後文字改成由上往下讀：只有另一個方向對得上，照樣讀出同樣的兩列。
    assert [row["管线号"] for row in reconstruct_form_table(
        turned, _form("leak_test_method_domains"), page_no=17)["normalizedRows"]] == ["PL8303-100", "PL8306-100"]
    mirrored = [{**fragment, "bbox": [500 - fragment["bbox"][2], fragment["bbox"][1],
                                      500 - fragment["bbox"][0], fragment["bbox"][3]]} for fragment in LEAK_PAGE]
    # 左右鏡像後表頭順序兩個方向都對不上：不重建。
    assert reconstruct_form_table(mirrored, _form("leak_test_method_domains"), page_no=17) is None


def test_leak_test_pressure_is_read_only_in_the_declared_unit():
    signature = _signature("leak_test_condition_domains")
    assert map_row({"泄漏性试验压力": "0.55Mpa"}, signature) == {"pressure": {"testPressureMPa": 0.55}}
    assert map_row({"泄漏性试验压力": "550kPa"}, signature) == {}
    assert map_row({"泄漏性试验压力": "0.55"}, signature) == {"pressure": {"testPressureMPa": 0.55}}
