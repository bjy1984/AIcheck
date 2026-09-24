"""Optional whole-document table/row classifier for the review worker.

The fixed parser remains the fallback for low confidence, unavailable Jev, and
unapproved data egress. Predictions are tied to exact table content hashes so
an OCR change cannot silently reuse stale row labels.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from libs.review_input_data import latest_selected_parses
from libs.review_orchestrator.jev_client import MODEL, ask_jev, jev_stage_enabled
from libs.review_orchestrator.jev_state import scoped_document_states
from libs.review_orchestrator.table_rows import (  # noqa: F401 -- 舊呼叫方相容
    CONFIDENCE_FLOOR,
    TABLE_TYPE_CHOICES,
    business_rows,
    table_hash,
    usable_prediction,
)
from libs.review_plugins.settings import run_plugin_enabled

_TABLE_TYPES = {
    "mech_test": "力学性能或拉伸、弯曲、冲击等试验结果表",
    "wps_parameters": "焊接工艺参数表，记录电流、电压、焊速、层间温度等",
    "welder_certificate": "焊工证或焊工名册表",
    "material_certificate": "材料或焊材质量证明书表",
    "other": "其他类型，或无法从原文确定",
}
_ROW_ROLES = {
    "header": "用来命名多列的表头，例如项目、数值、单位等列名；不是业务数据",
    "data": "已填写的具体业务记录，有对象、参数或结果值",
    "subtitle": "表内分组或章节标题；通常只有一个标题单元格有字，其余单元格为空，不表示已填写记录",
    "template": "待填写的空白模板或占位符；没有实际对象、参数或结果值",
}

def classify_review_tables(state: dict[str, Any], review_run: dict[str, Any]) -> dict[str, Any]:
    if int(review_run.get("nodeId") or 0) not in range(24, 35):
        return {"model": MODEL, "status": "not_applicable", "tables": {}, "overlongDocumentVersionIds": []}
    if not jev_stage_enabled("TABLE_CLASSIFICATION"):
        return {"model": MODEL, "status": "disabled", "tables": {}, "overlongDocumentVersionIds": []}
    # 这次审查选用了 Jev 插件（建立时冻结）才外发；没有快照的旧审查沿用原白名单。
    if not run_plugin_enabled(review_run, "jev"):
        return {"model": MODEL, "status": "project_not_approved_for_jev", "tables": {},
                "overlongDocumentVersionIds": []}
    document_states, conflicts, overlong = scoped_document_states(state, review_run, [])
    state_by_version = {row["documentVersionId"]: row["state"] for row in document_states if row["hasOcrText"]}
    output: dict[str, Any] = {"model": MODEL, "status": "completed", "tables": {},
                              "overlongDocumentVersionIds": overlong, "factConflicts": conflicts}
    for parse in latest_selected_parses(state, review_run, set(state_by_version)).values():
        version_id = str(parse.get("documentVersionId") or "")
        full_text = state_by_version.get(version_id)
        if not full_text:
            continue
        for table_index, table in enumerate(parse.get("tables") or [], 1):
            if not isinstance(table, dict):
                continue
            rows = [row for row in table.get("normalizedRows") or table.get("records") or [] if isinstance(row, dict)]
            if not rows:
                continue
            question_items = [("table_type", {"type": "choice", "instructions":
                               f"仅根据本文件全文，表格 {table_index} 本身是什么类型？不要因为正文提到 WPS 就把力学性能表归为 WPS 参数。",
                               "criteria": _TABLE_TYPES})]
            question_items.extend((f"row_{index}", {"type": "choice", "instructions":
                                   f"结合本文件全文，判断表格 {table_index} 第 {index} 行的角色。"
                                   f"该行内容：{json.dumps(row, ensure_ascii=False, sort_keys=True)}。"
                                   "不要把只有一个标题单元格有字、其余为空的小标题当作已填写业务记录。",
                                   "criteria": _ROW_ROLES}) for index, row in enumerate(rows, 1))
            answers: dict[str, Any] = {}
            try:
                for start in range(0, len(question_items), 50):
                    batch = dict(question_items[start:start + 50])
                    answers.update(ask_jev(full_text, batch))
            except (OSError, ValueError, RuntimeError) as exc:
                # Review remains available using the existing OCR heuristics.
                logging.getLogger(__name__).warning("Jev table classification fallback: %s", type(exc).__name__)
                continue
            prediction = {"tableHash": table_hash(table), "tableIndex": table_index,
                          "tableType": answers["table_type"],
                          "rowRoles": [answers[f"row_{index}"] for index in range(1, len(rows) + 1)]}
            output["tables"].setdefault(version_id, []).append(prediction)
    return output


assert set(_TABLE_TYPES) == TABLE_TYPE_CHOICES, "表類選項要與核心 table_rows 一致"
