from __future__ import annotations

import hashlib
import json
import math
import os
import re
import unicodedata
from copy import deepcopy
from typing import Any, Iterable


EVIDENCE_PRIOR_VERSION = "EvidencePrior@2"
DEFAULT_DOCUMENT_AI_PROFILE_ALLOWLIST = (
    "ndt_rt_report_v1",
    "quality_certificate_v1",
    "engineering_drawing_list_v1",
    "piping_characteristic_list_v1",
    "comprehensive_material_list_v1",
)
DEFAULT_MAX_CANDIDATES = 64
DEFAULT_MAX_PRIOR_TOKENS = 12_000
DEFAULT_MAX_PAGES = 6

_GRANULARITY_RANK = {
    "field": 0,
    "table_cell": 1,
    "text_line": 2,
    "seal_crop": 3,
    "table_block": 4,
    "layout_block": 5,
    "signature_visual": 6,
}
_CANDIDATE_PRIORITY = {
    "field": 500,
    "table_cell": 400,
    "text_line": 300,
    "seal_crop": 250,
    "table_block": 120,
    "layout_block": 80,
    "signature_visual": 40,
}
_FORMAL_BLOCKING_FLAGS = {
    "direct_vision_only",
    "visual_only",
    "visual_seal_candidate",
    "whole_table_bbox",
    "document_coordinate_unmapped",
}
_FIELD_LABEL_ALIASES = {
    "company_name": ("单位名称", "公司名称", "设计单位"),
    "project_name": ("项目名称", "工程名称"),
    "document_title": ("文件名称", "图纸名称", "标题"),
    "drawing_no": ("图号", "图纸编号"),
    "design_phase": ("设计阶段", "阶段"),
    "pipe_no": ("管线号", "管道号", "管号"),
    "pipeline_class": ("管道级别", "管道类别", "级别", "CLASS"),
    "medium": ("介质", "介质名称", "MEDIUM"),
    "design_pressure": ("设计压力", "P.(MPAG)", "DESIGN PRESSURE"),
    "design_temperature": ("设计温度", "T.(℃)", "DESIGN TEMPERATURE"),
    "strength_test": ("强度试验", "强度试验压力", "STRENGTH TEST"),
    "leak_test": ("严密性试验", "泄漏试验", "气密性试验", "TIGHTNESS TEST"),
    "detection_method": ("检测方法", "检测方式", "D. METHOD"),
    "detection_ratio": ("检测比例", "检测数量", "抽检比例", "D. SCALE", "D. SEALE"),
    "technical_grade": ("技术等级", "RANKING", "RANKIG"),
    "evaluation_level": ("评定级别", "合格级别", "验收等级", "ELIGIBLE L.", "ELEGIBLE L."),
    "film_model": ("胶片型号", "胶片牌号"),
    "intensifying_screen_thickness": ("增感屏厚度",),
    "report_no": ("报告编号", "报告号"),
    "certificate_no": ("证书编号", "质量证明书号"),
}
_HIGH_VALUE_CELL_RE = re.compile(
    r"(?:\bGC[12D]\b|\b(?:RT|UT|MT|PT|TOFD)\b|\b(?:AB|III|II|IV)\b|\d+(?:\.\d+)?\s*(?:%|MPA|KPA|MM|℃|°C))",
    re.IGNORECASE,
)


def document_ai_mode() -> str:
    mode = str(os.getenv("AICHECK_DOCUMENT_AI_MODE") or "off").strip().lower()
    return mode if mode in {"off", "shadow"} else "off"


def document_ai_profile_allowlist() -> set[str]:
    configured = str(os.getenv("AICHECK_DOCUMENT_AI_PROFILE_ALLOWLIST") or "").strip()
    if not configured:
        return set(DEFAULT_DOCUMENT_AI_PROFILE_ALLOWLIST)
    return {item.strip() for item in configured.split(",") if item.strip()}


def document_ai_shadow_enabled(profile_id: str | None) -> bool:
    return document_ai_mode() == "shadow" and bool(profile_id) and str(profile_id) in document_ai_profile_allowlist()


