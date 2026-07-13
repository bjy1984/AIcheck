from __future__ import annotations

import hashlib
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable

from PIL import Image

from libs.aliyun_ocr import (
    AliyunOcrError,
    AliyunQwenOcrClient,
    advanced_fragments,
    grounded_kie_fields,
    seal_candidates_from_fragments,
    table_from_call,
)
from libs.ocr_accuracy_pipeline import render_pages
from libs.ocr_runtime import ocr_runtime_config
from libs.official_ocr_control import (
    OfficialOcrBudgetExceeded,
    official_ocr_document_slot,
    reconcile_official_ocr_cost,
    reserve_official_ocr_cost,
)


def selected_source_pages(source_path: Path, profile: dict[str, Any], runtime: dict[str, Any]) -> list[int]:
    maximum = max(1, min(int(runtime["render"]["maxDocumentPages"]), 200))
    if source_path.suffix.lower() != ".pdf":
        return [1]
    try:
        import fitz

        with fitz.open(source_path) as document:
            total = int(document.page_count)
    except Exception:
        return [1]
    if total > maximum:
        raise AliyunOcrError(
            f"Document page count {total} exceeds official OCR limit {maximum}",
            reason="DOCUMENT_PAGE_LIMIT_EXCEEDED",
        )
    return list(range(1, total + 1))


def field_schema(profile: dict[str, Any]) -> tuple[dict[str, str], dict[str, str]]:
    structured = profile.get("structuredExtraction") if isinstance(profile.get("structuredExtraction"), dict) else {}
    definitions = structured.get("fieldDefinitions") if isinstance(structured.get("fieldDefinitions"), dict) else {}
    configured_fields = structured.get("fields") if isinstance(structured.get("fields"), list) else []
    required = [
        str(item)
        for item in (configured_fields or profile.get("requiredFields") or [])
        if str(item) and str(item) != "seal"
    ]
    schema: dict[str, str] = {}
    labels: dict[str, str] = {}
    for code in required:
        definition = definitions.get(code)
        if isinstance(definition, dict):
            label = str(definition.get("label") or definition.get("name") or code)
            description = str(definition.get("description") or definition.get("prompt") or label)
        else:
            label = str(definition or code)
            description = label
        labels[code] = label
        schema[code] = description
    return schema, labels


