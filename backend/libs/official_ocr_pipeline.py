from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Any, Callable

from PIL import Image

from libs.aliyun_ocr import (
    AliyunQwenOcrClient,
    advanced_fragments,
    grounded_kie_fields,
    seal_candidates_from_fragments,
    table_from_call,
)
from libs.ocr_accuracy_pipeline import render_pages
from libs.ocr_runtime import ocr_runtime_config


def selected_source_pages(source_path: Path, profile: dict[str, Any], runtime: dict[str, Any]) -> list[int]:
    maximum = max(1, min(int(runtime["render"]["maxPages"]), 50))
    if source_path.suffix.lower() != ".pdf":
        return [1]
    try:
        import fitz

        with fitz.open(source_path) as document:
            total = int(document.page_count)
    except Exception:
        return [1]
    structured = profile.get("structuredExtraction") if isinstance(profile.get("structuredExtraction"), dict) else {}
    configured = structured.get("maxPages") or maximum
    try:
        profile_limit = int(configured)
    except (TypeError, ValueError):
        profile_limit = maximum
    limit = max(1, min(profile_limit, maximum, total))
    if total <= limit:
        return list(range(1, total + 1))
    if limit == 1:
        return [1]
    return [*range(1, limit), total]


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
    }


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


def official_ocr_extract(
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
    table_code = required_tables[0] if len(required_tables) == 1 else "official_table_page"
    started = time.monotonic()

    total_pages = len(rendered)
    for completed_count, (page_no, image_path) in enumerate(sorted(rendered.items()), start=1):
        page_calls = [
            item
            for item in (page_call_cache or {}).get(int(page_no), [])
            if isinstance(item, dict)
        ]
        if not page_calls:
            advanced = ocr_client.call(image_path, task="advanced_recognition", page_no=page_no)
            page_calls.append(advanced)
            if schema:
                page_calls.append(
                    ocr_client.call(
                        image_path,
                        task="key_information_extraction",
                        page_no=page_no,
                        result_schema=schema,
                    )
                )
            if required_tables:
                page_calls.append(
                    ocr_client.call(image_path, task="table_parsing", page_no=page_no)
                )
            if page_completed:
                page_completed(page_no, completed_count, total_pages, page_calls)
        calls.extend(page_calls)
        advanced_calls.extend(item for item in page_calls if item.get("task") == "advanced_recognition")
        kie_calls.extend(item for item in page_calls if item.get("task") == "key_information_extraction")
        table_calls.extend(item for item in page_calls if item.get("task") == "table_parsing")

    fragments = [fragment for call in advanced_calls for fragment in advanced_fragments(call)]
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
    seal_required = bool((profile.get("sealRules") or {}).get("required"))
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
