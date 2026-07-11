from __future__ import annotations

import base64
import json
import mimetypes
import os
import re
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any, Iterable

from apps.ocr_service.profiles import profile_for
from libs.document_ai_shadow import (
    build_evidence_prior,
    stable_payload_hash,
    validate_shadow_attribution,
)


PIPELINE_VERSION = "ocr-accuracy-first@1"
PIPELINE_STAGES = (
    ("prepare", "资料准备", 5),
    ("text_scan", "文本扫描", 30),
    ("structure_scan", "表格与版面", 48),
    ("seal_signature_scan", "印章与签名候选", 60),
    ("evidence_fusion", "证据融合", 68),
    ("qwen_extract", "Qwen 结构化复核", 84),
    ("grounding_validate", "证据归因校验", 94),
    ("finalize", "结果入库", 100),
)
PIPELINE_STAGE_LABELS = {key: label for key, label, _ in PIPELINE_STAGES}
PIPELINE_STAGE_PROGRESS = {key: progress for key, _, progress in PIPELINE_STAGES}
PIPELINE_TERMINAL_STATUSES = {"completed", "partial", "failed", "canceled"}
DEFAULT_PROFILE_ALLOWLIST = {
    "ndt_rt_report_v1",
    "quality_certificate_v1",
    "engineering_drawing_list_v1",
    "piping_characteristic_list_v1",
    "comprehensive_material_list_v1",
}
GENERIC_PROFILE_IDS = {"", "generic_document_v1"}
FILENAME_PROFILE_SIGNALS = (
    ("ndt_rt_report_v1", ("射线检测", "射线探伤", "RT检测", "RT报告", "RADIOGRAPHIC")),
    ("quality_certificate_v1", ("质量证明", "材质证明", "产品合格证", "质量证书")),
    ("engineering_drawing_list_v1", ("工艺图纸目录", "图纸目录", "DRAWINGLIST")),
    ("piping_characteristic_list_v1", ("管道特性表", "PIPINGCHARACTERISTIC")),
    ("comprehensive_material_list_v1", ("综合材料表", "COMPREHENSIVEMATERIALLIST")),
)


def pipeline_mode() -> str:
    value = str(os.getenv("AICHECK_OCR_PIPELINE_MODE") or "shadow").strip().lower()
    return value if value in {"off", "shadow", "active"} else "off"


def pipeline_version() -> str:
    return str(os.getenv("AICHECK_OCR_PIPELINE_VERSION") or PIPELINE_VERSION).strip() or PIPELINE_VERSION


def pipeline_profile_allowlist() -> set[str]:
    raw = str(os.getenv("AICHECK_OCR_PIPELINE_PROFILE_ALLOWLIST") or "").strip()
    if not raw:
        return set(DEFAULT_PROFILE_ALLOWLIST)
    return {item.strip() for item in raw.split(",") if item.strip()}


def pipeline_enabled(profile_id: str | None, *, source_type: str | None = None) -> bool:
    if pipeline_mode() == "off" or source_type == "standard":
        return False
    return bool(profile_id and str(profile_id) in pipeline_profile_allowlist())


def infer_preliminary_profile_id(
    file_name: str | None,
    profile_id: str | None,
    document_type: str | None,
) -> str:
    requested = profile_for(profile_id, document_type)
    requested_profile_id = str(requested.get("profileId") or "generic_document_v1")
    if requested_profile_id not in GENERIC_PROFILE_IDS:
        return requested_profile_id
    normalized_name = re.sub(r"[\s_.\-/]+", "", Path(str(file_name or "")).stem).upper()
    for detected_profile_id, signals in FILENAME_PROFILE_SIGNALS:
        if any(signal.upper() in normalized_name for signal in signals):
            return detected_profile_id
    return requested_profile_id


