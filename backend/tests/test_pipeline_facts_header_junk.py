"""表头认错时，不能把垃圾行当成管线。

2026-09-11 全节点扫描实测（P-2026-ECD202，地上甲类储罐区2（含泵区）施工图.pdf）：
MinerU 把这张表的表头认错了一行，列名成了数据值——

    列名: ['BOM A', '0.275', '设计压力', 'GC2', 'M1E', '管路等级', '压力管道级别', ...]
    第一行: {"压力管道级别": "损伤比例", "管路等级": "介质名称", "设计压力": "设计温度", ...}

于是 `设计压力` 这个键底下装的是别的列。老写法只要 lineNo / 压力等级 / 设计压力
任一有值就收下这一行，结果产出 28 条「管线」：管线号、级别、材质全 null，
而 designPressureMPa 是 2/4/6/8/10/12/14/16 的等差数列——那是尺寸或序号列。

这些假管线随后喂给逐管线判定，16MPa 会直接改变管道级别结论。
缺结论只是查不出来，假事实是会把人引到错的结论上去。
"""
from __future__ import annotations

from libs.review_orchestrator.pipeline_facts import build_project_pipelines


def _state(rows: list[dict]) -> dict:
    return {
        "documents": [{"id": "DOC-1", "projectId": "P-1", "currentVersionId": "DV-1", "fileName": "施工图.pdf"}],
        "versions": [{"id": "DV-1", "documentId": "DOC-1"}],
        "ocr_parse_results": [
            {
                "documentVersionId": "DV-1",
                "profileId": "管道特性表",
                "tables": [{"tableId": "T-1", "pageNo": 3, "normalizedRows": rows}],
            }
        ],
    }


def test_没有管线号的行不产出管线():
    """真实形状：表头错位后只有一个数字落在「设计压力」键底下。"""
    junk = [{"设计压力": "2"}, {"设计压力": "4"}, {"设计压力": "6"}, {"压力管道级别": "损伤比例"}]
    assert build_project_pipelines(_state(junk), "P-1") == []


def test_有管线号的行照常产出():
    rows = [
        {"管线号": "LP7103", "管道级别": "GC2", "设计压力": "2.5", "材质": "20", "设计温度": "60"},
        {"管线号": "LP7104", "管道级别": "GC1", "设计压力": "4.0"},
    ]
    pipelines = build_project_pipelines(_state(rows), "P-1")
    assert [item["pipelineId"] for item in pipelines] == ["LP7103", "LP7104"]
    assert [item["pipelineGrade"] for item in pipelines] == ["GC2", "GC1"]
    assert pipelines[0]["material"] == "20"
    # 管线号是身份，不再用「版本:表:行号」合成。
    assert all(":" not in str(item["pipelineId"]) for item in pipelines)


def test_混在一起时只留有管线号的():
    rows = [{"设计压力": "2"}, {"管线号": "LP7103", "管道级别": "GC2"}, {"设计压力": "8"}]
    pipelines = build_project_pipelines(_state(rows), "P-1")
    assert [item["pipelineId"] for item in pipelines] == ["LP7103"]