def stable_payload_hash(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def estimate_json_tokens(value: Any) -> int:
    """Return a deliberately conservative token estimate for mixed Chinese/ASCII JSON."""
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    return max(1, math.ceil(len(raw.encode("utf-8")) / 3))


def normalize_bbox(value: Any) -> list[float] | None:
    if not isinstance(value, (list, tuple)) or len(value) < 4:
        return None
    try:
        bbox = [float(value[index]) for index in range(4)]
    except (TypeError, ValueError):
        return None
    x1, y1, x2, y2 = bbox
    if not all(math.isfinite(item) for item in bbox) or x2 <= x1 or y2 <= y1:
        return None
    return [round(x1, 4), round(y1, 4), round(x2, 4), round(y2, 4)]


def bbox_union(boxes: Iterable[Any]) -> list[float] | None:
    normalized = [item for item in (normalize_bbox(value) for value in boxes) if item]
    if not normalized:
        return None
    return [
        min(item[0] for item in normalized),
        min(item[1] for item in normalized),
        max(item[2] for item in normalized),
        max(item[3] for item in normalized),
    ]


def _text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return round(max(0.0, min(1.0, result)), 4) if math.isfinite(result) else None


def _int(value: Any, default: int = 1) -> int:
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return default


def _quality_flags(item: dict[str, Any]) -> list[str]:
    flags = item.get("qualityFlags") if isinstance(item.get("qualityFlags"), list) else []
    return sorted({str(flag) for flag in flags if str(flag).strip()})


def _source_engine(item: dict[str, Any]) -> str:
    return str(item.get("sourceEngine") or item.get("ocrEngine") or item.get("engine") or "unknown")


def _candidate_id(kind: str, payload: dict[str, Any]) -> str:
    digest = stable_payload_hash({"kind": kind, **payload}).split(":", 1)[1][:14].upper()
    return f"EP2-{kind.upper()}-{digest}"


def _candidate(
    kind: str,
    item: dict[str, Any],
    *,
    text: Any,
    page_no: Any,
    semantic_key: str | None = None,
    table_id: str | None = None,
    row: Any = None,
    col: Any = None,
    source_id: Any = None,
    formal_eligible: bool | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    normalized_text = _text(text)
    bbox = normalize_bbox(item.get("bbox"))
    polygon = item.get("polygon") if isinstance(item.get("polygon"), list) else None
    if not normalized_text and kind not in {"layout_block", "signature_visual"}:
        return None
    page = _int(page_no)
    flags = _quality_flags(item)
    source_engine = _source_engine(item)
    visual_only = (
        kind in {"layout_block", "signature_visual", "table_block"}
        or source_engine in {"visual_seal_candidate_subprocess", "direct_vision", "visual_review"}
        or bool(_FORMAL_BLOCKING_FLAGS.intersection(flags))
    )
    if formal_eligible is None:
        formal_eligible = bool(normalized_text and bbox and not visual_only)
    identity = {
        "pageNo": page,
        "sourceId": str(source_id or ""),
        "semanticKey": str(semantic_key or ""),
        "tableId": str(table_id or ""),
        "row": row,
        "col": col,
        "text": normalized_text,
        "bbox": bbox,
    }
    output = {
        "candidateId": _candidate_id(kind, identity),
        "candidateType": kind,
        "granularity": kind,
        "semanticKey": semantic_key,
        "text": normalized_text,
        "pageNo": page,
        "bbox": bbox,
        "polygon": polygon,
        "tableId": table_id,
        "row": row,
        "col": col,
        "sourceId": str(source_id) if source_id is not None else None,
        "sourceEngine": source_engine,
        "confidence": _float(item.get("confidence") or item.get("ocrConfidence") or item.get("structureConfidence")),
        "qualityFlags": flags,
        "formalEvidenceEligible": bool(formal_eligible),
    }
    if extra:
        output.update(extra)
    return {key: value for key, value in output.items() if value is not None and value != []}


def _table_cells(table: dict[str, Any]) -> list[dict[str, Any]]:
    cells = [item for item in table.get("cells") or [] if isinstance(item, dict)]
    if cells:
        return cells
    flattened: list[dict[str, Any]] = []
    for row_index, row in enumerate(table.get("rows") or []):
        if not isinstance(row, dict):
            continue
        raw_cells = row.get("cells") if isinstance(row.get("cells"), list) else []
        for col_index, cell in enumerate(raw_cells):
            if isinstance(cell, dict):
                flattened.append({"row": row_index, "col": col_index, **cell})
            else:
                flattened.append({"row": row_index, "col": col_index, "text": cell})
    return flattened


def _table_text(table: dict[str, Any], cells: list[dict[str, Any]]) -> str:
    direct = _text(table.get("text") or table.get("markdown"))
    if direct:
        return direct[:4000]
    return " | ".join(
        _text(cell.get("text") or cell.get("value") or cell.get("fieldValue"))
        for cell in cells
        if _text(cell.get("text") or cell.get("value") or cell.get("fieldValue"))
    )[:4000]


def _inferred_semantic_key(text: Any) -> str | None:
    normalized = _normalize_for_match(text)
    if not normalized:
        return None
    matches = [
        (field_key, len(_normalize_for_match(alias)))
        for field_key, aliases in _FIELD_LABEL_ALIASES.items()
        for alias in aliases
        if _normalize_for_match(alias) and _normalize_for_match(alias) in normalized
    ]
    if not matches:
        return None
    field_key, alias_length = max(matches, key=lambda item: item[1])
    if len(normalized) > alias_length + 10:
        return None
    return field_key


def _cell_semantic_keys(cells: list[dict[str, Any]], allowed_keys: set[str]) -> dict[int, str]:
    explicit: dict[int, str] = {}
    headers: list[tuple[int, str, list[float]]] = []
    for index, cell in enumerate(cells):
        semantic_key = str(cell.get("fieldCode") or cell.get("semanticKey") or "").strip() or _inferred_semantic_key(
            cell.get("header") or cell.get("text") or cell.get("value")
        )
        if semantic_key and allowed_keys and semantic_key not in allowed_keys:
            semantic_key = None
        bbox = normalize_bbox(cell.get("bbox"))
        if semantic_key:
            explicit[index] = semantic_key
            if bbox:
                headers.append((index, semantic_key, bbox))
    inferred = dict(explicit)
    for index, cell in enumerate(cells):
        if index in inferred:
            continue
        bbox = normalize_bbox(cell.get("bbox"))
        if not bbox:
            continue
        matches: list[tuple[float, float, str]] = []
        for header_index, semantic_key, header_bbox in headers:
            if header_index == index or header_bbox[1] > bbox[1]:
                continue
            vertical_distance = bbox[1] - header_bbox[3]
            if vertical_distance < -2 or vertical_distance > 220:
                continue
            overlap = max(0.0, min(bbox[2], header_bbox[2]) - max(bbox[0], header_bbox[0]))
            overlap_ratio = overlap / max(min(bbox[2] - bbox[0], header_bbox[2] - header_bbox[0]), 1.0)
            if overlap_ratio >= 0.55:
                matches.append((-vertical_distance, overlap_ratio, semantic_key))
        if matches:
            inferred[index] = max(matches)[2]
    return inferred


def _page_dimensions(parse_result: dict[str, Any]) -> dict[int, tuple[float, float, str | None]]:
    dimensions: dict[int, tuple[float, float, str | None]] = {}
    for index, page in enumerate(parse_result.get("pages") or [], start=1):
        if not isinstance(page, dict):
            continue
        page_no = _int(page.get("pageNo"), index)
        try:
            width = float(page.get("width") or page.get("pageWidth") or 0)
            height = float(page.get("height") or page.get("pageHeight") or 0)
        except (TypeError, ValueError):
            width, height = 0.0, 0.0
        dimensions[page_no] = (width, height, str(page.get("imageHash") or page.get("sha256") or "") or None)
    return dimensions


def sparse_table_diagnostics(parse_result: dict[str, Any]) -> list[dict[str, Any]]:
    page_dimensions = _page_dimensions(parse_result)
    diagnostics: list[dict[str, Any]] = []
    for index, table in enumerate(parse_result.get("tables") or [], start=1):
        if not isinstance(table, dict):
            continue
        page_no = _int(table.get("pageNo"))
        bbox = normalize_bbox(table.get("bbox"))
        width, height, _ = page_dimensions.get(page_no, (0.0, 0.0, None))
        if not bbox or width <= 0 or height <= 0:
            continue
        cells = _table_cells(table)
        area_ratio = ((bbox[2] - bbox[0]) * (bbox[3] - bbox[1])) / (width * height)
        if area_ratio < 0.2 or len(cells) >= 4:
            continue
        table_id = str(table.get("tableId") or table.get("id") or f"table-{index}")
        diagnostics.append(
            {
                "code": "TABLE_CONTENT_SPARSE",
                "level": "warning",
                "tableId": table_id,
                "pageNo": page_no,
                "bbox": bbox,
                "pageAreaRatio": round(area_ratio, 4),
                "cellCount": len(cells),
                "formalEvidenceEligible": False,
                "retryPlan": {
                    "orientationFirst": True,
                    "preferredEngines": ["pp_ocr", "pp_structure_v3"],
                    "fallbackEngine": "paddleocr_vl_1_6",
                    "tiles": table_retry_tiles(bbox, max_tiles=4, overlap_ratio=0.1),
                },
            }
        )
    return diagnostics


def table_retry_tiles(bbox: Any, *, max_tiles: int = 4, overlap_ratio: float = 0.1) -> list[list[float]]:
    normalized = normalize_bbox(bbox)
    if not normalized:
        return []
    x1, y1, x2, y2 = normalized
    width, height = x2 - x1, y2 - y1
    tile_count = max(1, min(int(max_tiles), 4))
    horizontal = width >= height
    length = width if horizontal else height
    if length <= 0 or tile_count == 1:
        return [normalized]
    tile_length = length / (tile_count - (tile_count - 1) * overlap_ratio)
    stride = tile_length * (1 - overlap_ratio)
    output = []
    for index in range(tile_count):
        start = (x1 if horizontal else y1) + index * stride
        end = min(x2 if horizontal else y2, start + tile_length)
        start = max(x1 if horizontal else y1, end - tile_length)
        tile = [start, y1, end, y2] if horizontal else [x1, start, x2, end]
        output.append([round(value, 4) for value in tile])
    return output


def _raw_candidates(parse_result: dict[str, Any], profile: dict[str, Any]) -> list[dict[str, Any]]:
    required_fields = {str(item) for item in profile.get("requiredFields") or []}
    structured = profile.get("structuredExtraction") if isinstance(profile.get("structuredExtraction"), dict) else {}
    structured_fields = {str(item) for item in structured.get("fields") or [] if str(item).strip()}
    output: list[dict[str, Any]] = []
    for index, field in enumerate(parse_result.get("fields") or [], start=1):
        if not isinstance(field, dict):
            continue
        code = str(field.get("fieldCode") or field.get("fieldName") or f"field_{index}")
        candidate = _candidate(
            "field",
            field,
            text=field.get("fieldValue") or field.get("value") or field.get("text"),
            page_no=field.get("pageNo"),
            semantic_key=code,
            source_id=field.get("fieldId") or field.get("id") or index,
            extra={"required": code in required_fields},
        )
        if candidate:
            output.append(candidate)

    seen_table_signatures: set[str] = set()
    for table_index, table in enumerate(parse_result.get("tables") or [], start=1):
        if not isinstance(table, dict):
            continue
        table_id = str(table.get("tableId") or table.get("id") or f"table-{table_index}")
        page_no = _int(table.get("pageNo"))
        cells = _table_cells(table)
        semantic_keys = _cell_semantic_keys(cells, structured_fields)
        table_text = _table_text(table, cells)
        signature = stable_payload_hash({"pageNo": page_no, "text": table_text, "bbox": normalize_bbox(table.get("bbox"))})
        if signature in seen_table_signatures:
            continue
        seen_table_signatures.add(signature)
        for cell_index, cell in enumerate(cells, start=1):
            text = cell.get("text") or cell.get("value") or cell.get("fieldValue")
            row = cell.get("row") if cell.get("row") is not None else cell.get("rowIndex")
            col = cell.get("col") if cell.get("col") is not None else cell.get("columnIndex")
            candidate = _candidate(
                "table_cell",
                cell,
                text=text,
                page_no=cell.get("pageNo") or page_no,
                semantic_key=semantic_keys.get(cell_index - 1),
                table_id=table_id,
                row=row,
                col=col,
                source_id=cell.get("cellId") or cell.get("id") or cell_index,
            )
            if candidate:
                output.append(candidate)
        block = _candidate(
            "table_block",
            table,
            text=table_text,
            page_no=page_no,
            semantic_key=str(table.get("businessSchema") or "") or None,
            table_id=table_id,
            source_id=table_id,
            formal_eligible=False,
            extra={"cellCount": len(cells), "tableSignature": signature},
        )
        if block:
            output.append(block)

    for index, fragment in enumerate(parse_result.get("fragments") or [], start=1):
        if not isinstance(fragment, dict):
            continue
        candidate = _candidate(
            "text_line",
            fragment,
            text=fragment.get("text"),
            page_no=fragment.get("pageNo"),
            source_id=fragment.get("fragmentId") or fragment.get("id") or index,
        )
        if candidate:
            output.append(candidate)

    for index, seal in enumerate(parse_result.get("seals") or [], start=1):
        if not isinstance(seal, dict):
            continue
        seal_text = seal.get("ocrText") or seal.get("sealName") or seal.get("text")
        source_engine = _source_engine(seal)
        formal_eligible = bool(
            _text(seal_text)
            and normalize_bbox(seal.get("bbox"))
            and source_engine not in {"visual_seal_candidate_subprocess", "direct_vision", "visual_review"}
        )
        candidate = _candidate(
            "seal_crop",
            seal,
            text=seal_text,
            page_no=seal.get("pageNo"),
            semantic_key=str(seal.get("sealType") or "seal"),
            source_id=seal.get("sealId") or seal.get("id") or index,
            formal_eligible=formal_eligible,
            extra={"required": bool((profile.get("sealRules") or {}).get("required"))},
        )
        if candidate:
            output.append(candidate)

    for index, block in enumerate(parse_result.get("layoutBlocks") or [], start=1):
        if not isinstance(block, dict):
            continue
        candidate = _candidate(
            "layout_block",
            block,
            text=block.get("text") or block.get("blockType") or "layout",
            page_no=block.get("pageNo"),
            semantic_key=str(block.get("blockType") or "layout"),
            source_id=block.get("blockId") or block.get("id") or index,
            formal_eligible=False,
        )
        if candidate:
            output.append(candidate)

    for index, signature in enumerate(parse_result.get("signatures") or [], start=1):
        if not isinstance(signature, dict):
            continue
        candidate = _candidate(
            "signature_visual",
            signature,
            text=signature.get("text") or signature.get("label") or "signature_candidate",
            page_no=signature.get("pageNo"),
            semantic_key="signature",
            source_id=signature.get("signatureId") or signature.get("id") or index,
            formal_eligible=False,
        )
        if candidate:
            output.append(candidate)
    return list({item["candidateId"]: item for item in output}.values())


def _select_pages(
    candidates: list[dict[str, Any]],
    parse_result: dict[str, Any],
    *,
    max_pages: int,
) -> list[int]:
    page_scores: dict[int, float] = {}
    for candidate in candidates:
        page_no = _int(candidate.get("pageNo"))
        score = float(_CANDIDATE_PRIORITY.get(str(candidate.get("candidateType")), 0))
        if candidate.get("required"):
            score += 1000
        page_scores[page_no] = page_scores.get(page_no, 0) + score
    dimensions = _page_dimensions(parse_result)
    ranked = sorted(page_scores, key=lambda page: (-page_scores[page], page))
    selected: list[int] = []
    seen_image_hashes: set[str] = set()
    for page_no in ranked:
        image_hash = dimensions.get(page_no, (0.0, 0.0, None))[2]
        if image_hash and image_hash in seen_image_hashes:
            continue
        if image_hash:
            seen_image_hashes.add(image_hash)
        selected.append(page_no)
        if len(selected) >= max_pages:
            break
    if not selected:
        available_pages = sorted(_page_dimensions(parse_result))
        selected = [available_pages[0] if available_pages else 1]
    return sorted(selected)


def _candidate_sort_key(candidate: dict[str, Any]) -> tuple[Any, ...]:
    return (
        0 if candidate.get("required") else 1,
        -_CANDIDATE_PRIORITY.get(str(candidate.get("candidateType")), 0),
        -_candidate_selection_utility(candidate),
        _int(candidate.get("pageNo")),
        _GRANULARITY_RANK.get(str(candidate.get("granularity")), 99),
        str(candidate.get("candidateId")),
    )


def _candidate_selection_utility(candidate: dict[str, Any]) -> int:
    text = str(candidate.get("text") or "")
    normalized_text = _normalize_for_match(text)
    utility = 0
    if any(_normalize_for_match(alias) in normalized_text for aliases in _FIELD_LABEL_ALIASES.values() for alias in aliases):
        utility += 500
    if _HIGH_VALUE_CELL_RE.search(unicodedata.normalize("NFKC", text)):
        utility += 350
    row = candidate.get("row")
    try:
        if row is not None and int(row) <= 3:
            utility += 200
    except (TypeError, ValueError):
        pass
    if candidate.get("semanticKey"):
        utility += 150
    if candidate.get("formalEvidenceEligible") is True:
        utility += 50
    return utility


def build_evidence_prior(
    parse_result: dict[str, Any],
    profile: dict[str, Any],
    *,
    max_candidates: int | None = None,
    max_tokens: int | None = None,
    max_pages: int | None = None,
) -> dict[str, Any]:
    structured = profile.get("structuredExtraction") if isinstance(profile.get("structuredExtraction"), dict) else {}
    max_candidates = max(1, min(int(max_candidates or structured.get("maxCandidates") or DEFAULT_MAX_CANDIDATES), DEFAULT_MAX_CANDIDATES))
    max_tokens = max(1, min(int(max_tokens or structured.get("maxPriorTokens") or DEFAULT_MAX_PRIOR_TOKENS), DEFAULT_MAX_PRIOR_TOKENS))
    max_pages = max(1, min(int(max_pages or structured.get("maxPages") or DEFAULT_MAX_PAGES), DEFAULT_MAX_PAGES))
    raw_candidates = _raw_candidates(parse_result, profile)
    selected_pages = _select_pages(raw_candidates, parse_result, max_pages=max_pages)
    page_candidates = [item for item in raw_candidates if _int(item.get("pageNo")) in selected_pages]
    page_candidates.sort(key=_candidate_sort_key)
    base = {
        "schemaVersion": EVIDENCE_PRIOR_VERSION,
        "profileId": profile.get("profileId"),
        "templateVersion": structured.get("templateVersion") or f"{profile.get('profileId')}@1",
        "sourceParseResultId": parse_result.get("parseResultId") or parse_result.get("id"),
        "selectedPageNos": selected_pages,
        "limits": {"maxCandidates": max_candidates, "maxPriorTokens": max_tokens, "maxPages": max_pages},
        "diagnostics": sparse_table_diagnostics(parse_result),
    }
    selected: list[dict[str, Any]] = []
    repeated_cell_texts: dict[tuple[str, str], int] = {}
    for candidate in page_candidates:
        if len(selected) >= max_candidates:
            break
        if candidate.get("candidateType") == "table_cell":
            signature = (str(candidate.get("tableId") or ""), _normalize_for_match(candidate.get("text")))
            if signature[1] and repeated_cell_texts.get(signature, 0) >= 4:
                continue
        proposed = {**base, "candidates": [*selected, candidate]}
        if estimate_json_tokens(proposed) > max_tokens:
            continue
        selected.append(candidate)
        if candidate.get("candidateType") == "table_cell" and signature[1]:
            repeated_cell_texts[signature] = repeated_cell_texts.get(signature, 0) + 1
    compact = {
        **base,
        "candidateCount": len(selected),
        "omittedCandidateCount": max(0, len(raw_candidates) - len(selected)),
        "candidates": selected,
    }
    compact["estimatedTokenCount"] = 0
    compact["estimatedTokenCount"] = estimate_json_tokens(compact)
    while compact["candidates"] and estimate_json_tokens(compact) > max_tokens:
        compact["candidates"].pop()
        compact["candidateCount"] = len(compact["candidates"])
        compact["omittedCandidateCount"] = max(0, len(raw_candidates) - len(compact["candidates"]))
        compact["estimatedTokenCount"] = estimate_json_tokens(compact)
    compact["estimatedTokenCount"] = estimate_json_tokens(compact)
    full = {
        **base,
        "candidateCount": len(raw_candidates),
        "candidates": sorted(raw_candidates, key=_candidate_sort_key),
    }
    return {
        "full": full,
        "compact": compact,
        "fullPriorHash": stable_payload_hash(full),
        "compactPriorHash": stable_payload_hash(compact),
    }


def _normalize_for_match(value: Any) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or "")).upper()
    normalized = normalized.replace("／", "/").replace("－", "-")
    return re.sub(r"[^0-9A-Z\u4e00-\u9fff%./+\-]+", "", normalized)