def profile_from_ocr_result(result: dict[str, Any], fallback_profile: dict[str, Any]) -> dict[str, Any]:
    metadata = result.get("metadata") if isinstance(result.get("metadata"), dict) else {}
    detected_profile_id = str(
        result.get("profileId")
        or metadata.get("detectedProfileId")
        or fallback_profile.get("profileId")
        or "generic_document_v1"
    )
    detected_document_type = str(
        result.get("documentType")
        or fallback_profile.get("documentType")
        or "generic_document"
    )
    return profile_for(detected_profile_id, detected_document_type)


def pipeline_run_key(
    document_id: str,
    version_id: str,
    storage_key: str,
    profile_id: str | None,
) -> str:
    return stable_payload_hash(
        {
            "documentId": document_id,
            "documentVersionId": version_id,
            "storageKey": storage_key,
            "profileId": profile_id,
            "pipelineVersion": pipeline_version(),
        }
    )


def initial_stage_records(
    run_id: str,
    *,
    now: str,
    document_id: str | None = None,
    version_id: str | None = None,
) -> list[dict[str, Any]]:
    return [
        {
            "id": f"{run_id}-{stage}",
            "pipelineRunId": run_id,
            "documentId": document_id,
            "documentVersionId": version_id,
            "stage": stage,
            "stageLabel": label,
            "status": "queued",
            "progress": progress,
            "attempt": 0,
            "createdAt": now,
            "updatedAt": now,
            "startedAt": None,
            "finishedAt": None,
            "artifactUrl": None,
            "artifactHash": None,
            "engineStatus": {},
            "blockingReasons": [],
        }
        for stage, label, progress in PIPELINE_STAGES
    ]


def page_numbers(parse_result: dict[str, Any]) -> list[int]:
    values: set[int] = set()
    for collection in ("pages", "fragments", "fields", "tables", "seals", "layoutBlocks"):
        for item in parse_result.get(collection) or []:
            if not isinstance(item, dict):
                continue
            try:
                page_no = int(item.get("pageNo") or 0)
            except (TypeError, ValueError):
                page_no = 0
            if page_no > 0:
                values.add(page_no)
    if not values:
        values.add(1)
    maximum = max(1, int(os.getenv("AICHECK_OCR_QWEN_MAX_PAGES", "60")))
    return sorted(values)[:maximum]


def page_batches(parse_result: dict[str, Any], *, size: int = 4) -> list[list[int]]:
    size = max(1, min(int(size), 4))
    pages = page_numbers(parse_result)
    return [pages[offset : offset + size] for offset in range(0, len(pages), size)]


def parse_result_for_pages(parse_result: dict[str, Any], selected_pages: Iterable[int]) -> dict[str, Any]:
    selected = {int(value) for value in selected_pages}
    output = deepcopy(parse_result)
    for collection in ("pages", "fragments", "fields", "tables", "seals", "layoutBlocks"):
        output[collection] = [
            item
            for item in parse_result.get(collection) or []
            if isinstance(item, dict) and int(item.get("pageNo") or 1) in selected
        ]
    return output


def build_batch_prior(parse_result: dict[str, Any], profile: dict[str, Any], selected_pages: list[int]) -> dict[str, Any]:
    scoped = parse_result_for_pages(parse_result, selected_pages)
    prior = build_evidence_prior(
        scoped,
        profile,
        max_candidates=64,
        max_tokens=12_000,
        max_pages=max(1, len(selected_pages)),
    )
    prior["compact"]["selectedPageNos"] = list(selected_pages)
    prior["full"]["selectedPageNos"] = list(selected_pages)
    return prior


def render_pages(source_path: Path, selected_pages: list[int], output_directory: Path) -> dict[int, Path]:
    output_directory.mkdir(parents=True, exist_ok=True)
    with source_path.open("rb") as handle:
        signature = handle.read(4)
    if signature == b"%PDF":
        import fitz

        document = fitz.open(source_path)
        rendered: dict[int, Path] = {}
        try:
            for page_no in selected_pages:
                if page_no < 1 or page_no > document.page_count:
                    continue
                page = document.load_page(page_no - 1)
                long_side = max(float(page.rect.width), float(page.rect.height), 1.0)
                scale = max(1.0, min(4.0, 2200.0 / long_side))
                pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
                target = output_directory / f"page-{page_no:04d}.png"
                pixmap.save(target)
                rendered[page_no] = target
        finally:
            document.close()
        return rendered
    if 1 not in selected_pages:
        return {}
    from PIL import Image

    target = output_directory / "page-0001.png"
    with Image.open(source_path) as image:
        converted = image.convert("RGB")
        converted.thumbnail((2200, 2200))
        converted.save(target, "PNG", optimize=True)
    return {1: target}


