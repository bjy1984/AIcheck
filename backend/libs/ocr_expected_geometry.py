"""OCR 期望值与几何计算。

从 apps/api/routes.py 搬出来的 25 个纯函数：包围盒面积/交并比/排序键、
印章候选打分、期望字段提取，以及业务规则文本的解析与编译。

全是可以拿数字直接验的东西——包围盒 IoU 算错不会报错，只会让「命中率」
这类指标悄悄偏掉。这类代码最该被单测钉住，而埋在三万行路由文件里没人会去测。
"""

from __future__ import annotations

import json
import re
from typing import Any

from libs.fde_console_views import (
    fde_expected_value_present,
)


def parse_rule_node_ids(raw_value: Any, fallback: int | None = None) -> list[int]:
    values: list[Any]
    if isinstance(raw_value, list):
        values = raw_value
    elif isinstance(raw_value, tuple):
        values = list(raw_value)
    elif raw_value is None:
        values = []
    else:
        values = re.split(r"[,，、\s]+", str(raw_value))
    node_ids: list[int] = []
    for value in values:
        if str(value).strip().isdigit():
            node_id = int(str(value).strip())
            if node_id not in node_ids:
                node_ids.append(node_id)
    if not node_ids and fallback is not None:
        node_ids.append(int(fallback))
    return node_ids

def normalize_rule_status(value: Any, default: str = "草稿") -> str:
    raw = str(value or "").strip().lower()
    if raw in {"已发布", "published", "production", "active", "启用"}:
        return "已发布"
    if raw in {"待发布", "candidate", "pending", "ready"}:
        return "待发布"
    if raw in {"已回滚", "rollback", "rolled_back", "retired"}:
        return "已回滚"
    if raw in {"草稿", "draft", ""}:
        return default
    return str(value or default)

