"""表格行過濾：去掉表頭、小標題與空白模板行，只留業務數據行（核心邏輯，不依賴任何插件）。

固定規則永遠生效；審查若選用了表格分類插件（Jev），插件寫在審查任務上的行角色預測
只在「表格內容雜湊一致、表類與行角色把握值都達 0.90」時才採用，否則逐行退回固定規則。
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

CONFIDENCE_FLOOR = 0.90
# 表類選項；插件出題時用同一組鍵（見 jev_tables._TABLE_TYPES）。
TABLE_TYPE_CHOICES = frozenset({"mech_test", "wps_parameters", "welder_certificate", "material_certificate", "other"})

# A narrow, deterministic fallback for the one-cell title/blank-template rows
# seen in WPS tables. It does not rely on a sub-0.90 model prediction.
_SECTION_TITLES = {
    "焊接参数", "焊接工艺参数", "焊接工艺评定", "力学性能", "力学性能试验",
    "拉伸试验", "弯曲试验", "冲击试验", "热处理参数", "热处理工艺参数",
}
_EMPTY_TEMPLATE_MARKERS = {"待填写", "待填", "未填写", "请填写", "空白模板"}


def _obvious_nondata_row(row: dict[str, Any]) -> bool:
    if len(row) < 2:
        return False
    values = [str(value).strip() for value in row.values() if value is not None and str(value).strip()]
    if len(values) != 1:
        return False
    return values[0] in _SECTION_TITLES | _EMPTY_TEMPLATE_MARKERS


def table_hash(table: dict[str, Any]) -> str:
    body = json.dumps(table, sort_keys=True, ensure_ascii=False, default=str, separators=(",", ":"))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def usable_prediction(table: dict[str, Any], prediction: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(prediction, dict) or prediction.get("tableHash") != table_hash(table):
        return None
    table_type = prediction.get("tableType") or {}
    confidence = table_type.get("confidence")
    if table_type.get("choice") not in TABLE_TYPE_CHOICES or not isinstance(confidence, (int, float)) or confidence < CONFIDENCE_FLOOR:
        return None
    return prediction


def business_rows(parse: dict[str, Any], classifications: dict[str, Any] | None,
                  *, skip_mechanical: bool = False) -> list[dict[str, Any]]:
    """Keep only confidently classified data rows; fall back row by row."""
    version_id = str(parse.get("documentVersionId") or "")
    # 預測只由插件步驟寫在伺服器端的審查任務上；逐表再按內容雜湊核對，內容一變就不採用。
    valid_snapshot = classifications if isinstance(classifications, dict) and isinstance(classifications.get("tables"), dict) else {}
    predictions = valid_snapshot.get("tables", {}).get(version_id, [])
    output: list[dict[str, Any]] = []
    for table_index, table in enumerate(parse.get("tables") or [], 1):
        if not isinstance(table, dict):
            continue
        rows = [row for row in table.get("normalizedRows") or table.get("records") or [] if isinstance(row, dict)]
        predicted = next((item for item in predictions if item.get("tableIndex") == table_index
                          and usable_prediction(table, item)), None)
        if skip_mechanical and predicted and predicted["tableType"]["choice"] == "mech_test":
            # Test specimens are not WPS/PQR records, but may be essential to R26 certificates.
            continue
        for row_index, row in enumerate(rows):
            if _obvious_nondata_row(row):
                continue
            role = (predicted.get("rowRoles") or [])[row_index] if predicted and row_index < len(predicted.get("rowRoles") or []) else {}
            confidence = role.get("confidence") if isinstance(role, dict) else None
            if isinstance(role, dict) and role.get("choice") in {"header", "subtitle", "template"} and isinstance(confidence, (int, float)) and confidence >= CONFIDENCE_FLOOR:
                continue
            output.append(row)
    return output