def _page_dimensions(parse_result: dict[str, Any]) -> dict[int, tuple[float, float]]:
    output: dict[int, tuple[float, float]] = {}
    for index, page in enumerate(parse_result.get("pages") or [], start=1):
        if not isinstance(page, dict):
            continue
        try:
            page_no = int(page.get("pageNo") or index)
            width = float(page.get("width") or page.get("pageWidth") or 0)
            height = float(page.get("height") or page.get("pageHeight") or 0)
        except (TypeError, ValueError):
            continue
        if width > 0 and height > 0:
            output[page_no] = (width, height)
    return output


def render_candidate_rois(
    rendered_pages: dict[int, Path],
    parse_result: dict[str, Any],
    compact_prior: dict[str, Any],
    output_directory: Path,
    *,
    limit: int = 12,
) -> list[dict[str, Any]]:
    from PIL import Image

    dimensions = _page_dimensions(parse_result)
    candidates = [
        item
        for item in compact_prior.get("candidates") or []
        if isinstance(item, dict)
        and isinstance(item.get("bbox"), list)
        and item.get("candidateType") in {"field", "table_cell", "seal_crop"}
    ][: max(0, limit)]
    rois: list[dict[str, Any]] = []
    output_directory.mkdir(parents=True, exist_ok=True)
    for index, candidate in enumerate(candidates, start=1):
        page_no = int(candidate.get("pageNo") or 1)
        page_path = rendered_pages.get(page_no)
        if not page_path:
            continue
        bbox = candidate.get("bbox") or []
        if len(bbox) < 4:
            continue
        with Image.open(page_path) as image:
            source_width, source_height = dimensions.get(page_no, image.size)
            scale_x = image.width / max(float(source_width), 1.0)
            scale_y = image.height / max(float(source_height), 1.0)
            x1, y1, x2, y2 = [float(value) for value in bbox[:4]]
            padding_x = max((x2 - x1) * 0.12, 12.0)
            padding_y = max((y2 - y1) * 0.12, 12.0)
            crop_box = (
                max(0, int((x1 - padding_x) * scale_x)),
                max(0, int((y1 - padding_y) * scale_y)),
                min(image.width, int((x2 + padding_x) * scale_x)),
                min(image.height, int((y2 + padding_y) * scale_y)),
            )
            if crop_box[2] <= crop_box[0] or crop_box[3] <= crop_box[1]:
                continue
            target = output_directory / f"roi-{page_no:04d}-{index:02d}.png"
            image.convert("RGB").crop(crop_box).save(target, "PNG", optimize=True)
        rois.append(
            {
                "path": target,
                "pageNo": page_no,
                "candidateIds": [str(candidate.get("candidateId"))],
            }
        )
    return rois


def image_data_url(path: Path) -> str:
    mime_type = mimetypes.guess_type(path.name)[0] or "image/png"
    return f"data:{mime_type};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"