def _anchors(value: str) -> list[str]:
    normalized = unicodedata.normalize("NFKC", value).upper()
    patterns = [
        r"(?:19|20)\d{2}[年./-]\d{1,2}(?:[月./-]\d{1,2}日?)?",
        r"(?:GB|NB|TSG|HG|SY|DL|JB)\s*[/T]*\s*\d+(?:\.\d+)*(?:[-—]\d{4})?",
        r"[A-Z]{1,5}\d[A-Z0-9./-]{3,}",
        r"-?\d+(?:\.\d+)?\s*(?:MPA|KPA|PA|MM|CM|M|%|℃|°C)",
        r"\b(?:AB|III|II|IV)\b",
    ]
    anchors = []
    for pattern in patterns:
        anchors.extend(_normalize_for_match(item) for item in re.findall(pattern, normalized, flags=re.IGNORECASE))
    return [item for item in dict.fromkeys(anchors) if item]


def _bigrams(value: str) -> set[str]:
    normalized = _normalize_for_match(value)
    if len(normalized) < 2:
        return {normalized} if normalized else set()
    return {normalized[index : index + 2] for index in range(len(normalized) - 1)}


def _supports_value(value: str, evidence_text: str, *, semantic_match: bool = False) -> bool:
    normalized_value = _normalize_for_match(value)
    normalized_evidence = _normalize_for_match(evidence_text)
    if not normalized_value:
        return False
    if normalized_value in normalized_evidence:
        return True
    anchors = _anchors(value)
    if anchors and all(anchor in normalized_evidence for anchor in anchors):
        return True
    value_bigrams = _bigrams(value)
    evidence_bigrams = _bigrams(evidence_text)
    overlap = len(value_bigrams & evidence_bigrams) / max(len(value_bigrams), 1)
    return overlap >= (0.45 if semantic_match else 0.68)


