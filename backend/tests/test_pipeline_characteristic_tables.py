"""設計文件的管道特性表：OCR 只給按行文字或嵌入的 HTML，按簽名逐字認表頭、按格數重建。

版面照七項目快照的真實輸出：7F7270 設計說明書（按行文字、含氣密，25 欄）、6B15AE 設計圖紙
（按行文字，19 欄，後面接圖簽文字）、OCR-002 同一份圖紙的 MinerU HTML 版本。
"""
from __future__ import annotations

import pytest

from libs.ocr.text_line_tables import text_line_tables
from libs.review_orchestrator.pipeline_facts import build_project_pipelines
from libs.review_orchestrator.r14_facts import (
    _extract_pipeline_characteristics,
    _pipeline_table_signature,
)

DESIGN_NOTE = """管道特性表
管线号 管道名称 管道规格(mm) 介质 改造起止点 设计参数 工作参数 内外防护 试压 气密 无损检测 清洗吹扫介质 管道长度(m) 管道类别 材质
名称 状态 起点 止点 温度°C 压力Mpa 温度°C 压力Mpa 隔热材料 保温厚度(mm) 外防护 介质 压力Mpa 介质 压力Mpa 检测方式 检测比例 合格级别
LS-04012-50-M1B 蒸汽管道 $\\phi 57\\times 4.0$ 蒸汽 汽态 原有管道 V-1110 194 1.25 192 1.2 岩棉 100 铝皮 洁净水 1.88 / / RT ≥5% III 蒸汽 9 GC2 20GB/T8163-2018
LS-0011 蒸汽管道 $\\phi 133\\times 4.5$ 蒸汽 汽态 法兰 法兰 194 1.25 192 1.2 岩棉 100 铝皮 洁净水 1.88 / / RT ≥5% III 蒸汽 / GC2 20GB/T8163-2018"""

DRAWING = """管道特性表
管线号 管道名称 管道规格(mm) 介质 起止点 设计参数 工作参数 内外防护 试压 清洗吹扫介质 管道长度(m) 管道类别
名称 状态 起点 止点 温度°C 压力Mpa 温度°C 压力Mpa 隔热材料 保温厚度(mm) 外防护 介质 压力Mpa
NG-01 氮气管道 Φ108X8 氮气 气态 氮气管网预留口 减压阀 常温 3.0 50 2.3 / / / 洁净水 4.5 压缩空气 400 GC2
珠海盈德气体有限公司
RongGui广东荣贵能源设备科技有限公司 建设单位 珠海新建化工区管道气站项目(华润化学)管道工程"""

DRAWING_HTML = (
    '<table><tr><td colspan="18">管道特性表</td><td></td></tr>'
    '<tr><td rowspan="2">管线号</td><td rowspan="2">管道名称</td><td rowspan="2">管道规格(mm)</td>'
    '<td colspan="2">介质</td><td colspan="2">起止点</td><td colspan="2">设计参数</td><td colspan="2">工作参数</td>'
    '<td colspan="3">内外防护</td><td colspan="2">试压</td><td rowspan="2">清洗吹扫介质</td>'
    '<td rowspan="2">管道长度(m)</td><td rowspan="2">管道类别</td></tr>'
    '<tr><td>名称</td><td>状态</td><td>起点</td><td>止点</td><td>温度°C</td><td>压力Mpa</td><td>温度°C</td>'
    '<td>压力Mpa</td><td>隔热材料</td><td>保温厚度(mm)</td><td>外防护</td><td>介质</td><td>压力Mpa</td></tr>'
    '<tr><td>NG-01</td><td>氮气管道</td><td>Φ108X8</td><td>氮气</td><td>气态</td><td>氮气管网预留口</td>'
    '<td>减压阀</td><td>常温</td><td>3.0</td><td>50</td><td>2.3</td><td>/</td><td>/</td><td>/</td>'
    '<td>洁净水</td><td>4.5</td><td>压缩空气</td><td>400</td><td>GC2</td></tr></table>')


def _parse(text, page=3):
    return {"documentVersionId": "V", "fragments": [{"pageNo": page, "text": text}]}