def qwen_messages(
    rendered_pages: dict[int, Path],
    rois: list[dict[str, Any]],
    profile: dict[str, Any],
    compact_prior: dict[str, Any],
) -> list[dict[str, Any]]:
    structured = profile.get("structuredExtraction") if isinstance(profile.get("structuredExtraction"), dict) else {}
    content: list[dict[str, Any]] = []
    for page_no, path in sorted(rendered_pages.items()):
        content.append({"type": "text", "text": f"原始页面 pageNo={page_no}"})
        content.append({"type": "image_url", "image_url": {"url": image_data_url(path)}})
    for roi in rois:
        content.append(
            {
                "type": "text",
                "text": (
                    f"证据 ROI pageNo={roi['pageNo']} candidateIds="
                    + ",".join(roi.get("candidateIds") or [])
                ),
            }
        )
        content.append({"type": "image_url", "image_url": {"url": image_data_url(roi["path"])}})
    request_payload = {
        "profileId": profile.get("profileId"),
        "requiredFields": profile.get("requiredFields") or [],
        "requiredTables": profile.get("requiredTables") or [],
        "fieldDefinitions": structured.get("fieldDefinitions") or {},
        "evidencePrior": compact_prior,
        "outputContract": {
            "fields": {"field_code": {"value": None, "sourceCandidateIds": []}},
            "tables": {"table_code": [{"cells": {}, "sourceCandidateIds": []}]},
            "seals": [{"value": None, "sealType": None, "sourceCandidateIds": []}],
            "missingRequiredFields": [],
        },
    }
    content.append(
        {
            "type": "text",
            "text": (
                "请从原始页面和 EvidencePrior 中抽取结构化 JSON。每个非空值必须引用实际存在的 "
                "sourceCandidateIds；禁止自行生成 bbox、页码或候选 ID。看不清时返回 null，不得推断。"
                "日期必须区分印章日期、签发日期和有效期；表格检测比例、技术等级、评定级别不得混用。"
                "只输出 JSON，不输出解释。输入如下：\n"
                + json.dumps(request_payload, ensure_ascii=False, separators=(",", ":"))
            ),
        }
    )
    return [
        {
            "role": "system",
            "content": (
                "你是工业工程资料结构化复核器。OCR 候选是唯一可归因证据；视觉只能辅助选择候选，"
                "不能创造正式证据。"
            ),
        },
        {"role": "user", "content": content},
    ]