def _semantic_supports_field(field_key: str, value: str, candidate: dict[str, Any], evidence_text: str) -> bool:
    normalized_key = str(field_key or "").strip().lower()
    if not _field_value_format_valid(normalized_key, value):
        return False
    semantic_key = str(candidate.get("semanticKey") or "").strip().lower()
    if candidate.get("candidateType") == "field" and semantic_key:
        return semantic_key == normalized_key
    aliases = _FIELD_LABEL_ALIASES.get(normalized_key)
    if not aliases:
        return True
    normalized_evidence = _normalize_for_match(evidence_text)
    contains_label = any(_normalize_for_match(alias) in normalized_evidence for alias in aliases)
    normalized_value = _normalize_for_match(value)
    ambiguous_value = len(normalized_value) <= 6 or bool(
        re.fullmatch(r"(?:-?\d+(?:\.\d+)?(?:%|MPA|KPA|MM)?|RT|UT|MT|PT|TOFD|AB|III|II|IV|GC[12D])", normalized_value)
    )
    if semantic_key:
        return semantic_key == normalized_key or contains_label
    return contains_label if ambiguous_value else True


def _field_value_format_valid(field_key: str, value: str) -> bool:
    normalized = _normalize_for_match(value)
    if not normalized:
        return False
    ndt_method = bool(re.fullmatch(r"(?:RT|UT|MT|PT|TOFD|PAUT)", normalized))
    if field_key in {"strength_test", "leak_test"}:
        return not ndt_method and not normalized.endswith("%")
    if field_key == "detection_method":
        return ndt_method or any(token in normalized for token in ("射线", "超声", "磁粉", "渗透", "相控阵"))
    if field_key == "detection_ratio":
        return "%" in normalized or "全检" in normalized or "全部" in normalized
    if field_key == "technical_grade":
        return bool(re.fullmatch(r"(?:A|B|AB|C)", normalized))
    if field_key == "evaluation_level":
        return bool(re.fullmatch(r"(?:I|II|III|IV|V|[1-5]级)", normalized))
    return True