def test_a_design_note_table_is_rebuilt_row_by_row_with_every_column_in_place():
    (table,) = text_line_tables(_parse(DESIGN_NOTE), _pipeline_table_signature())
    first = table["normalizedRows"][0]
    assert (first["管线号"], first["规格"], first["设计温度"], first["设计压力"], first["试验压力MPa"]) == (
        "LS-04012-50-M1B", "$\\phi 57\\times 4.0$", "194", "1.25", "1.88")
    assert (first["气密介质"], first["检测比例"], first["管道级别"], first["材质"]) == ("/", "≥5%", "GC2", "20GB/T8163-2018")
    assert table["normalizedRows"][1]["管道长度"] == "/"
    # 引文是 OCR 記錄下來的原文行：表名、兩層表頭與兩條管線。
    assert table["contentMarkdown"].splitlines()[0] == "管道特性表" and len(table["contentMarkdown"].splitlines()) == 5


def test_the_title_block_under_a_drawing_table_is_not_a_pipeline():
    (table,) = text_line_tables(_parse(DRAWING), _pipeline_table_signature())
    assert [row["管线号"] for row in table["normalizedRows"]] == ["NG-01"]
    assert table["normalizedRows"][0]["清洗吹扫介质"] == "压缩空气"


def test_the_same_drawing_as_mineru_html_gives_the_same_row():
    (table,) = text_line_tables(_parse(f"前文\n{DRAWING_HTML}\n后文"), _pipeline_table_signature())
    assert table["normalizedRows"] == text_line_tables(_parse(DRAWING), _pipeline_table_signature())[0]["normalizedRows"]
    assert "NG-01" in table["html"]


def test_a_row_whose_cell_count_does_not_match_is_left_out_not_shifted():
    text = DESIGN_NOTE.replace("20GB/T8163-2018\nLS-0011", "20 GB/T8163-2018\nLS-0011")
    (table,) = text_line_tables(_parse(text), _pipeline_table_signature())
    assert [row["管线号"] for row in table["normalizedRows"]] == ["LS-0011"]
    assert table["rejectedRowCount"] == 1


@pytest.mark.parametrize("change", [("管线号 管道名称", "管线编号 管道名称"), ("检测比例", "比例"), ("管道特性表", "管道一览表")])
def test_a_header_that_is_not_a_declared_layout_is_not_read(change):
    assert text_line_tables(_parse(DESIGN_NOTE.replace(*change, 1)), _pipeline_table_signature()) == []


def test_html_rows_with_merged_cells_are_not_read():
    html = DRAWING_HTML.replace("<td>NG-01</td>", '<td rowspan="2">NG-01</td>')
    assert text_line_tables(_parse(html), _pipeline_table_signature()) == []


def test_rebuilt_rows_become_project_pipelines_with_their_source():
    state = {"documents": [{"id": "D", "projectId": "P", "fileName": "设计说明书.pdf", "currentVersionId": "V"}],
             "versions": [{"id": "V", "documentId": "D"}],
             "ocr_parse_results": [{"id": "O", "documentVersionId": "V", "status": "success",
                                    "fragments": [{"pageNo": 3, "text": DESIGN_NOTE}]}]}
    items = _extract_pipeline_characteristics(state, state["ocr_parse_results"][0])
    assert [item["pipelineId"] for item in items] == ["LS-04012-50-M1B", "LS-0011"]
    assert items[0]["evidence"]["pageNo"] == 3 and "LS-04012-50-M1B" in items[0]["evidence"]["quotedText"]
    pipelines = build_project_pipelines(state, "P")
    assert {(item["pipelineId"], item["pipelineGrade"], item["designPressureMPa"], item["minimumTestPressureMPa"])
            for item in pipelines} == {("LS-04012-50-M1B", "GC2", 1.25, 1.88), ("LS-0011", "GC2", 1.25, 1.88)}
    assert pipelines[0]["medium"] == "蒸汽" and pipelines[0]["source"]["fileName"] == "设计说明书.pdf"


def _frag(text, x0, y0, x1, y1, confidence=1.0):
    return {"id": f"S-{x0}-{y0}", "pageNo": 4, "text": text, "bbox": [x0, y0, x1, y1], "confidence": confidence}