def detect_color_seal_rois(
    image_path: Path,
    output_directory: Path,
    *,
    max_candidates: int = 2,
) -> list[dict[str, Any]]:
    try:
        import cv2
        import numpy as np
    except ImportError:
        return []
    image = cv2.imread(str(image_path))
    if image is None:
        return []
    height, width = image.shape[:2]
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    masks = {
        "red": (
            cv2.inRange(hsv, np.array([0, 25, 35]), np.array([15, 255, 255]))
            | cv2.inRange(hsv, np.array([160, 25, 35]), np.array([180, 255, 255]))
        ),
        "blue": cv2.inRange(hsv, np.array([85, 35, 25]), np.array([140, 255, 230])),
    }
    candidates: list[dict[str, Any]] = []
    for color, mask in masks.items():
        kernel = np.ones((15, 15), np.uint8)
        merged = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
        contours, _ = cv2.findContours(merged, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for contour in contours:
            area = float(cv2.contourArea(contour))
            if area < max(800.0, width * height * 0.00008):
                continue
            x, y, box_width, box_height = cv2.boundingRect(contour)
            if box_width < 40 or box_height < 25:
                continue
            if (box_width * box_height) / float(width * height) > 0.12:
                continue
            aspect = box_width / float(box_height)
            if aspect < 0.3 or aspect > 6.0:
                continue
            candidates.append(
                {
                    "color": color,
                    "area": area,
                    "bbox": [int(x), int(y), int(x + box_width), int(y + box_height)],
                }
            )
    selected: list[dict[str, Any]] = []
    for candidate in sorted(candidates, key=lambda item: float(item["area"]), reverse=True):
        x0, y0, x1, y1 = candidate["bbox"]
        center = ((x0 + x1) / 2.0, (y0 + y1) / 2.0)
        if any(
            previous["bbox"][0] <= center[0] <= previous["bbox"][2]
            and previous["bbox"][1] <= center[1] <= previous["bbox"][3]
            for previous in selected
        ):
            continue
        padding = max(8, int(max(x1 - x0, y1 - y0) * 0.12))
        crop_bbox = [
            max(0, x0 - padding),
            max(0, y0 - padding),
            min(width, x1 + padding),
            min(height, y1 + padding),
        ]
        crop = image[crop_bbox[1] : crop_bbox[3], crop_bbox[0] : crop_bbox[2]]
        if crop.size == 0:
            continue
        output_directory.mkdir(parents=True, exist_ok=True)
        crop_path = output_directory / f"seal_{candidate['color']}_{len(selected) + 1}.jpg"
        if not cv2.imwrite(str(crop_path), crop):
            continue
        selected.append(
            {
                **candidate,
                "bbox": crop_bbox,
                "path": crop_path,
            }
        )
        if len(selected) >= max_candidates:
            break
    return selected


def _offset_advanced_fragments(call: dict[str, Any]) -> list[dict[str, Any]]:
    fragments = advanced_fragments(call)
    offset = call.get("roiOffset")
    if not isinstance(offset, list) or len(offset) < 2:
        return fragments
    offset_x, offset_y = float(offset[0]), float(offset[1])
    for fragment in fragments:
        bbox = fragment.get("bbox")
        polygon = fragment.get("polygon")
        if isinstance(bbox, list) and len(bbox) >= 4:
            fragment["bbox"] = [
                float(bbox[0]) + offset_x,
                float(bbox[1]) + offset_y,
                float(bbox[2]) + offset_x,
                float(bbox[3]) + offset_y,
            ]
        if isinstance(polygon, list) and len(polygon) >= 8:
            fragment["polygon"] = [
                float(value) + (offset_x if index % 2 == 0 else offset_y)
                for index, value in enumerate(polygon)
            ]
        digest = hashlib.sha256(
            f"{fragment.get('pageNo')}|{fragment.get('text')}|{fragment.get('polygon')}".encode("utf-8")
        ).hexdigest()[:16].upper()
        candidate_id = f"OCR-CAND-{digest}"
        fragment["candidateId"] = candidate_id
        fragment["sourceCandidateIds"] = [candidate_id]
        fragment["sourceEngine"] = "aliyun_qwen_ocr_seal_roi"
        fragment["roiBbox"] = call.get("roiBbox")
        fragment["roiColor"] = call.get("roiColor")
    return fragments


def _page_records(rendered: dict[int, Path]) -> list[dict[str, Any]]:
    output = []
    for page_no, path in sorted(rendered.items()):
        with Image.open(path) as image:
            width, height = image.size
        output.append(
            {
                "pageNo": int(page_no),
                "width": int(width),
                "height": int(height),
                "coordinateSystem": "rendered_pixels",
                "imageHash": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    return output


def _attempt_record(call: dict[str, Any], *, status: str = "success", error: str | None = None) -> dict[str, Any]:
    return {
        "provider": call.get("provider") or "aliyun_model_studio",
        "model": call.get("model"),
        "task": call.get("task"),
        "requestId": call.get("requestId"),
        "pageNo": call.get("pageNo"),
        "status": status,
        "durationMs": int(call.get("durationMs") or 0),
        "usage": call.get("usage") or {},
        "costCny": float(call.get("costCny") or 0.0),
        "input": call.get("input") or {},
        "failureReason": error,
        "callId": call.get("callId"),
        "finishReason": call.get("finishReason"),
        "outputTruncated": bool(call.get("outputTruncated")),
        "maxOutputTokens": call.get("maxOutputTokens"),
        "modelCallLedgerId": call.get("modelCallLedgerId"),
    }


def _split_recovery_tiles(
    image_path: Path,
    output_directory: Path,
    *,
    overlap_ratio: float = 0.08,
) -> list[dict[str, Any]]:
    output_directory.mkdir(parents=True, exist_ok=True)
    with Image.open(image_path) as source:
        image = source.convert("RGB")
        width, height = image.size
        vertical = height >= width
        length = height if vertical else width
        overlap = max(8, int(length * overlap_ratio))
        midpoint = length // 2
        ranges = [(0, min(length, midpoint + overlap)), (max(0, midpoint - overlap), length)]
        output: list[dict[str, Any]] = []
        for index, (start, end) in enumerate(ranges, start=1):
            bbox = [0, start, width, end] if vertical else [start, 0, end, height]
            crop = image.crop(tuple(bbox))
            path = output_directory / f"tile-{index}.jpg"
            crop.save(path, format="JPEG", quality=90, optimize=True, subsampling=0)
            output.append({"path": path, "bbox": bbox, "offset": [bbox[0], bbox[1]]})
        return output


def _table_grid_score(image_path: Path) -> float:
    try:
        import cv2
        import numpy as np
    except ImportError:
        return 0.0
    image = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
    if image is None or image.size == 0:
        return 0.0
    binary = cv2.adaptiveThreshold(
        image,
        255,
        cv2.ADAPTIVE_THRESH_MEAN_C,
        cv2.THRESH_BINARY_INV,
        31,
        12,
    )
    horizontal_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (max(20, image.shape[1] // 30), 1))
    vertical_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(20, image.shape[0] // 30)))
    horizontal = cv2.morphologyEx(binary, cv2.MORPH_OPEN, horizontal_kernel)
    vertical = cv2.morphologyEx(binary, cv2.MORPH_OPEN, vertical_kernel)
    line_pixels = int(np.count_nonzero(horizontal | vertical))
    return round(line_pixels / float(image.size), 6)


def _page_text(fragments: list[dict[str, Any]], page_no: int) -> str:
    return " ".join(
        str(item.get("text") or "")
        for item in fragments
        if int(item.get("pageNo") or 1) == int(page_no)
    )


def _structured_candidate_pages(
    rendered: dict[int, Path],
    fragments: list[dict[str, Any]],
    *,
    labels: list[str],
    limit: int,
    table_mode: bool,
) -> list[int]:
    normalized_labels = ["".join(str(label).lower().split()) for label in labels if str(label).strip()]
    table_keywords = ["表", "序号", "项目", "规格", "检测", "管线", "材料", "报告编号", "证书号"]
    scored: list[tuple[float, int]] = []
    for page_no, image_path in rendered.items():
        text = _page_text(fragments, page_no)
        compact = "".join(text.lower().split())
        label_hits = sum(1 for label in normalized_labels if label and label in compact)
        keyword_hits = sum(1 for keyword in table_keywords if keyword in text) if table_mode else 0
        grid_score = _table_grid_score(image_path) if table_mode else 0.0
        content_score = min(len(compact) / 10000.0, 0.5)
        scored.append((label_hits * 10.0 + keyword_hits * 2.0 + grid_score * 100.0 + content_score, page_no))
    positive = [item for item in scored if item[0] >= (1.0 if table_mode else 1.0)]
    selected = positive or scored
    selected.sort(key=lambda item: (-item[0], item[1]))
    return [page_no for _, page_no in selected[: max(1, min(limit, len(selected)))]]


def _local_text_layer_result(
    source_path: Path,
    selected_pages: list[int],
    profile: dict[str, Any],
) -> dict[str, Any] | None:
    if source_path.suffix.lower() != ".pdf":
        return None
    required_fields = [item for item in profile.get("requiredFields") or [] if str(item) != "seal"]
    required_tables = profile.get("requiredTables") or []
    seal_required = bool((profile.get("sealRules") or {}).get("required"))
    if required_fields or required_tables or seal_required:
        return None
    try:
        import fitz

        document = fitz.open(source_path)
    except Exception:
        return None
    fragments: list[dict[str, Any]] = []
    pages: list[dict[str, Any]] = []
    try:
        for page_no in selected_pages:
            if page_no < 1 or page_no > document.page_count:
                continue
            page = document.load_page(page_no - 1)
            pages.append(
                {
                    "pageNo": page_no,
                    "width": float(page.rect.width),
                    "height": float(page.rect.height),
                    "coordinateSystem": "pdf_points",
                }
            )
            for index, block in enumerate(page.get_text("blocks")):
                if len(block) < 5:
                    continue
                text = str(block[4] or "").strip()
                if not text:
                    continue
                bbox = [float(block[0]), float(block[1]), float(block[2]), float(block[3])]
                digest = hashlib.sha256(f"{page_no}|{index}|{text}|{bbox}".encode("utf-8")).hexdigest()[:16].upper()
                candidate_id = f"TEXT-CAND-{digest}"
                fragments.append(
                    {
                        "candidateId": candidate_id,
                        "pageNo": page_no,
                        "text": text,
                        "bbox": bbox,
                        "polygon": None,
                        "coordinateSystem": "pdf_points",
                        "sourceEngine": "pymupdf_text_layer",
                        "sourceCandidateIds": [candidate_id],
                        "formalEvidenceEligible": True,
                    }
                )
    finally:
        document.close()
    if sum(len(str(item.get("text") or "")) for item in fragments) < 80:
        return None
    return {
        "status": "success",
        "outcomeStatus": "completed",
        "parserVersion": "pymupdf-text-layer@1",
        "profileId": profile.get("profileId"),
        "documentType": profile.get("documentType"),
        "pages": pages,
        "fragments": fragments,
        "fields": [],
        "tables": [],
        "seals": [],
        "signatures": [],
        "layoutBlocks": [],
        "engineRuns": [
            {
                "engine": "pymupdf_text_layer",
                "status": "success",
                "durationMs": 0,
                "engineAttempted": True,
                "engineExecuted": True,
            }
        ],
        "quality": {"status": "usable", "reasons": [], "blockingReasons": []},
        "metadata": {
            "providerMode": "hybrid_auto",
            "provider": "local_text_layer",
            "model": None,
            "cloudGrounded": False,
            "costCny": 0.0,
            "modelCallCount": 0,
            "selectedPageNos": selected_pages,
        },
        "modelCallAttempts": [],
        "costCny": 0.0,
        "groundingValidation": {
            "invalidCandidateIdCount": 0,
            "unsupportedAttributionCount": 0,
            "droppedUnsupportedAttributionCount": 0,
            "candidateRepairCount": 0,
            "validatedFieldCount": 0,
        },
    }


def _official_ocr_extract_legacy(
    source_path: Path,
    *,
    profile: dict[str, Any],
    runtime: dict[str, Any] | None = None,
    client: AliyunQwenOcrClient | None = None,
    work_directory: Path,
    page_call_cache: dict[int, list[dict[str, Any]]] | None = None,
    page_completed: Callable[[int, int, int, list[dict[str, Any]]], None] | None = None,
) -> dict[str, Any]:
    current = runtime or ocr_runtime_config(validate=True)
    selected_pages = selected_source_pages(source_path, profile, current)
    if current["mode"] == "hybrid_auto":
        text_result = _local_text_layer_result(source_path, selected_pages, profile)
        if text_result is not None:
            return text_result

    ocr_client = client or AliyunQwenOcrClient(runtime=current)
    rendered = render_pages(source_path, selected_pages, work_directory / "pages")
    pages = _page_records(rendered)
    calls: list[dict[str, Any]] = []
    advanced_calls: list[dict[str, Any]] = []
    kie_calls: list[dict[str, Any]] = []
    table_calls: list[dict[str, Any]] = []
    schema, field_labels = field_schema(profile)
    required_tables = [str(item) for item in profile.get("requiredTables") or [] if str(item)]
    seal_required = bool((profile.get("sealRules") or {}).get("required"))
    table_code = required_tables[0] if len(required_tables) == 1 else "official_table_page"
    started = time.monotonic()

    total_pages = len(rendered)

    def process_page(page_no: int, image_path: Path) -> tuple[int, list[dict[str, Any]], bool]:
        page_calls = [
            item
            for item in (page_call_cache or {}).get(int(page_no), [])
            if isinstance(item, dict)
        ]
        fresh = not page_calls
        if fresh:
            call_specs: list[tuple[str, dict[str, Any]]] = [
                ("advanced_recognition", {}),
            ]
            if schema:
                call_specs.append(
                    ("key_information_extraction", {"result_schema": schema})
                )
            if required_tables:
                call_specs.append(("table_parsing", {}))
            with ThreadPoolExecutor(max_workers=len(call_specs)) as executor:
                futures = [
                    executor.submit(
                        ocr_client.call,
                        image_path,
                        task=task,
                        page_no=page_no,
                        **kwargs,
                    )
                    for task, kwargs in call_specs
                ]
                page_calls.extend(future.result() for future in futures)

            advanced = next(
                item
                for item in page_calls
                if item.get("task") == "advanced_recognition"
            )
            if seal_required and not seal_candidates_from_fragments(advanced_fragments(advanced)):
                seal_rois = detect_color_seal_rois(
                    image_path,
                    work_directory / "seal-rois" / f"page-{page_no}",
                )
                for roi in seal_rois:
                    roi_call = ocr_client.call(
                        roi["path"],
                        task="advanced_recognition",
                        page_no=page_no,
                    )
                    roi_call["roiOffset"] = [roi["bbox"][0], roi["bbox"][1]]
                    roi_call["roiBbox"] = roi["bbox"]
                    roi_call["roiColor"] = roi["color"]
                    page_calls.append(roi_call)
        return page_no, page_calls, fresh

    rendered_items = sorted(rendered.items())
    page_results: dict[int, list[dict[str, Any]]] = {}
    with ThreadPoolExecutor(max_workers=min(2, max(total_pages, 1))) as executor:
        page_futures = [
            executor.submit(process_page, page_no, image_path)
            for page_no, image_path in rendered_items
        ]
        for completed_count, future in enumerate(as_completed(page_futures), start=1):
            page_no, page_calls, fresh = future.result()
            page_results[page_no] = page_calls
            if fresh and page_completed:
                page_completed(page_no, completed_count, total_pages, page_calls)

    for page_no in sorted(page_results):
        page_calls = page_results[page_no]
        calls.extend(page_calls)
        advanced_calls.extend(item for item in page_calls if item.get("task") == "advanced_recognition")
        kie_calls.extend(item for item in page_calls if item.get("task") == "key_information_extraction")
        table_calls.extend(item for item in page_calls if item.get("task") == "table_parsing")
        accumulated_cost = sum(float(item.get("costCny") or 0.0) for item in calls)
        if accumulated_cost > float(current["render"]["maxCostCnyPerDocument"]):
            raise AliyunOcrError(
                "Official OCR document cost limit exceeded",
                reason="DOCUMENT_COST_LIMIT_EXCEEDED",
            )

    fragments = [fragment for call in advanced_calls for fragment in _offset_advanced_fragments(call)]
    fields = grounded_kie_fields(kie_calls, fragments, field_labels=field_labels)
    tables = [
        table
        for call in table_calls
        if (table := table_from_call(call, table_code)) is not None
    ]
    seals = seal_candidates_from_fragments(fragments)
    model_calls = [_attempt_record(call) for call in calls]
    total_cost = round(sum(float(call.get("costCny") or 0.0) for call in calls), 6)

    required_field_codes = {str(item) for item in schema}
    formal_field_codes = {
        str(item.get("fieldCode") or "")
        for item in fields
        if item.get("formalEvidenceEligible") and item.get("fieldValue") not in (None, "")
    }
    quality_reasons: list[str] = []
    if not fragments:
        quality_reasons.append("FIELD_EVIDENCE_MISSING")
    if not required_field_codes.issubset(formal_field_codes):
        quality_reasons.append("FIELD_EVIDENCE_MISSING")
    formal_table_codes = {
        str(item.get("tableCode") or "")
        for item in tables
        if item.get("formalEvidenceEligible")
    }
    if set(required_tables) - formal_table_codes:
        quality_reasons.append("TABLE_EVIDENCE_MISSING")
    if seal_required and not any(item.get("formalEvidenceEligible") for item in seals):
        quality_reasons.append("SEAL_EVIDENCE_MISSING")
    invalid_grounded_fields = [field for field in fields if not field.get("formalEvidenceEligible")]
    reasons = sorted(set(quality_reasons))

    return {
        "status": "success" if fragments or fields or tables else "failed",
        "outcomeStatus": "completed" if not reasons else "partial",
        "parserVersion": "aliyun-qwen-ocr@1",
        "profileId": profile.get("profileId"),
        "documentType": profile.get("documentType"),
        "pages": pages,
        "fragments": fragments,
        "fields": fields,
        "tables": tables,
        "seals": seals,
        "signatures": [],
        "layoutBlocks": [],
        "engineRuns": [
            {
                "engine": "aliyun_qwen_ocr",
                "provider": "aliyun_model_studio",
                "model": current["official"]["primaryModel"],
                "status": "success" if calls else "failed",
                "durationMs": round((time.monotonic() - started) * 1000),
                "callCount": len(calls),
                "pageCount": len(rendered),
                "tasks": sorted({str(call.get("task") or "") for call in calls}),
                "engineAttempted": True,
                "engineExecuted": bool(calls),
            }
        ],
        "quality": {
            "status": "usable" if not reasons else "needs_human_review",
            "reasons": reasons,
            "blockingReasons": [{"code": reason} for reason in reasons],
        },
        "metadata": {
            "providerMode": current["mode"],
            "provider": "aliyun_model_studio",
            "model": current["official"]["primaryModel"],
            "selectedPageNos": selected_pages,
            "cloudGrounded": bool(fragments) and not invalid_grounded_fields,
            "providerRequestIds": [call.get("requestId") for call in calls if call.get("requestId")],
            "costCny": total_cost,
            "modelCallCount": len(calls),
            "sealRoiCallCount": sum(1 for call in calls if call.get("roiBbox")),
            "maxPagesPerBatch": current["render"]["maxPagesPerBatch"],
            "maxDocumentPages": current["render"]["maxDocumentPages"],
            "maxCostCnyPerDocument": current["render"]["maxCostCnyPerDocument"],
            "inputImageHashes": [str((call.get("input") or {}).get("sha256") or "") for call in calls],
        },
        "modelCallAttempts": model_calls,
        "costCny": total_cost,
        "groundingValidation": {
            "invalidCandidateIdCount": 0,
            "unsupportedAttributionCount": len(invalid_grounded_fields),
            "droppedUnsupportedAttributionCount": 0,
            "candidateRepairCount": 0,
            "validatedFieldCount": len(fields) - len(invalid_grounded_fields),
        },
    }


def official_ocr_extract(
    source_path: Path,
    *,
    profile: dict[str, Any],
    runtime: dict[str, Any] | None = None,
    client: AliyunQwenOcrClient | None = None,
    work_directory: Path,
    page_call_cache: dict[int, list[dict[str, Any]]] | None = None,
    page_completed: Callable[[int, int, int, list[dict[str, Any]]], None] | None = None,
    attempt_recorder: Callable[[dict[str, Any]], str | None] | None = None,
    budget_key: str | None = None,
) -> dict[str, Any]:
    current = runtime or ocr_runtime_config(validate=True)
    selected_pages = selected_source_pages(source_path, profile, current)
    if current["mode"] == "hybrid_auto":
        text_result = _local_text_layer_result(source_path, selected_pages, profile)
        if text_result is not None:
            return text_result

    ocr_client = client or AliyunQwenOcrClient(runtime=current, attempt_recorder=attempt_recorder)
    rendered = render_pages(source_path, selected_pages, work_directory / "pages")
    pages = _page_records(rendered)
    schema, field_labels = field_schema(profile)
    required_tables = [str(item) for item in profile.get("requiredTables") or [] if str(item)]
    seal_required = bool((profile.get("sealRules") or {}).get("required"))
    table_code = required_tables[0] if len(required_tables) == 1 else "official_table_page"
    total_pages = len(rendered)
    started = time.monotonic()
    page_results: dict[int, list[dict[str, Any]]] = {
        int(page_no): [item for item in calls if isinstance(item, dict)]
        for page_no, calls in (page_call_cache or {}).items()
    }
    for page_no in rendered:
        page_results.setdefault(int(page_no), [])

    budget_id = budget_key or hashlib.sha256(str(source_path.resolve()).encode("utf-8")).hexdigest()[:24]
    budget_limit = float(current["render"]["maxCostCnyPerDocument"])
    budget_stopped = threading.Event()
    budget_state: dict[str, Any] = {
        "current": 0.0,
        "remaining": budget_limit,
        "overrun": False,
        "overrunReason": None,
    }
    estimated_costs = {
        "advanced_recognition": 0.01,
        "key_information_extraction": 0.015,
        "table_parsing": 0.03,
    }

    def notify(page_no: int, completed: int) -> None:
        if page_completed:
            page_completed(page_no, completed, total_pages, page_results[page_no])

    def provider_call(
        image_path: Path,
        *,
        task: str,
        page_no: int,
        result_schema: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        if budget_stopped.is_set():
            return None
        estimate = estimated_costs.get(task, 0.02)
        try:
            reserve_official_ocr_cost(budget_id, estimate, budget_limit)
        except OfficialOcrBudgetExceeded:
            budget_stopped.set()
            return None
        try:
            call = ocr_client.call(
                image_path,
                task=task,
                page_no=page_no,
                result_schema=result_schema,
            )
        except Exception:
            reconciled = reconcile_official_ocr_cost(
                budget_id,
                reserved=estimate,
                actual=0.0,
                limit=budget_limit,
            )
            budget_state.update(reconciled)
            raise
        reconciled = reconcile_official_ocr_cost(
            budget_id,
            reserved=estimate,
            actual=float(call.get("costCny") or 0.0),
            limit=budget_limit,
        )
        budget_state.update(reconciled)
        if not reconciled["withinLimit"]:
            budget_stopped.set()
            budget_state["overrun"] = True
            budget_state["overrunReason"] = "BUDGET_OVERRUN_AFTER_PROVIDER_RESPONSE"
        call["budget"] = {
            "reservedCostCny": estimate,
            "actualCostCny": float(call.get("costCny") or 0.0),
            "documentCostCny": float(reconciled["current"]),
            "remainingCostCny": float(reconciled["remaining"]),
            "limitCostCny": budget_limit,
            "withinLimit": bool(reconciled["withinLimit"]),
        }
        return call

    def scan_advanced_page(page_no: int, image_path: Path) -> tuple[int, bool]:
        page_calls = page_results[page_no]
        base_calls = [
            item
            for item in page_calls
            if item.get("task") == "advanced_recognition"
            and not item.get("roiColor")
            and not item.get("tileRecovery")
        ]
        tile_calls = [item for item in page_calls if item.get("tileRecovery")]
        if base_calls and (not base_calls[-1].get("outputTruncated") or tile_calls):
            return page_no, False
        base_call = base_calls[-1] if base_calls else provider_call(
            image_path,
            task="advanced_recognition",
            page_no=page_no,
        )
        fresh = bool(base_call is not None and not base_calls)
        if fresh and base_call is not None:
            page_calls.append(base_call)
        if base_call is not None and base_call.get("outputTruncated") and not tile_calls:
            base_call["supersededByTiles"] = True
            for tile in _split_recovery_tiles(
                image_path,
                work_directory / "truncation-recovery" / f"page-{page_no}",
            ):
                tile_call = provider_call(tile["path"], task="advanced_recognition", page_no=page_no)
                if tile_call is None:
                    break
                tile_call.update(
                    {
                        "roiOffset": tile["offset"],
                        "roiBbox": tile["bbox"],
                        "tileRecovery": True,
                    }
                )
                page_calls.append(tile_call)
        return page_no, fresh

    with official_ocr_document_slot(current):
        rendered_items = sorted(rendered.items())
        window_size = int(current["render"]["maxPagesPerBatch"])
        completed_count = 0
        for offset in range(0, len(rendered_items), window_size):
            window = rendered_items[offset : offset + window_size]
            with ThreadPoolExecutor(max_workers=min(2, max(len(window), 1))) as executor:
                futures = [executor.submit(scan_advanced_page, page_no, path) for page_no, path in window]
                for future in as_completed(futures):
                    page_no, fresh = future.result()
                    completed_count += 1
                    if fresh or page_completed:
                        notify(page_no, completed_count)
            if budget_stopped.is_set():
                break

        advanced_calls = [
            item
            for page_calls in page_results.values()
            for item in page_calls
            if item.get("task") == "advanced_recognition"
            and not item.get("roiColor")
            and not item.get("supersededByTiles")
        ]
        fragments = [fragment for call in advanced_calls for fragment in _offset_advanced_fragments(call)]
        structured_limit = int(current["render"]["structuredPageLimit"])

        def run_structured(page_no: int, task: str) -> tuple[int, bool]:
            page_calls = page_results[page_no]
            if any(item.get("task") == task for item in page_calls):
                return page_no, False
            call = provider_call(
                rendered[page_no],
                task=task,
                page_no=page_no,
                result_schema=schema if task == "key_information_extraction" else None,
            )
            if call is None:
                return page_no, False
            page_calls.append(call)
            return page_no, True

        if schema and not budget_stopped.is_set():
            kie_pages = _structured_candidate_pages(
                rendered,
                fragments,
                labels=[*field_labels.values(), *schema.keys()],
                limit=structured_limit,
                table_mode=False,
            )
            with ThreadPoolExecutor(max_workers=min(2, len(kie_pages) or 1)) as executor:
                futures = [
                    executor.submit(run_structured, page_no, "key_information_extraction")
                    for page_no in kie_pages
                ]
                for future in as_completed(futures):
                    page_no, fresh = future.result()
                    if fresh:
                        notify(page_no, total_pages)

        if required_tables and not budget_stopped.is_set():
            table_pages = _structured_candidate_pages(
                rendered,
                fragments,
                labels=required_tables,
                limit=structured_limit,
                table_mode=True,
            )
            with ThreadPoolExecutor(max_workers=min(2, len(table_pages) or 1)) as executor:
                futures = [executor.submit(run_structured, page_no, "table_parsing") for page_no in table_pages]
                for future in as_completed(futures):
                    page_no, fresh = future.result()
                    if fresh:
                        notify(page_no, total_pages)

        current_advanced = [
            item
            for page_calls in page_results.values()
            for item in page_calls
            if item.get("task") == "advanced_recognition" and not item.get("supersededByTiles")
        ]
        current_fragments = [
            fragment for call in current_advanced for fragment in _offset_advanced_fragments(call)
        ]
        seal_limit = int(current["render"]["sealRoiLimitPerDocument"])
        existing_seal_roi_count = sum(1 for call in current_advanced if call.get("roiColor"))
        if seal_required and not seal_candidates_from_fragments(current_fragments) and not budget_stopped.is_set():
            for page_no, image_path in rendered_items:
                remaining = seal_limit - existing_seal_roi_count
                if remaining <= 0:
                    break
                seal_rois = detect_color_seal_rois(
                    image_path,
                    work_directory / "seal-rois" / f"page-{page_no}",
                    max_candidates=min(2, remaining),
                )
                for roi in seal_rois:
                    roi_call = provider_call(roi["path"], task="advanced_recognition", page_no=page_no)
                    if roi_call is None:
                        break
                    roi_call.update(
                        {
                            "roiOffset": [roi["bbox"][0], roi["bbox"][1]],
                            "roiBbox": roi["bbox"],
                            "roiColor": roi["color"],
                        }
                    )
                    page_results[page_no].append(roi_call)
                    existing_seal_roi_count += 1
                if seal_rois:
                    notify(page_no, total_pages)

    calls = [item for page_no in sorted(page_results) for item in page_results[page_no]]
    advanced_calls = [
        item
        for item in calls
        if item.get("task") == "advanced_recognition" and not item.get("supersededByTiles")
    ]
    kie_calls = [item for item in calls if item.get("task") == "key_information_extraction"]
    table_calls = [item for item in calls if item.get("task") == "table_parsing"]
    fragments = [fragment for call in advanced_calls for fragment in _offset_advanced_fragments(call)]
    fields = grounded_kie_fields(kie_calls, fragments, field_labels=field_labels)
    tables = [
        table
        for call in table_calls
        if (table := table_from_call(call, table_code, fragments)) is not None
    ]
    seals = seal_candidates_from_fragments(fragments)
    model_calls = [_attempt_record(call) for call in calls]
    total_cost = round(sum(float(call.get("costCny") or 0.0) for call in calls), 6)

    required_field_codes = {str(item) for item in schema}
    formal_field_codes = {
        str(item.get("fieldCode") or "")
        for item in fields
        if item.get("formalEvidenceEligible") and item.get("fieldValue") not in (None, "")
    }
    formal_table_codes = {
        str(item.get("tableCode") or "") for item in tables if item.get("formalEvidenceEligible")
    }
    quality_reasons: list[str] = []
    if not fragments or not required_field_codes.issubset(formal_field_codes):
        quality_reasons.append("FIELD_EVIDENCE_MISSING")
    if set(required_tables) - formal_table_codes:
        quality_reasons.append("TABLE_EVIDENCE_MISSING")
    if seal_required and not any(item.get("formalEvidenceEligible") for item in seals):
        quality_reasons.append("SEAL_EVIDENCE_MISSING")
    output_truncated = any(
        bool(call.get("outputTruncated")) and not call.get("supersededByTiles") for call in calls
    )
    if output_truncated:
        quality_reasons.append("OCR_OUTPUT_TRUNCATED")
    if budget_stopped.is_set():
        quality_reasons.append("DOCUMENT_COST_LIMIT_EXCEEDED")
    if budget_state.get("overrun"):
        quality_reasons.append("BUDGET_OVERRUN_AFTER_PROVIDER_RESPONSE")
    page_costs = {
        page_no: round(sum(float(item.get("costCny") or 0.0) for item in page_calls), 6)
        for page_no, page_calls in page_results.items()
    }
    expensive_pages = sorted(page_no for page_no, cost in page_costs.items() if cost > 0.02)
    if expensive_pages:
        quality_reasons.append("PAGE_COST_REVIEW_REQUIRED")
    invalid_grounded_fields = [field for field in fields if not field.get("formalEvidenceEligible")]
    reasons = sorted(set(quality_reasons))

    return {
        "status": "success" if fragments or fields or tables else "failed",
        "outcomeStatus": "completed" if not reasons else "partial",
        "parserVersion": "aliyun-qwen-ocr@2",
        "profileId": profile.get("profileId"),
        "documentType": profile.get("documentType"),
        "pages": pages,
        "fragments": fragments,
        "fields": fields,
        "tables": tables,
        "seals": seals,
        "signatures": [],
        "layoutBlocks": [],
        "engineRuns": [
            {
                "engine": "aliyun_qwen_ocr",
                "provider": "aliyun_model_studio",
                "model": current["official"]["primaryModel"],
                "status": "success" if calls else "failed",
                "durationMs": round((time.monotonic() - started) * 1000),
                "callCount": len(calls),
                "pageCount": len(rendered),
                "tasks": sorted({str(call.get("task") or "") for call in calls}),
                "engineAttempted": True,
                "engineExecuted": bool(calls),
            }
        ],
        "quality": {
            "status": "usable" if not reasons else "needs_human_review",
            "reasons": reasons,
            "blockingReasons": [{"code": reason} for reason in reasons],
        },
        "metadata": {
            "providerMode": current["mode"],
            "provider": "aliyun_model_studio",
            "model": current["official"]["primaryModel"],
            "selectedPageNos": selected_pages,
            "cloudGrounded": bool(fragments) and not invalid_grounded_fields,
            "providerRequestIds": [call.get("requestId") for call in calls if call.get("requestId")],
            "costCny": total_cost,
            "modelCallCount": len(calls),
            "sealRoiCallCount": sum(1 for call in calls if call.get("roiColor")),
            "maxPagesPerBatch": current["render"]["maxPagesPerBatch"],
            "maxDocumentPages": current["render"]["maxDocumentPages"],
            "maxCostCnyPerDocument": budget_limit,
            "structuredPageLimit": current["render"]["structuredPageLimit"],
            "formalReadinessProfileAllowed": str(profile.get("profileId") or "")
            in set(current.get("formalReadinessProfileAllowlist") or []),
            "outputTruncated": output_truncated,
            "budgetStopped": budget_stopped.is_set(),
            "budget": {
                "limitCostCny": budget_limit,
                "actualCostCny": float(budget_state.get("current") or total_cost),
                "remainingCostCny": float(budget_state.get("remaining") or 0.0),
                "overrun": bool(budget_state.get("overrun")),
                "overrunReason": budget_state.get("overrunReason"),
            },
            "pageCostsCny": page_costs,
            "expensivePageNos": expensive_pages,
            "truncationRecoveryCallCount": sum(1 for call in calls if call.get("tileRecovery")),
            "inputImageHashes": [str((call.get("input") or {}).get("sha256") or "") for call in calls],
        },
        "modelCallAttempts": model_calls,
        "costCny": total_cost,
        "groundingValidation": {
            "invalidCandidateIdCount": 0,
            "unsupportedAttributionCount": len(invalid_grounded_fields),
            "droppedUnsupportedAttributionCount": 0,
            "candidateRepairCount": 0,
            "validatedFieldCount": len(fields) - len(invalid_grounded_fields),
            "outputTruncated": output_truncated,
        },
    }


def profile_result_complete(result: dict[str, Any], profile: dict[str, Any]) -> bool:
    field_codes = {
        str(item.get("fieldCode") or item.get("fieldName") or "")
        for item in result.get("fields") or []
        if isinstance(item, dict)
        and item.get("formalEvidenceEligible", True)
        and item.get("fieldValue") not in (None, "")
    }
    structured = profile.get("structuredExtraction") if isinstance(profile.get("structuredExtraction"), dict) else {}
    configured_fields = structured.get("fields") if isinstance(structured.get("fields"), list) else []
    required_fields = {
        str(item)
        for item in (configured_fields or profile.get("requiredFields") or [])
        if str(item) and str(item) != "seal"
    }
    table_codes = {
        str(item.get("tableCode") or item.get("tableId") or "")
        for item in result.get("tables") or []
        if isinstance(item, dict) and item.get("formalEvidenceEligible")
    }
    required_tables = {str(item) for item in profile.get("requiredTables") or [] if str(item)}
    seal_required = bool((profile.get("sealRules") or {}).get("required"))
    seal_ready = not seal_required or any(
        bool(item.get("formalEvidenceEligible") and item.get("canSatisfyRequiredSeal"))
        for item in result.get("seals") or []
        if isinstance(item, dict)
    )
    return required_fields.issubset(field_codes) and required_tables.issubset(table_codes) and seal_ready
