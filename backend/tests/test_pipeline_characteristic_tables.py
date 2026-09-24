"""設計文件的管道特性表：OCR 只給按行文字或嵌入的 HTML，按簽名逐字認表頭、按格數重建。

版面照七項目快照的真實輸出：7F7270 設計說明書（按行文字、含氣密，25 欄）、6B15AE 設計圖紙
（按行文字，19 欄，後面接圖簽文字）、OCR-002 同一份圖紙的 MinerU HTML 版本。
"""
from __future__ import annotations

import pytest

from libs.ocr.text_line_tables import text_line_tables
from libs.review_orchestrator.pipeline_facts import build_project_pipelines
from libs.review_orchestrator.r14_facts import _extract_pipeline_characteristics, _pipeline_table_signature

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