# GDLNG 交工資料第 4 頁「压力管道汇总表」：直著掃描，終點「四区交／换站」折成兩行（真實座標）。
SUMMARY_PAGE = [
    _frag("压力管道汇总表", 60, 360, 79, 488), _frag("备注", 125, 51, 138, 77), _frag("（图号）", 137, 46, 149, 84, 0.5),
    _frag("QX201903S", 167, 43, 182, 93, 0.5), _frag("13-Y-07", 181, 43, 197, 87),
    _frag("QX201903S-", 197, 35, 214, 95, 0.5), _frag("13-Y-07", 214, 44, 229, 86),
    _frag("工作条件", 115, 108, 130, 158), _frag("压力", 137, 103, 152, 127), _frag("MPa", 149, 103, 160, 128, 0.5),
    _frag("0.5", 175, 105, 189, 127, 0.5), _frag("0.5", 207, 105, 221, 127, 0.5),
    _frag("温度", 135, 136, 153, 164, 0.5), _frag("常温", 175, 136, 189, 165, 0.5), _frag("常温", 207, 137, 221, 164, 0.5),
    _frag("MPa", 149, 172, 163, 199), _frag("设计条件", 115, 179, 130, 229), _frag("压力", 136, 174, 152, 198),
    _frag("0.55", 172, 174, 191, 199, 0.5), _frag("0.55", 204, 174, 222, 199, 0.3),
    _frag("温度", 136, 208, 152, 234, 0.5), _frag("50", 176, 214, 189, 230), _frag("50", 207, 214, 222, 231),
    _frag("四区交", 167, 246, 182, 283), _frag("四区交", 199, 246, 214, 283, 0.5), _frag("终点", 142, 251, 156, 278),
    _frag("换站", 183, 252, 198, 278, 0.5), _frag("换站", 215, 251, 230, 278, 0.5), _frag("起止点", 115, 270, 130, 307),
    _frag("P8301A", 175, 292, 189, 335), _frag("P8301B", 207, 292, 221, 335), _frag("起点", 142, 300, 156, 327),
    _frag("管道长度", 135, 341, 152, 391), _frag("（m）", 149, 354, 163, 379, 0.5), _frag("101", 176, 356, 188, 377),
    _frag("90", 208, 358, 222, 374), _frag("管道规格", 113, 398, 130, 447), _frag("公称壁厚", 136, 399, 150, 448, 0.5),
    _frag("（mm）", 149, 407, 160, 440, 0.3), _frag("公称直径", 136, 455, 150, 504), _frag("（mm）", 149, 464, 160, 497, 0.3),
    _frag("100", 175, 469, 189, 491), _frag("100", 208, 469, 221, 492),
    _frag("化工品（丙醇）", 175, 509, 189, 585, 0.5), _frag("化工品（丙醇）", 207, 509, 221, 585, 0.5),
    _frag("介质", 131, 535, 145, 563), _frag("材质", 131, 598, 144, 624), _frag("20", 176, 603, 189, 619),
    _frag("20", 208, 603, 221, 619), _frag("管道", 125, 641, 138, 666), _frag("级别", 137, 641, 150, 666),
    _frag("GC2", 175, 640, 189, 667), _frag("GC2", 207, 640, 221, 667), _frag("管道编号", 130, 674, 144, 723),
    _frag("PL8303", 175, 678, 188, 722, 0.5), _frag("PL8306", 207, 678, 221, 722),
    _frag("管道名称", 130, 734, 144, 783), _frag("卸车管线", 175, 734, 189, 784), _frag("卸车管线", 207, 735, 221, 784),
]


def _state_with(fragments):
    return {"documents": [{"id": "D", "projectId": "P", "fileName": "交工资料.pdf", "currentVersionId": "V"}],
            "versions": [{"id": "V", "documentId": "D"}],
            "ocr_parse_results": [{"id": "O", "documentVersionId": "V", "status": "success", "fragments": fragments}]}


