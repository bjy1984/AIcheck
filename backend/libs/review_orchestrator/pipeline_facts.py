"""P11 N-02：逐管线事实（横向）——project.pipelines 由设计资料里的"管道特性表"构建。

此前只有 R14 自己从管道特性表抽 pipelineCharacteristics，R04/R06/R07 的四级触发拿到的
project.pipelines 是空的，executor 只能退回到工程级的一条 pipelineGrade（见
executor.project_pipeline_facts），"逐管线判"实际是"整个工程一刀切"。

这里把 R14 的抽取提升为工程级：扫描本工程全部已解析资料（管道特性表通常挂在设计节点，
不在当前节点的输入里），按管线号去重，输出 pipelineId / 级别 / P / T / 材质 / 规格 / 介质
与证据位置，并合并进 businessFacts.project。带 documentScopeSnapshot 的新任务仅扫描固定输入，
并重建管线及级别列表；以下兼容行为只适用于无快照历史任务：
- 已有非空 project.pipelines（例如上游工具已给）不覆盖；
- 同时补 project.pipelineGrades（R01/R02 的 requiredPipelineGrades 用它）。
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from libs.review_input_data import selected_parse_results
from libs.review_orchestrator.certificate_facts import _documents_by_version
from libs.review_orchestrator.r14_facts import _extract_pipeline_characteristics, _value

_PIPELINE_KEYS = (
    "pipelineId",
    "lineNo",
    "pipelineGrade",
    "pressureClass",
    "designPressureMPa",
    "designTemperatureC",
    "minimumTestPressureMPa",
    "material",
)


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    text = str(value).strip().replace("MPa", "").replace("℃", "").replace("°C", "").replace(",", "")
    try:
        return float(text)
    except ValueError:
        return None


def _pipeline_from_characteristic(item: dict[str, Any]) -> dict[str, Any]:
    row = item.get("sourceRow") if isinstance(item.get("sourceRow"), dict) else {}
    pipeline = {key: item.get(key) for key in _PIPELINE_KEYS}
    pipeline["pipelineId"] = str(item.get("pipelineId") or item.get("lineNo") or "").strip()
    pipeline["designPressureMPa"] = _number(item.get("designPressureMPa"))
    pipeline["designTemperatureC"] = _number(item.get("designTemperatureC"))
    pipeline["minimumTestPressureMPa"] = _number(item.get("minimumTestPressureMPa"))
    pipeline["pipelineGrade"] = str(item.get("pipelineGrade") or "").strip().upper() or None
    pipeline["specification"] = _value(row, "specification", "spec", "规格", "规格型号", "公称直径", "DN")
    pipeline["medium"] = _value(row, "medium", "fluid", "介质", "输送介质")
    # 毒性程度与泄漏危害性决定 GC2 管道的检查等级（GB/T 20801.1-2025 8.3.1.3 a）/8.3.1.4 a）：
    # 有毒 → Ⅲ 级、泄漏危害性 → Ⅱ 级，都比缺省的 Ⅳ 级严，对应的体积检测比例也更高。
    pipeline["mediumToxicity"] = _value(row, "mediumToxicity", "toxicity", "毒性程度", "介质毒性")
    pipeline["leakHazard"] = _value(row, "leakHazard", "泄漏危害性", "泄漏危害")
    pipeline["weldingMethod"] = _value(row, "weldingMethod", "焊接方法")
    pipeline["ndtRatio"] = _value(row, "ndtRatio", "检测比例", "无损检测比例")
    pipeline["source"] = {
        "documentVersionId": item.get("documentVersionId"),
        "fileName": item.get("fileName"),
        "pageNo": item.get("pageNo"),
        "tableId": item.get("tableId"),
        "rowIndex": item.get("rowIndex"),
    }
    pipeline["evidence"] = deepcopy(item.get("evidence") or {})
    return pipeline


def _completeness(pipeline: dict[str, Any]) -> int:
    return sum(1 for key in ("pipelineGrade", "designPressureMPa", "designTemperatureC", "material", "specification") if pipeline.get(key) not in (None, ""))


def build_project_pipelines(state: dict[str, Any], project_id: str, *, review_run: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """本工程全部已解析资料里的管道特性表 → 按管线号去重的逐管线事实（信息更全的一行优先）。"""
    if review_run is not None and str(review_run.get("projectId") or "") != project_id:
        raise ValueError("pipeline_review_scope_mismatch")
    versions = _documents_by_version(state, project_id)
    by_line: dict[str, dict[str, Any]] = {}
    parses = (selected_parse_results(state, {}, context={"reviewRun": review_run})
              if review_run is not None else state.get("ocr_parse_results") or [])
    for parse_result in parses:
        if not isinstance(parse_result, dict):
            continue
        version_id = str(parse_result.get("documentVersionId") or "")
        if not version_id or version_id not in versions:
            continue
        for item in _extract_pipeline_characteristics(state, parse_result):
            pipeline = _pipeline_from_characteristic(item)
            if not pipeline["source"].get("fileName"):
                pipeline["source"]["fileName"] = versions[version_id].get("fileName")
            key = pipeline["pipelineId"] or f"{version_id}:{item.get('tableId')}:{item.get('rowIndex')}"
            if not pipeline["pipelineId"]:
                pipeline["pipelineId"] = key
            existing = by_line.get(key)
            if existing is None or _completeness(pipeline) > _completeness(existing):
                by_line[key] = pipeline
    return list(by_line.values())


def merge_project_pipelines(
    state: dict[str, Any], review_run: dict[str, Any], facts: dict[str, Any] | None
) -> dict[str, Any]:
    merged = deepcopy(facts) if isinstance(facts, dict) else {}
    project = merged.get("project") if isinstance(merged.get("project"), dict) else {}
    scoped = "documentScopeSnapshot" in review_run
    if not scoped and isinstance(project.get("pipelines"), list) and project["pipelines"]:
        return merged
    pipelines = build_project_pipelines(state, str(review_run.get("projectId") or ""),
                                       review_run=review_run if scoped else None)
    if not pipelines and not scoped:
        return merged
    project = dict(project)
    project["pipelines"] = pipelines
    project["pipelineCount"] = len(pipelines)
    grades = list(dict.fromkeys(item["pipelineGrade"] for item in pipelines if item.get("pipelineGrade")))
    if scoped or (grades and not project.get("pipelineGrades")):
        project["pipelineGrades"] = grades
    merged["project"] = project
    return merged