def parse_qwen_json(response: dict[str, Any]) -> dict[str, Any]:
    choices = response.get("choices") if isinstance(response.get("choices"), list) else []
    message = (choices[0] or {}).get("message") if choices and isinstance(choices[0], dict) else {}
    raw = message.get("content") if isinstance(message, dict) else None
    if isinstance(raw, list):
        raw = "".join(str(item.get("text") or "") for item in raw if isinstance(item, dict))
    if isinstance(raw, dict):
        return raw
    text = str(raw or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
        text = text.rsplit("```", 1)[0].strip()
        if text.lower().startswith("json"):
            text = text[4:].lstrip()
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError("qwen_structured_output_must_be_object")
    return parsed


def merge_batch_outputs(outputs: list[dict[str, Any]]) -> dict[str, Any]:
    merged: dict[str, Any] = {"fields": {}, "tables": {}, "seals": [], "missingRequiredFields": []}
    conflicts: list[dict[str, Any]] = []
    for output in outputs:
        for key, item in (output.get("fields") or {}).items():
            if not isinstance(item, dict) or item.get("value") in {None, ""}:
                continue
            existing = merged["fields"].get(key)
            if existing and str(existing.get("value")) != str(item.get("value")):
                conflicts.append({"fieldCode": key, "values": [existing.get("value"), item.get("value")]})
                if existing.get("attributionStatus") == "validated":
                    continue
            merged["fields"][key] = deepcopy(item)
        for key, rows in (output.get("tables") or {}).items():
            if not isinstance(rows, list):
                continue
            destination = merged["tables"].setdefault(key, [])
            seen = {stable_payload_hash(item) for item in destination}
            for row in rows:
                if isinstance(row, dict) and stable_payload_hash(row) not in seen:
                    destination.append(deepcopy(row))
                    seen.add(stable_payload_hash(row))
        for seal in output.get("seals") or []:
            if isinstance(seal, dict) and stable_payload_hash(seal) not in {
                stable_payload_hash(item) for item in merged["seals"]
            }:
                merged["seals"].append(deepcopy(seal))
        merged["missingRequiredFields"].extend(str(value) for value in output.get("missingRequiredFields") or [])
    merged["missingRequiredFields"] = sorted(set(merged["missingRequiredFields"]))
    merged["conflicts"] = conflicts
    return merged


def validate_batch_output(output: dict[str, Any], compact_prior: dict[str, Any]) -> dict[str, Any]:
    return validate_shadow_attribution(output, compact_prior)


def validated_ocr_fields(
    structured_output: dict[str, Any],
    profile: dict[str, Any],
    all_candidates: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    structured = profile.get("structuredExtraction") if isinstance(profile.get("structuredExtraction"), dict) else {}
    field_definitions = structured.get("fieldDefinitions") if isinstance(structured.get("fieldDefinitions"), dict) else {}
    output: list[dict[str, Any]] = []
    for field_code, item in (structured_output.get("fields") or {}).items():
        if not isinstance(item, dict) or item.get("attributionStatus") != "validated":
            continue
        value = item.get("value")
        candidate_ids = [str(value) for value in item.get("sourceCandidateIds") or []]
        candidates = [all_candidates[candidate_id] for candidate_id in candidate_ids if candidate_id in all_candidates]
        if value in {None, ""} or not candidates or not all(candidate.get("formalEvidenceEligible") for candidate in candidates):
            continue
        confidences = [float(candidate.get("confidence") or 0.8) for candidate in candidates]
        output.append(
            {
                "fieldCode": str(field_code),
                "fieldName": str(field_definitions.get(field_code) or field_code),
                "fieldValue": str(value),
                "pageNo": item.get("evidencePageNo") or candidates[0].get("pageNo") or 1,
                "bbox": item.get("evidenceBbox") or candidates[0].get("bbox"),
                "confidence": round(min(0.95, max(confidences or [0.8])), 4),
                "sourceMethod": "qwen_grounded_candidate",
                "sourceEngine": "qwen3.7-plus",
                "sourceCandidateIds": candidate_ids,
                "reviewStatus": "待确认",
                "formalEvidenceEligible": True,
            }
        )
    return output


def merge_grounded_fields(parse_result: dict[str, Any], grounded_fields: list[dict[str, Any]]) -> dict[str, Any]:
    merged = deepcopy(parse_result)
    existing = {
        str(item.get("fieldCode") or item.get("fieldName") or ""): item
        for item in merged.get("fields") or []
        if isinstance(item, dict)
    }
    for field in grounded_fields:
        key = str(field.get("fieldCode") or field.get("fieldName") or "")
        current = existing.get(key)
        if current is None or float(field.get("confidence") or 0) >= float(current.get("confidence") or 0):
            existing[key] = field
    merged["fields"] = list(existing.values())
    merged.setdefault("diagnostics", []).append(
        {
            "code": "QWEN_GROUNDED_CANDIDATES_MERGED",
            "level": "info",
            "fieldCount": len(grounded_fields),
        }
    )
    return merged


def required_field_blockers(parse_result: dict[str, Any], profile: dict[str, Any]) -> list[dict[str, Any]]:
    required = {str(value) for value in profile.get("requiredFields") or [] if str(value) and str(value) != "seal"}
    available = {
        str(item.get("fieldCode") or item.get("fieldName") or "")
        for item in parse_result.get("fields") or []
        if isinstance(item, dict)
        and item.get("fieldValue") is not None
        and item.get("fieldValue") != ""
        and item.get("bbox")
    }
    return [
        {"code": "REQUIRED_FIELD_MISSING", "fieldCode": field_code}
        for field_code in sorted(required - available)
    ]


def default_profile(profile_id: str | None, document_type: str | None) -> dict[str, Any]:
    return profile_for(profile_id, document_type)


def temporary_pipeline_directory(run_id: str) -> Path:
    return Path(tempfile.mkdtemp(prefix=f"aicheck-ocr-pipeline-{re.sub(r'[^A-Za-z0-9_-]', '-', run_id)}-"))