def test_a_sideways_summary_table_gives_each_pipeline_with_its_design_conditions():
    pipelines = {item["pipelineId"]: item for item in build_project_pipelines(_state_with(SUMMARY_PAGE), "P")}
    assert set(pipelines) == {"PL8303", "PL8306"}
    first = pipelines["PL8303"]
    assert (first["pipelineGrade"], first["designPressureMPa"], first["designTemperatureC"], first["medium"]) == (
        "GC2", 0.55, 50.0, "化工品（丙醇）")
    assert first["source"]["pageNo"] == 4


def test_a_cell_wrapped_onto_two_lines_is_read_whole_not_cut():
    from libs.ocr.form_tables import form_tables
    from libs.review_orchestrator.r14_facts import _pipeline_form_signatures

    ((table, _signature),) = form_tables({"fragments": SUMMARY_PAGE}, list(_pipeline_form_signatures()))
    assert [row["终点"] for row in table["normalizedRows"]] == ["四区交 换站", "四区交 换站"]
    assert [row["备注"] for row in table["normalizedRows"]] == ["QX201903S 13-Y-07", "QX201903S- 13-Y-07"]


def test_an_html_pipeline_table_is_read_as_rows_not_as_a_drawing_title_block():
    state = _state_with([{"pageNo": 1, "text": DRAWING_HTML}])
    assert [item["pipelineId"] for item in build_project_pipelines(state, "P")] == ["NG-01"]


# ECD202 施工圖第 32 頁：表名夾在圖簽行、「管道等级」是材料等級、備註欄空（OCR 原文節錄）。
TANK_AREA = """广东政和工程有限公司 资质等级 甲级 建设单位 珠海海瑞德制药有限公司 图名DWG NAME 管道特性表 设计分项 2 / 2
项目名称PROJ. 珠海海瑞德制药有限公司增资扩产项目 图号DWG NO. HZ026Y-112-02-S301 设计阶段PHASE 施工图
管段号 外径x壁厚(mm) 管道等级 压力管道类别 介质 工作参数 设计参数 绝热及防腐 试压要求 焊缝检测要求 泄漏试验要求 吹扫清洗介质 备注
名称 相态 特性 起点 终点 温度°C 表压MPa 温度°C 表压MPa 代号 厚度mm 是否防腐 试压介质 试验压力MPa 检验比例% 合格等级
A01-PL-02 Φ89x3.0 M1E GC2 甲醇 液态 可燃 LP7101 ST7101 常温 0.25 60 0.275 - - - 水 0.413 RT10% III级 √ 水
A02-PL-02 Φ89x3.0 M1E GC2 正庚烷 液态 可燃 LP7103 ST7102 常温 0.25 60 0.275 - - - 水 0.413 RT10% III级 √ 水"""

TANK_AREA_HTML = (
    '<table><tr><td>图名</td><td>管道特性表</td></tr>'
    '<tr><td rowspan="2">管段号</td><td rowspan="2">外径x壁厚(mm)</td><td rowspan="2">管道等级</td>'
    '<td rowspan="2">压力管道类别</td><td colspan="5">介质</td><td colspan="2">工作参数</td><td colspan="2">设计参数</td>'
    '<td colspan="2">绝热及防腐</td><td colspan="2">试压要求</td><td colspan="2">焊缝检测要求</td><td>泄漏试验要求</td>'
    '<td rowspan="2">吹扫清洗介质</td><td rowspan="2">备注</td><td></td></tr>'
    '<tr><td>名称</td><td>相态</td><td>特性</td><td>起点</td><td>终点</td><td>温度°C</td><td>表压MPa</td><td>温度°C</td>'
    '<td>表压MPa</td><td>代号</td><td>厚度mm</td><td>是否防腐</td><td>试压介质</td><td>试验压力MPa</td><td>检验比例%</td>'
    '<td>合格等级</td><td></td></tr>'
    '<tr><td>A01-PL-02</td><td>Φ89x3.0</td><td>M1E</td><td>GC2</td><td>甲醇</td><td>液态</td><td>可燃</td><td>LP7101</td>'
    '<td>ST7101</td><td>常温</td><td>0.25</td><td>60</td><td>0.275</td><td>-</td><td>-</td><td>-</td><td>水</td>'
    '<td>0.413</td><td>RT10%</td><td>III级</td><td>√</td><td>水</td><td></td><td></td></tr></table>')


