from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from libs.integrations.storage import object_storage, parse_storage_url


AGENTDESIGN_BACKEND = Path("/Volumes/Volume/project/agentdesign/mvp-system/backend")
if AGENTDESIGN_BACKEND.exists() and str(AGENTDESIGN_BACKEND) not in sys.path:
    sys.path.append(str(AGENTDESIGN_BACKEND))


class OcrService:
    def __init__(self) -> None:
        self.pipeline = self._load_pipeline()

    def _load_pipeline(self) -> Any | None:
        try:
            from seal_ocr.pipeline import recognize_document  # type: ignore

            return recognize_document
        except Exception:
            try:
                from seal_ocr.pipeline import SealOcrPipeline  # type: ignore

                return SealOcrPipeline()
            except Exception:
                return None

    def parse_document(self, storage_key: str, *, file_name: str | None = None) -> dict[str, Any]:
        if self.pipeline is not None:
            try:
                source_path = resolve_source_path(storage_key, file_name)
                if source_path is not None:
                    if callable(self.pipeline):
                        result = self.pipeline(source_path)  # type: ignore[misc]
                    else:
                        result = self.pipeline.run(str(source_path))  # type: ignore[attr-defined]
                    return normalize_ocr_result(result, storage_key, file_name)
            except Exception as exc:
                return failed_result(storage_key, file_name, str(exc))
        return normalize_ocr_result(
            {
                "text": f"OCR placeholder for {file_name or storage_key}",
                "fields": [],
                "seals": [],
                "diagnostics": ["agentdesign OCR pipeline not importable; placeholder result generated."],
            },
            storage_key,
            file_name,
        )


def normalize_ocr_result(raw: Any, storage_key: str, file_name: str | None = None) -> dict[str, Any]:
    text = raw.get("text") if isinstance(raw, dict) else str(raw)
    fields = raw.get("fields", []) if isinstance(raw, dict) else []
    seals = raw.get("seals", []) if isinstance(raw, dict) else []
    diagnostics = normalize_diagnostics(raw.get("diagnostics", []) if isinstance(raw, dict) else [])
    if isinstance(raw, dict) and raw.get("ok") is False:
        return failed_result(storage_key, file_name, raw.get("error") or "OCR failed")
    normalized_fields = normalize_raw_fields(fields)
    normalized_fields.extend(fields_from_seals(seals))
    fragments = normalize_fragments(raw, text)
    return {
        "storageKey": storage_key,
        "fileName": file_name,
        "status": "success",
        "fragments": fragments,
        "fields": normalized_fields,
        "seals": seals,
        "diagnostics": diagnostics,
    }


def failed_result(storage_key: str, file_name: str | None, message: str) -> dict[str, Any]:
    return {
        "storageKey": storage_key,
        "fileName": file_name,
        "status": "failed",
        "fragments": [],
        "fields": [],
        "seals": [],
        "diagnostics": [message],
    }


ocr_service = OcrService()


def resolve_source_path(storage_key: str, file_name: str | None) -> Path | None:
    direct = Path(storage_key)
    if direct.is_file():
        return direct
    parsed = parse_storage_url(storage_key)
    bucket = "documents"
    object_name = storage_key
    if parsed:
        bucket, object_name = parsed
    suffix = Path(file_name or object_name).suffix
    try:
        return object_storage.download_to_temp(bucket, object_name, suffix=suffix)
    except Exception:
        return None


def normalize_diagnostics(raw: Any) -> list[str]:
    if not raw:
        return []
    normalized = []
    for item in raw if isinstance(raw, list) else [raw]:
        if isinstance(item, dict):
            normalized.append(str(item.get("message") or item))
        else:
            normalized.append(str(item))
    return normalized


def normalize_raw_fields(raw_fields: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_fields, list):
        return []
    normalized = []
    for raw in raw_fields:
        if not isinstance(raw, dict):
            continue
        name = raw.get("fieldName") or raw.get("field") or raw.get("name")
        value = raw.get("fieldValue") or raw.get("value") or raw.get("text")
        if not name or value is None:
            continue
        normalized.append(
            {
                "fieldName": str(name),
                "fieldValue": str(value),
                "pageNo": raw.get("pageNo") or raw.get("page_index", 0) + 1,
                "bbox": raw.get("bbox") or raw.get("polygon"),
                "confidence": raw.get("confidence") or raw.get("calibrated_confidence") or 0.8,
                "extractionMethod": raw.get("extractionMethod") or "PaddleOCR",
            }
        )
    return normalized


def fields_from_seals(seals: Any) -> list[dict[str, Any]]:
    if not isinstance(seals, list):
        return []
    fields = []
    for seal in seals:
        if not isinstance(seal, dict):
            continue
        page_no = int(seal.get("page_index") or 0) + 1
        polygon = seal.get("polygon")
        for key, value in (seal.get("fields") or {}).items():
            if not isinstance(value, dict) or not value.get("value"):
                continue
            fields.append(
                {
                    "fieldName": seal_field_label(key),
                    "fieldValue": str(value["value"]),
                    "pageNo": page_no,
                    "bbox": polygon,
                    "confidence": value.get("calibrated_confidence") or value.get("visual_confidence") or 0.8,
                    "extractionMethod": "PaddleOCR+seal",
                }
            )
    return fields


def seal_field_label(key: str) -> str:
    return {
        "organization_name": "单位名称",
        "certificate_number": "证书编号",
        "license_scope": "许可范围",
        "valid_until": "有效期至",
        "issuer_or_seal_name": "印章名称",
    }.get(key, key)


def normalize_fragments(raw: Any, text: str | None) -> list[dict[str, Any]]:
    if isinstance(raw, dict) and isinstance(raw.get("fragments"), list):
        return raw["fragments"]
    summary = ""
    if isinstance(raw, dict):
        summary = str(raw.get("document_summary") or raw.get("candidate_summary") or "")
    return [{"pageNo": 1, "text": text or summary or "", "bbox": None, "confidence": 0.8}]
