"""Join wrapped report numbers only inside a detected closed table cell."""
import math
import re
from copy import deepcopy
from itertools import pairwise


def _rect(value):
    if not isinstance(value, list) or len(value) != 4:
        return None
    if any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) for x in value):
        return None
    return value if value[0] < value[2] and value[1] < value[3] else None


def _inside(outer, inner):
    return outer[0] <= inner[0] and outer[1] <= inner[1] and inner[2] <= outer[2] and inner[3] <= outer[3]


def _parts(result, table, cell):
    box = _rect(cell.get("bbox"))
    if box is None:
        return []
    parts = []
    for row in result.get("fragments", []):
        if not isinstance(row, dict) or row.get("pageNo") != table.get("pageNo") or row.get("coordinateSystem") != "pixel":
            continue
        bounds = _rect(row.get("bbox"))
        if bounds is None:
            continue
        overlaps = max(box[0], bounds[0]) < min(box[2], bounds[2]) and max(box[1], bounds[1]) < min(box[3], bounds[3])
        if overlaps and not _inside(box, bounds):
            return []  # A crossing fragment makes cell membership ambiguous.
        if _inside(box, bounds):
            confidence = row.get("confidence")
            if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not .75 <= confidence <= 1:
                return []
            if not isinstance(row.get("text"), str) or not row["text"].strip():
                return []
            parts.append(row)
    return sorted(parts, key=lambda row: (row["bbox"][1], row["bbox"][0]))


def extract_closed_cell_report_number(result, append_field):
    candidates = []
    for table in result.get("tables", []):
        if (not isinstance(table, dict) or table.get("sourceEngine") != "opencv_table_grid_subprocess"
                or table.get("closedCellsCoordinateSystem") != "pixel"
                or not _rect(table.get("closedCellsTableBBox")) or table.get("closedCellsTableBBox") != table.get("bbox")
                or table.get("coordinateTransform") or table.get("coordinateSystem") not in (None, "pixel")
                or isinstance(table.get("pageNo"), bool) or not isinstance(table.get("pageNo"), int) or table["pageNo"] <= 0):
            continue
        cells = [cell for cell in table.get("closedCells", []) if isinstance(cell, dict) and _rect(cell.get("bbox"))]
        for label in cells:
            parts = _parts(result, table, label)
            if len(parts) != 1 or parts[0]["text"].strip().rstrip(":：") not in {"报告编号", "报告号"}:
                continue
            left = label["bbox"]
            adjacent = []
            for cell in cells:
                right = cell["bbox"]
                overlap = min(left[3], right[3]) - max(left[1], right[1])
                height = min(left[3] - left[1], right[3] - right[1])
                if 0 <= right[0] - left[2] <= height * .15 and overlap >= height * .8:
                    adjacent.append(cell)
            if len(adjacent) != 1:
                continue
            cell = adjacent[0]
            values = _parts(result, table, cell)
            if not values or any(not re.fullmatch(r"[A-Za-z0-9/-]+", row["text"].strip()) for row in values):
                continue
            # Only vertically separate lines; do not concatenate parallel values.
            if any(a["bbox"][3] > b["bbox"][1] for a, b in pairwise(values)):
                continue
            text = "".join(row["text"].strip() for row in values)
            if len(text) > 100 or not re.search(r"\d", text):
                continue
            candidates.append((text, table, cell, values))
    if not candidates:
        return
    existing = [row for row in result.get("fields", []) if isinstance(row, dict) and row.get("fieldCode") == "report_no"]
    if len({candidate[0] for candidate in candidates} | {row.get("fieldValue") for row in existing}) != 1:
        for row in existing:
            row["qualityFlags"] = sorted({*(row.get("qualityFlags") or []), "field_value_conflict"})
        result.setdefault("diagnostics", []).append({"code": "NDT_REPORT_CELL_CONFLICT", "level": "warning",
            "message": "不同位置的报告编号不一致，请核对原文。", "fieldCode": "report_no"})
        return
    if existing or len(candidates) != 1:
        return
    text, table, cell, values = candidates[0]
    fragment = {**values[0], "bbox": cell["bbox"], "confidence": min(row["confidence"] for row in values),
                "qualityFlags": sorted({"layout_join_requires_source_review", *(flag for row in values for flag in row.get("qualityFlags", []))})}
    append_field(result, "report_no", "报告编号", {"text": text, "fragment": fragment})
    field = next(row for row in result["fields"] if row["fieldCode"] == "report_no")
    field.update(extractionMethod="closed_cell_line_join", sourceFragments=deepcopy(values),
                 sourceTableId=table.get("tableId"), sourceCellId=cell.get("cellId"))