def test_a_drawing_table_whose_title_sits_in_the_title_block_is_read_by_its_headers():
    (table,) = text_line_tables(_parse(TANK_AREA, page=32), _pipeline_table_signature())
    first = table["normalizedRows"][0]
    assert (first["管线号"], first["管道材料等级"], first["管道级别"], first["介质"], first["介质特性"]) == (
        "A01-PL-02", "M1E", "GC2", "甲醇", "可燃")
    assert (first["设计压力"], first["试验压力MPa"], first["泄漏试验要求"], first["清洗吹扫介质"]) == ("0.275", "0.413", "√", "水")
    assert "备注" not in first, "空着的结尾栏不出现，也不把别的值挪进去"
    assert len(table["normalizedRows"]) == 2


def test_the_same_drawing_table_as_html_with_padding_cells_gives_the_same_row():
    (table,) = text_line_tables(_parse(TANK_AREA_HTML, page=1), _pipeline_table_signature())
    row = table["normalizedRows"][0]
    assert (row["管线号"], row["管道级别"], row["介质特性"], row["泄漏试验要求"]) == ("A01-PL-02", "GC2", "可燃", "√")
    assert "备注" not in row, "行尾空着的备注与补位格一样不出现，与按行文字版一致"


def test_headers_alone_without_the_table_name_on_the_page_are_not_read():
    assert text_line_tables(_parse(TANK_AREA.replace("管道特性表", "管道数据"), page=32), _pipeline_table_signature()) == []


def test_material_class_is_not_taken_as_the_pipeline_grade_and_marks_become_flags():
    pipelines = {item["pipelineId"]: item for item in build_project_pipelines(
        _state_with([{"pageNo": 32, "text": TANK_AREA}]), "P")}
    first = pipelines["A01-PL-02"]
    assert (first["pipelineGrade"], first["mediumProperty"], first["leakTestRequired"]) == ("GC2", "可燃", True)
    assert first["designPressureMPa"] == 0.275 and first["minimumTestPressureMPa"] == 0.413


def test_ocr_invented_rows_leave_only_the_conflicting_field_unknown():
    """2026-09-25 ECD202 施工图第 32 页：原图 8 行，OCR 在空白格里又编出 A07/A08 两行（配上 A06 的甲苯），
    整个工程的正式复核因「管线资料冲突」全部失败。现在只把冲突栏位置空交人工，其余照审。"""
    from libs.review_document_scope import freeze_document_scope

    page = TANK_AREA + """
A06-PL-02 Φ89x3.0 M1E GC2 甲苯 液态 可燃 LP7111 ST7106 常温 0.25 60 0.275 - - - 水 0.413 RT10% III级 √ 水
A07-PL-02 Φ89x3.0 M1E GC2 乙酸异丙酯 液态 可燃 LP7113 ST7107 常温 0.25 60 0.275 - - - 水 0.413 RT10% III级 √ 水
A07-PL-02 Φ89x3.0 M1E GC2 甲苯 液态 可燃 LP7111 ST7106 常温 0.25 60 0.275 - - - 水 0.413 RT10% III级 √ 水"""
    state = _state_with([{"pageNo": 32, "text": page}])
    run = {"projectId": "P", "nodeId": 1, "inputDocumentVersionIds": ["V"]}
    run["documentScopeSnapshot"] = freeze_document_scope(run, state)
    pipelines = {item["pipelineId"]: item for item in build_project_pipelines(state, "P", review_run=run)}
    assert set(pipelines) == {"A01-PL-02", "A02-PL-02", "A06-PL-02", "A07-PL-02"}
    assert pipelines["A07-PL-02"]["medium"] is None
    assert [item["field"] for item in pipelines["A07-PL-02"]["fieldConflicts"]] == ["medium"]
    assert pipelines["A07-PL-02"]["designPressureMPa"] == 0.275, "没冲突的栏位照常"
    assert pipelines["A06-PL-02"]["medium"] == "甲苯" and "fieldConflicts" not in pipelines["A06-PL-02"]