def normalize_expected_text(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()

def expected_full_page_bbox(result: dict[str, Any]) -> list[int] | None:
    pages = [item for item in result.get("pages") or [] if isinstance(item, dict)]
    page = pages[0] if pages else {}
    try:
        width = int(float(page.get("width") or page.get("pageWidth") or page.get("imageWidth") or 0))
        height = int(float(page.get("height") or page.get("pageHeight") or page.get("imageHeight") or 0))
    except (TypeError, ValueError):
        width = 0
        height = 0
    if width > 0 and height > 0:
        return [0, 0, width, height]
    return None

def expected_tables_from_result(result: dict[str, Any]) -> list[dict[str, Any]]:
    expected = []
    for table in result.get("tables") or []:
        if not isinstance(table, dict):
            continue
        item: dict[str, Any] = {
            "businessSchema": table.get("businessSchema"),
            "tableId": table.get("tableId"),
            "minRows": int(table.get("rows") or 0),
            "minColumns": int(table.get("columns") or 0),
        }
        rows = table.get("businessRows") or table.get("normalizedRows") or []
        if rows and isinstance(rows[0], dict):
            item["requiredBusinessKeys"] = [key for key, value in rows[0].items() if value not in {None, ""}][:12]
        if table.get("bbox") or table.get("polygon"):
            item["bbox"] = table.get("bbox") or table.get("polygon")
            item["bboxIouThreshold"] = 0.5
        content_markdown = expected_table_content_from_result(table)
        if content_markdown:
            item["contentMarkdown"] = content_markdown
            item["content"] = content_markdown
        expected.append({key: value for key, value in item.items() if fde_expected_value_present(value)})
    return expected[:20]

def expected_table_content_from_result(table: dict[str, Any]) -> str:
    for key in ["contentMarkdown", "markdown", "content"]:
        value = normalize_expected_multiline_text(table.get(key))
        if value:
            return value
    cells = table.get("cells") if isinstance(table.get("cells"), list) else []
    content = expected_table_markdown_from_cells(cells)
    if content:
        return content
    rows = table.get("businessRows") or table.get("normalizedRows") or table.get("dataRows") or []
    content = expected_table_markdown_from_rows(rows)
    if content:
        return content
    return normalize_expected_multiline_text(table.get("text"))

def expected_table_markdown_from_cells(cells: list[Any]) -> str:
    indexed_cells: list[tuple[int, int, str]] = []
    row_values: list[int] = []
    column_values: list[int] = []
    for cell in cells:
        if not isinstance(cell, dict):
            continue
        row_index = expected_table_cell_index(
            cell,
            ["rowIndex", "row", "rowNo", "rowNumber", "rowId", "row_id"],
        )
        column_index = expected_table_cell_index(
            cell,
            [
                "columnIndex",
                "colIndex",
                "column",
                "col",
                "columnNo",
                "colNo",
                "columnId",
                "col_id",
            ],
        )
        if row_index is None or column_index is None:
            continue
        text = expected_table_cell_text(cell)
        row_values.append(row_index)
        column_values.append(column_index)
        indexed_cells.append((row_index, column_index, text))
    if not indexed_cells:
        return ""
    row_offset = 1 if row_values and min(row_values) >= 1 else 0
    column_offset = 1 if column_values and min(column_values) >= 1 else 0
    normalized = [
        (max(0, row - row_offset), max(0, column - column_offset), text)
        for row, column, text in indexed_cells
    ]
    row_count = max(row for row, _, _ in normalized) + 1
    column_count = max(column for _, column, _ in normalized) + 1
    grid = [["" for _ in range(column_count)] for _ in range(row_count)]
    for row, column, text in normalized:
        current = grid[row][column].strip()
        grid[row][column] = " ".join(part for part in [current, text] if part).strip()
    return expected_table_markdown_from_grid(grid)

def expected_table_markdown_from_rows(rows: Any) -> str:
    if not isinstance(rows, list) or not rows:
        return ""
    if all(isinstance(row, dict) for row in rows):
        headers: list[str] = []
        for row in rows:
            for key, value in row.items():
                if key not in headers and fde_expected_value_present(value):
                    headers.append(str(key))
        if not headers:
            return ""
        grid = [headers]
        for row in rows:
            grid.append([normalize_expected_inline_text(row.get(header)) for header in headers])
        return expected_table_markdown_from_grid(grid)
    if all(isinstance(row, list) for row in rows):
        grid = [[normalize_expected_inline_text(cell) for cell in row] for row in rows]
        return expected_table_markdown_from_grid(grid)
    return ""

def expected_table_markdown_from_grid(grid: list[list[str]]) -> str:
    rows = [row for row in grid if any(normalize_expected_inline_text(cell) for cell in row)]
    if not rows:
        return ""
    column_count = max(1, max(len(row) for row in rows))
    normalized_rows = [
        [expected_table_escape_cell(row[index] if index < len(row) else "") for index in range(column_count)]
        for row in rows
    ]
    markdown_rows = [f"| {' | '.join(row)} |" for row in normalized_rows]
    if len(normalized_rows) > 1 and column_count > 1:
        markdown_rows.insert(1, f"| {' | '.join(['---'] * column_count)} |")
    return "\n".join(markdown_rows)

def expected_table_cell_index(cell: dict[str, Any], keys: list[str]) -> int | None:
    for key in keys:
        value = cell.get(key)
        if value is None:
            continue
        try:
            return int(float(value))
        except (TypeError, ValueError):
            continue
    return None

def expected_table_cell_text(cell: dict[str, Any]) -> str:
    for key in ["text", "value", "content", "cellText", "rawText"]:
        value = normalize_expected_inline_text(cell.get(key))
        if value:
            return value
    lines = cell.get("lines") or cell.get("fragments")
    if isinstance(lines, list):
        parts = []
        for line in lines:
            if isinstance(line, dict):
                parts.append(normalize_expected_inline_text(line.get("text") or line.get("value")))
            else:
                parts.append(normalize_expected_inline_text(line))
        return " ".join(part for part in parts if part).strip()
    return ""

def normalize_expected_inline_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return " ".join(normalize_expected_inline_text(item) for item in value).strip()
    if isinstance(value, dict):
        return normalize_expected_inline_text(
            value.get("text") or value.get("value") or json.dumps(value, ensure_ascii=False)
        )
    return re.sub(r"\s+", " ", str(value)).strip()

def normalize_expected_multiline_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return "\n".join(normalize_expected_inline_text(item) for item in value).strip()
    return str(value).strip()

def expected_table_escape_cell(value: Any) -> str:
    return normalize_expected_inline_text(value).replace("|", "/")

def expected_seal_text_from_result(seal: dict[str, Any]) -> str:
    explicit = normalize_expected_text(
        seal.get("text") or seal.get("fullText") or seal.get("rawText") or seal.get("content")
    )
    seal_name = normalize_expected_text(seal.get("sealName"))
    field_lines = []
    for field in seal.get("fields") or []:
        if not isinstance(field, dict):
            continue
        name = normalize_expected_text(field.get("fieldName") or field.get("fieldCode"))
        value = normalize_expected_text(field.get("fieldValue") or field.get("value"))
        if name and value:
            field_lines.append(f"{name}：{value}")
        elif value:
            field_lines.append(value)
    lines: list[str] = []
    for line in [explicit, seal_name if not expected_seal_name_is_placeholder(seal_name) else "", *field_lines]:
        value = normalize_expected_text(line)
        if value and value not in lines:
            lines.append(value)
    return "\n".join(lines)

def expected_seal_fields_from_result(seal: dict[str, Any]) -> list[dict[str, Any]]:
    fields: list[dict[str, Any]] = []
    for field in seal.get("fields") or []:
        if not isinstance(field, dict):
            continue
        name = normalize_expected_text(field.get("fieldCode") or field.get("fieldName"))
        value = normalize_expected_text(field.get("fieldValue") or field.get("value"))
        if not name and not value:
            continue
        item: dict[str, Any] = {
            "fieldName": name,
            "value": value,
            "bbox": field.get("bbox"),
            "minConfidence": field.get("confidence"),
        }
        fields.append({key: val for key, val in item.items() if fde_expected_value_present(val)})
    return fields[:20]

def expected_seal_name_is_placeholder(value: str) -> bool:
    text = value.strip().lower()
    return not text or text.startswith(("视觉", "visual_")) or text in {"蓝章", "红章", "seal", "stamp"}

def expected_seal_candidate_score(candidate: dict[str, Any]) -> float:
    item = candidate.get("item") if isinstance(candidate.get("item"), dict) else {}
    source = candidate.get("source") if isinstance(candidate.get("source"), dict) else {}
    confidence = 0.0
    for key in ["ocrConfidence", "visualConfidence", "confidence", "score"]:
        try:
            confidence = max(confidence, float(source.get(key) or 0))
        except (TypeError, ValueError):
            continue
    score = confidence
    if normalize_expected_text(item.get("text") or item.get("content")):
        score += 0.35
    if normalize_expected_text(item.get("nameContains")) and not expected_seal_name_is_placeholder(
        normalize_expected_text(item.get("nameContains"))
    ):
        score += 0.2
    if expected_bbox_extents(item.get("bbox") or item.get("polygon")):
        score += 0.1
    if item.get("fields"):
        score += 0.1
    flags = {str(flag) for flag in source.get("qualityFlags") or []}
    if "visual_candidate_only" in flags and not normalize_expected_text(item.get("text") or item.get("content")):
        score -= 0.15
    if source.get("sourceEngine") == "fragment_seal_text_fusion":
        score += 0.08
    return score

def expected_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default

def expected_bbox_sort_key(item: dict[str, Any]) -> tuple[float, float]:
    box = expected_bbox_extents(item.get("bbox") or item.get("polygon")) or [0.0, 0.0, 0.0, 0.0]
    return (box[1], box[0])

def expected_bbox_extents(raw: Any) -> list[float] | None:
    if not isinstance(raw, list) or not raw:
        return None
    if len(raw) == 4 and all(isinstance(value, (int, float)) for value in raw):
        x0, y0, x1, y1 = [float(value) for value in raw]
        if x0 == x1 or y0 == y1:
            return None
        return [min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)]
    if len(raw) >= 6 and all(isinstance(value, (int, float)) for value in raw):
        xs = [float(value) for value in raw[0::2]]
        ys = [float(value) for value in raw[1::2]]
        if not xs or not ys or max(xs) <= min(xs) or max(ys) <= min(ys):
            return None
        return [min(xs), min(ys), max(xs), max(ys)]
    points = []
    for point in raw:
        if isinstance(point, (list, tuple)) and len(point) >= 2:
            try:
                points.append((float(point[0]), float(point[1])))
            except (TypeError, ValueError):
                continue
    if not points:
        return None
    return [min(x for x, _ in points), min(y for _, y in points), max(x for x, _ in points), max(y for _, y in points)]

def expected_bbox_iou(left: list[float], right: list[float]) -> float:
    intersection = expected_bbox_intersection_area(left, right)
    if intersection <= 0:
        return 0.0
    left_area = expected_bbox_area(left)
    right_area = expected_bbox_area(right)
    union = left_area + right_area - intersection
    return intersection / union if union > 0 else 0.0

def expected_bbox_overlap_ratio(left: list[float], right: list[float]) -> float:
    intersection = expected_bbox_intersection_area(left, right)
    if intersection <= 0:
        return 0.0
    return intersection / max(min(expected_bbox_area(left), expected_bbox_area(right)), 1.0)

def expected_bbox_intersection_area(left: list[float], right: list[float]) -> float:
    lx0, ly0, lx1, ly1 = left
    rx0, ry0, rx1, ry1 = right
    x0 = max(lx0, rx0)
    y0 = max(ly0, ry0)
    x1 = min(lx1, rx1)
    y1 = min(ly1, ry1)
    if x1 <= x0 or y1 <= y0:
        return 0.0
    return (x1 - x0) * (y1 - y0)

def expected_bbox_area(box: list[float]) -> float:
    return max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1])
