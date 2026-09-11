"""单线图图签：标签、值横着排，整张表只描述一条管线。

2026-09-11 生产实测（地上甲类储罐区2（含泵区）施工图.pdf）：表格解析把图签第一行当成表头，
「设计压力」这个键底下装的是别的列，按行读出 28 条假管线（设计压力 2/4/6/…/16 等差数列）。
真实信息干净地摆在格子里——一条管线 LP7103→ST7102、压力管道级别 GC2、设计压力 0.275、
设计温度 60°C。这里按格子读，标签后面那一格就是它的值。
"""
from __future__ import annotations

from libs.review_orchestrator.pipeline_facts import build_project_pipelines


def _cell(row: int, col: int, text: str) -> dict:
    return {"row": row, "col": col, "text": text, "colspan": 1, "rowspan": 1}


def _real_title_block_cells() -> list[dict]:
    """按生产那张表的 cells 原样复刻前两行 + 材料表的表头行与一行数据。"""
    row0 = ["设计压力", "0.275", "操作压力", "0.413", "管路起点", "LP7103", "管路等级", "M1E", "压力管道级别", "GC2", "BOM A"]
    row1 = ["设计温度", "60°C", "操作温度", "常温", "管路终点", "ST7102", "介质名称", "王虎悦", "损伤比例", "RT10%", "PIPE"]
    row2 = ["C-1", "2025.04", "ID", "黄红描述", "DN", "数量", "材质", "说明"]
    row3 = ["", "", "1", "无缝钢管", "25", "0.7M", "S30408", "无缝钢管,SMLS,PL,系列II,GB/T 16/976"]
    cells = []
    for r, row in enumerate((row0, row1, row2, row3)):
        cells.extend(_cell(r, c, text) for c, text in enumerate(row) if text)
    return cells


def _state(tables: list[dict]) -> dict:
    return {
        "documents": [{"id": "DOC-1", "projectId": "P-1", "currentVersionId": "DV-1", "fileName": "施工图.pdf"}],
        "versions": [{"id": "DV-1", "documentId": "DOC-1"}],
        "ocr_parse_results": [
            {"documentVersionId": "DV-1", "profileId": "管道特性表", "tables": tables}
        ],
    }


def _junk_normalized_rows() -> list[dict]:
    """表头认错后的 normalizedRows：数值落在「设计压力」键底下。"""
    return [{"设计压力": str(n)} for n in (2, 4, 6, 8)]


def test_图签整张表只产出一条管线():
    table = {"tableId": "T-1", "pageNo": 3, "cells": _real_title_block_cells(), "normalizedRows": _junk_normalized_rows()}
    pipelines = build_project_pipelines(_state([table]), "P-1")
    assert len(pipelines) == 1, pipelines
    line = pipelines[0]
    assert line["pipelineId"] == "LP7103→ST7102"
    assert line["pipelineGrade"] == "GC2"
    assert line["designPressureMPa"] == 0.275
    assert line["designTemperatureC"] == 60
    assert line["medium"] == "王虎悦"  # 图上就这么写的（OCR 对错位），照抄不替人改
    assert line["ndtRatio"] == "RT10%"
    # 材料表表头「…材质 | 说明」只有一个已知标签，不是图签行；「说明」不能变成材质。
    assert line["material"] is None
    assert "LP7103" in line["evidence"]["quotedText"] and "GC2" in line["evidence"]["quotedText"]
    # 材料表那几行不是管线。
    assert all(":" not in str(item["pipelineId"]) for item in pipelines)


def test_没有cells时按html拆格子():
    html = (
        "<table><tr><td>设计压力</td><td>0.275</td><td>管路起点</td><td>LP7103</td>"
        "<td>压力管道级别</td><td>GC2</td></tr>"
        "<tr><td>设计温度</td><td>60°C</td><td>管路终点</td><td>ST7102</td></tr></table>"
    )
    table = {"tableId": "T-2", "pageNo": 1, "html": html, "normalizedRows": _junk_normalized_rows()}
    pipelines = build_project_pipelines(_state([table]), "P-1")
    assert [item["pipelineId"] for item in pipelines] == ["LP7103→ST7102"]
    assert pipelines[0]["pipelineGrade"] == "GC2"


def test_标签不够三个不算图签():
    cells = [_cell(0, 0, "设计压力"), _cell(0, 1, "0.275"), _cell(0, 2, "备注"), _cell(0, 3, "无")]
    table = {"tableId": "T-3", "pageNo": 1, "cells": cells, "normalizedRows": _junk_normalized_rows()}
    assert build_project_pipelines(_state([table]), "P-1") == []


def test_配不出身份就不产出():
    """有级别有压力，但既没管线号也没起止点——没有身份的管线不能凭空造一个。"""
    cells = [
        _cell(0, 0, "设计压力"), _cell(0, 1, "0.275"),
        _cell(0, 2, "压力管道级别"), _cell(0, 3, "GC2"),
        _cell(0, 4, "设计温度"), _cell(0, 5, "60°C"),
    ]
    table = {"tableId": "T-4", "pageNo": 1, "cells": cells}
    assert build_project_pipelines(_state([table]), "P-1") == []


def test_有管线号时优先用管线号():
    cells = [
        _cell(0, 0, "管线号"), _cell(0, 1, "LP7103"),
        _cell(0, 2, "管路起点"), _cell(0, 3, "A"),
        _cell(0, 4, "管路终点"), _cell(0, 5, "B"),
        _cell(0, 6, "压力管道级别"), _cell(0, 7, "GC1"),
    ]
    table = {"tableId": "T-5", "pageNo": 1, "cells": cells}
    pipelines = build_project_pipelines(_state([table]), "P-1")
    assert [item["pipelineId"] for item in pipelines] == ["LP7103"]
    assert pipelines[0]["pipelineGrade"] == "GC1"