def _attribution_value(item: dict[str, Any]) -> str:
    for key in ["value", "fieldValue", "text", "sealText", "result"]:
        if key in item and not isinstance(item.get(key), (dict, list)):
            return _text(item.get(key))
    scalars = {
        key: value
        for key, value in item.items()
        if key not in {"sourceCandidateIds", "rawSourceCandidateIds"}
        and value is not None
        and not isinstance(value, (dict, list))
    }
    return _text(" ".join(str(value) for value in scalars.values()))


def _walk_attributed_items(value: Any, path: str = "$") -> Iterable[tuple[str, dict[str, Any]]]:
    if isinstance(value, dict):
        if "sourceCandidateIds" in value:
            yield path, value
        for key, child in value.items():
            if key in {"sourceCandidateIds", "rawSourceCandidateIds"}:
                continue
            yield from _walk_attributed_items(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk_attributed_items(child, f"{path}[{index}]")


def validate_shadow_attribution(structured_output: Any, evidence_prior: dict[str, Any]) -> dict[str, Any]:
    repaired = deepcopy(structured_output)
    candidates = {
        str(item.get("candidateId")): item
        for item in evidence_prior.get("candidates") or []
        if isinstance(item, dict) and item.get("candidateId")
    }
    validations: list[dict[str, Any]] = []
    invalid_candidate_ids: set[str] = set()
    for path, item in _walk_attributed_items(repaired):
        raw_ids = item.get("sourceCandidateIds")
        raw_ids = raw_ids if isinstance(raw_ids, list) else []
        raw_ids = [str(candidate_id) for candidate_id in raw_ids if candidate_id]
        unknown_ids = [candidate_id for candidate_id in raw_ids if candidate_id not in candidates]
        invalid_candidate_ids.update(unknown_ids)
        known = [candidates[candidate_id] for candidate_id in raw_ids if candidate_id in candidates]
        value = _attribution_value(item)
        field_key = path.rsplit(".", 1)[-1].split("[", 1)[0]
        individually_supported = [
            candidate
            for candidate in known
            if _supports_value(
                value,
                str(candidate.get("text") or ""),
                semantic_match=str(candidate.get("semanticKey") or "") == field_key,
            )
            and _semantic_supports_field(field_key, value, candidate, str(candidate.get("text") or ""))
        ]
        selected: list[dict[str, Any]] = []
        if individually_supported:
            selected = [
                sorted(
                    individually_supported,
                    key=lambda candidate: (
                        0 if str(candidate.get("semanticKey") or "") == field_key else 1,
                        _GRANULARITY_RANK.get(str(candidate.get("granularity")), 99),
                        -len(str(candidate.get("text") or "")),
                        str(candidate.get("candidateId")),
                    ),
                )[0]
            ]
        elif known:
            row_groups: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
            for candidate in known:
                if candidate.get("candidateType") != "table_cell" or candidate.get("row") is None:
                    continue
                key = (candidate.get("pageNo"), candidate.get("tableId"), candidate.get("row"))
                row_groups.setdefault(key, []).append(candidate)
            supported_groups = [
                group
                for group in row_groups.values()
                if _supports_value(value, " ".join(str(candidate.get("text") or "") for candidate in group))
                and _semantic_supports_field(
                    field_key,
                    value,
                    {"candidateType": "table_row"},
                    " ".join(str(candidate.get("text") or "") for candidate in group),
                )
            ]
            if supported_groups:
                selected = min(supported_groups, key=lambda group: (len(group), [str(item.get("candidateId")) for item in group]))
        selected_ids = [str(candidate.get("candidateId")) for candidate in selected]
        if selected_ids != raw_ids:
            item["rawSourceCandidateIds"] = raw_ids
        item["sourceCandidateIds"] = selected_ids
        formal_candidates = [candidate for candidate in selected if candidate.get("formalEvidenceEligible") is True]
        item["attributionStatus"] = (
            "validated" if selected and len(formal_candidates) == len(selected) else "advisory_only" if selected else "unsupported"
        )
        item["advisoryOnly"] = True
        union = bbox_union(candidate.get("bbox") for candidate in selected)
        pages = sorted({_int(candidate.get("pageNo")) for candidate in selected})
        if union:
            item["evidenceBbox"] = union
        if len(pages) == 1:
            item["evidencePageNo"] = pages[0]
        validations.append(
            {
                "path": path,
                "rawSourceCandidateIds": raw_ids,
                "validatedSourceCandidateIds": selected_ids,
                "unknownSourceCandidateIds": unknown_ids,
                "status": item["attributionStatus"],
                "formalCandidateEligible": bool(selected) and len(formal_candidates) == len(selected),
            }
        )
    status_counts = {
        status: len([item for item in validations if item.get("status") == status])
        for status in ["validated", "advisory_only", "unsupported"]
    }
    return {
        "structuredOutput": repaired,
        "advisoryOnly": True,
        "formalEvidenceReady": False,
        "validation": {
            "schemaVersion": "DocumentAiAttributionValidation@1",
            "items": validations,
            "statusCounts": status_counts,
            "invalidCandidateIds": sorted(invalid_candidate_ids),
            "invalidCandidateIdCount": len(invalid_candidate_ids),
        },
    }


def _baseline_fields(parse_result: dict[str, Any]) -> dict[str, str]:
    return {
        str(item.get("fieldCode") or item.get("fieldName")): _text(item.get("fieldValue") or item.get("value") or item.get("text"))
        for item in parse_result.get("fields") or []
        if isinstance(item, dict) and (item.get("fieldCode") or item.get("fieldName"))
    }


def _shadow_fields(output: Any) -> dict[str, str]:
    if not isinstance(output, dict):
        return {}
    raw = output.get("fields") if isinstance(output.get("fields"), (dict, list)) else output
    fields: dict[str, str] = {}
    if isinstance(raw, dict):
        for key, value in raw.items():
            if isinstance(value, dict):
                fields[str(key)] = _attribution_value(value)
            elif not isinstance(value, list):
                fields[str(key)] = _text(value)
    elif isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            key = item.get("fieldCode") or item.get("fieldName") or item.get("name")
            if key:
                fields[str(key)] = _attribution_value(item)
    return fields


def compare_shadow_to_baseline(parse_result: dict[str, Any], structured_output: Any) -> dict[str, Any]:
    baseline = _baseline_fields(parse_result)
    shadow = _shadow_fields(structured_output)
    matching = sorted(key for key in baseline.keys() & shadow.keys() if _normalize_for_match(baseline[key]) == _normalize_for_match(shadow[key]))
    changed = [
        {"fieldCode": key, "baselineValue": baseline[key], "shadowValue": shadow[key]}
        for key in sorted(baseline.keys() & shadow.keys())
        if key not in matching
    ]
    return {
        "schemaVersion": "DocumentAiShadowDiff@1",
        "matchingFields": matching,
        "changedFields": changed,
        "shadowOnlyFields": [{"fieldCode": key, "value": shadow[key]} for key in sorted(shadow.keys() - baseline.keys())],
        "baselineOnlyFields": [{"fieldCode": key, "value": baseline[key]} for key in sorted(baseline.keys() - shadow.keys())],
        "accuracyClaimed": False,
        "requiresHumanGoldLabels": True,
    }
