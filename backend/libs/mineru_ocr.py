from __future__ import annotations

import hashlib
import io
import json
import stat
import zipfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any
from uuid import uuid4

from apps.ocr_service.engines import html_table_to_structure
from libs.contracts.responses import server_time


MAX_ZIP_MEMBERS = 5_000
MAX_ZIP_MEMBER_BYTES = 128 * 1024 * 1024
MAX_ZIP_TOTAL_BYTES = 1024 * 1024 * 1024

_BLOCK_TYPE_MAP = {
    "title": "title",
    "text": "text",
    "equation": "equation",
    "interline_equation": "equation",
    "code": "code",
    "list": "list",
    "image_caption": "caption",
    "table_caption": "caption",
    "header": "header",
    "page_header": "header",
    "footer": "footer",
    "page_footer": "footer",
    "page_footnote": "footnote",
}


class MinerUNormalizationError(RuntimeError):
    def __init__(self, code: str, safe_message: str) -> None:
        super().__init__(safe_message)
        self.code = code


@dataclass(frozen=True)
class MinerUArtifact:
    name: str
    data: bytes
    content_type: str
    sha256: str


@dataclass(frozen=True)
class MinerUNormalizedBundle:
    result: dict[str, Any]
    artifacts: dict[str, MinerUArtifact]


def normalize_mineru_zip(
    zip_bytes: bytes,
    *,
    storage_key: str,
    file_name: str,
    profile_id: str | None,
    document_type: str | None,
    provider_task_id: str,
) -> MinerUNormalizedBundle:
    members = validated_zip_members(zip_bytes)
    content_name = unique_artifact_name(
        members,
        "_content_list.json",
        required=True,
        missing_code="MINERU_CONTENT_LIST_MISSING",
    )
    middle_name = unique_artifact_name(
        members,
        "_middle.json",
        required=True,
        missing_code="MINERU_MIDDLE_JSON_MISSING",
    )
    markdown_name = primary_markdown_name(members)
    content = _load_json(members[content_name], expected_type=list)
    middle = _load_json(members[middle_name], expected_type=dict)
    pages = mineru_pages(middle)
    result = build_mineru_result(
        content,
        pages=pages,
        storage_key=storage_key,
        file_name=file_name,
        profile_id=profile_id,
        document_type=document_type,
        provider_task_id=provider_task_id,
        markdown_present=markdown_name is not None,
    )
    artifacts = build_mineru_artifacts(
        zip_bytes,
        content_bytes=members[content_name],
        middle_bytes=members[middle_name],
        markdown_bytes=members[markdown_name] if markdown_name else None,
        result=result,
    )
    return MinerUNormalizedBundle(result=result, artifacts=artifacts)


def validated_zip_members(zip_bytes: bytes) -> dict[str, bytes]:
    members: dict[str, bytes] = {}
    try:
        archive = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except (zipfile.BadZipFile, OSError) as exc:
        raise MinerUNormalizationError(
            "MINERU_ZIP_INVALID",
            "MinerU result archive is invalid.",
        ) from exc
    with archive:
        infos = archive.infolist()
        if len(infos) > MAX_ZIP_MEMBERS:
            raise MinerUNormalizationError(
                "MINERU_ZIP_TOO_MANY_MEMBERS",
                "MinerU result archive contains too many files.",
            )
        total_size = 0
        for info in infos:
            name = info.filename
            path = PurePosixPath(name)
            if (
                not name
                or "\\" in name
                or path.is_absolute()
                or ".." in path.parts
            ):
                raise MinerUNormalizationError(
                    "MINERU_ZIP_UNSAFE_PATH",
                    "MinerU result archive contains an unsafe path.",
                )
            unix_mode = info.external_attr >> 16
            if stat.S_IFMT(unix_mode) == stat.S_IFLNK:
                raise MinerUNormalizationError(
                    "MINERU_ZIP_SYMLINK",
                    "MinerU result archive contains a symbolic link.",
                )
            if info.flag_bits & 0x1:
                raise MinerUNormalizationError(
                    "MINERU_ZIP_ENCRYPTED",
                    "MinerU result archive contains an encrypted file.",
                )
            if info.is_dir():
                continue
            if name in members:
                raise MinerUNormalizationError(
                    "MINERU_ZIP_DUPLICATE_MEMBER",
                    "MinerU result archive contains duplicate files.",
                )
            if info.file_size > MAX_ZIP_MEMBER_BYTES:
                raise MinerUNormalizationError(
                    "MINERU_ZIP_MEMBER_TOO_LARGE",
                    "MinerU result archive contains an oversized file.",
                )
            total_size += info.file_size
            if total_size > MAX_ZIP_TOTAL_BYTES:
                raise MinerUNormalizationError(
                    "MINERU_ZIP_EXPANSION_TOO_LARGE",
                    "MinerU result archive expands beyond the allowed size.",
                )
            try:
                data = archive.read(info)
            except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
                raise MinerUNormalizationError(
                    "MINERU_ZIP_READ_FAILED",
                    "MinerU result archive could not be read.",
                ) from exc
            if len(data) != info.file_size:
                raise MinerUNormalizationError(
                    "MINERU_ZIP_SIZE_MISMATCH",
                    "MinerU result archive contains an invalid file.",
                )
            members[name] = data
    return members


def unique_artifact_name(
    members: Mapping[str, bytes],
    suffix: str,
    *,
    required: bool,
    missing_code: str,
) -> str | None:
    matches = sorted(name for name in members if name.endswith(suffix))
    if len(matches) > 1:
        raise MinerUNormalizationError(
            "MINERU_ARTIFACT_AMBIGUOUS",
            "MinerU result archive contains ambiguous artifacts.",
        )
    if not matches:
        if required:
            raise MinerUNormalizationError(
                missing_code,
                "MinerU result archive omitted a required artifact.",
            )
        return None
    return matches[0]


def primary_markdown_name(members: Mapping[str, bytes]) -> str | None:
    exact = sorted(
        name
        for name in members
        if PurePosixPath(name).name.lower() == "full.md"
    )
    if exact:
        return exact[0]
    markdown = sorted(name for name in members if name.lower().endswith(".md"))
    return markdown[0] if markdown else None


def mineru_pages(middle: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw_pages = middle.get("pdf_info")
    if not isinstance(raw_pages, list):
        raw_pages = []
    pages: list[dict[str, Any]] = []
    for fallback_index, raw_page in enumerate(raw_pages):
        if not isinstance(raw_page, Mapping):
            continue
        page_index = _safe_int(raw_page.get("page_idx"), fallback_index)
        size = raw_page.get("page_size")
        if isinstance(size, Mapping):
            width = _safe_float(size.get("width"))
            height = _safe_float(size.get("height"))
        elif isinstance(size, (list, tuple)) and len(size) >= 2:
            width = _safe_float(size[0])
            height = _safe_float(size[1])
        else:
            width = None
            height = None
        if page_index < 0 or width is None or height is None:
            continue
        if width <= 0 or height <= 0:
            continue
        pages.append(
            {
                "pageNo": page_index + 1,
                "width": width,
                "height": height,
                "coordinateSystem": "rendered_pixels",
                "sourceCoordinateSystem": "mineru_normalized_1000",
            }
        )
    pages.sort(key=lambda item: item["pageNo"])
    return pages


def build_mineru_result(
    content: list[Any],
    *,
    pages: list[dict[str, Any]],
    storage_key: str,
    file_name: str,
    profile_id: str | None,
    document_type: str | None,
    provider_task_id: str,
    markdown_present: bool,
) -> dict[str, Any]:
    page_by_no = {int(page["pageNo"]): page for page in pages}
    fragments: list[dict[str, Any]] = []
    layout_blocks: list[dict[str, Any]] = []
    tables: list[dict[str, Any]] = []
    seals: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    reasons = ["provider_confidence_unavailable"]
    if not markdown_present:
        diagnostics.append(
            _diagnostic(
                "mineru_markdown_missing",
                "MinerU result did not include Markdown.",
                severity="warning",
            )
        )
    reading_order = 0
    coordinate_unmapped = False
    for source_index, raw_item in enumerate(content):
        if not isinstance(raw_item, Mapping):
            diagnostics.append(
                _diagnostic(
                    "mineru_content_item_invalid",
                    "MinerU content contained an invalid item.",
                    severity="warning",
                    sourceIndex=source_index,
                )
            )
            continue
        item_type = str(raw_item.get("type") or "text").lower()
        page_index = _safe_int(raw_item.get("page_idx"), 0)
        page_no = max(page_index + 1, 1)
        mapped_bbox, source_coordinate_system = _map_bbox(
            raw_item.get("bbox"),
            page_by_no.get(page_no),
        )
        if raw_item.get("bbox") is not None and mapped_bbox is None:
            coordinate_unmapped = True
            diagnostics.append(
                _diagnostic(
                    "coordinate_transform_unmapped",
                    "MinerU coordinates could not be mapped to rendered pixels.",
                    severity="warning",
                    pageNo=page_no,
                    sourceIndex=source_index,
                )
            )
        identity = _candidate_identity(
            page_no,
            source_index,
            item_type,
            raw_item,
        )
        block_type = _BLOCK_TYPE_MAP.get(item_type, item_type)
        common = {
            "pageNo": page_no,
            "bbox": mapped_bbox,
            "coordinateSystem": (
                "rendered_pixels" if mapped_bbox is not None else None
            ),
            "sourceCoordinateSystem": source_coordinate_system,
            "sourceBbox": raw_item.get("bbox"),
            "sourceEngine": "mineru_vlm",
            "formalEvidenceEligible": mapped_bbox is not None,
        }
        if item_type == "table":
            html = str(
                raw_item.get("table_body")
                or raw_item.get("html")
                or ""
            )
            structure = html_table_to_structure(html)
            for cell in structure.get("cells") or []:
                cell["confidence"] = 0.0
            table = {
                "tableId": f"MINERU-TABLE-{identity}",
                "candidateId": f"MINERU-CAND-{identity}",
                "sourceCandidateIds": [f"MINERU-CAND-{identity}"],
                "html": html,
                "confidence": 0.0,
                "candidateOnly": not bool(structure.get("rows")),
                **common,
                **structure,
            }
            tables.append(table)
            if not structure.get("rows") or not structure.get("columns"):
                diagnostics.append(
                    _diagnostic(
                        "table_structure_unavailable",
                        "MinerU table HTML could not be converted to a grid.",
                        severity="warning",
                        pageNo=page_no,
                        sourceIndex=source_index,
                    )
                )
            layout_blocks.append(
                {
                    "blockId": f"MINERU-BLOCK-{identity}",
                    "blockType": "table",
                    "readingOrder": len(layout_blocks) + 1,
                    **common,
                }
            )
            continue
        if item_type == "image" and str(
            raw_item.get("sub_type") or ""
        ).lower() == "seal":
            seals.append(
                {
                    "sealId": f"MINERU-SEAL-{identity}",
                    "candidateId": f"MINERU-CAND-{identity}",
                    "sourceCandidateIds": [f"MINERU-CAND-{identity}"],
                    "imagePath": raw_item.get("img_path"),
                    "confidence": 0.0,
                    "candidateOnly": True,
                    "canSatisfyRequiredSeal": False,
                    "formalEvidenceEligible": False,
                    **{
                        key: value
                        for key, value in common.items()
                        if key != "formalEvidenceEligible"
                    },
                }
            )
            layout_blocks.append(
                {
                    "blockId": f"MINERU-BLOCK-{identity}",
                    "blockType": "seal",
                    "readingOrder": len(layout_blocks) + 1,
                    **common,
                }
            )
            continue
        text = _content_text(raw_item)
        layout_blocks.append(
            {
                "blockId": f"MINERU-BLOCK-{identity}",
                "blockType": block_type,
                "text": text,
                "readingOrder": len(layout_blocks) + 1,
                **common,
            }
        )
        if not text:
            continue
        reading_order += 1
        candidate_id = f"MINERU-CAND-{identity}"
        fragments.append(
            {
                "candidateId": candidate_id,
                "sourceCandidateIds": [candidate_id],
                "text": text,
                "blockType": block_type,
                "readingOrder": reading_order,
                "confidence": 0.0,
                **common,
            }
        )
    if coordinate_unmapped:
        reasons.append("coordinate_transform_unmapped")
    return {
        "parseResultId": f"PARSE-{uuid4().hex[:12].upper()}",
        "storageKey": storage_key,
        "fileName": file_name,
        "status": "success",
        "outcomeStatus": "completed",
        "parserVersion": "mineru-vlm-adapter@1",
        "profileId": profile_id,
        "documentType": document_type,
        "pages": pages,
        "fragments": fragments,
        "layoutBlocks": layout_blocks,
        "tables": tables,
        "seals": seals,
        "signatures": [],
        "fields": [],
        "quality": {
            "status": "degraded" if coordinate_unmapped else "usable",
            "reasons": reasons,
            "blockingReasons": [],
        },
        "diagnostics": diagnostics,
        "engineRuns": [
            {
                "engine": "mineru_vlm",
                "provider": "mineru",
                "model": "vlm",
                "status": "success",
                "engineAttempted": True,
                "engineExecuted": True,
                "durationMs": 0,
            }
        ],
        "modelManifest": {
            "provider": "mineru",
            "model": "vlm",
            "adapterVersion": "mineru-vlm-adapter@1",
        },
        "metadata": {
            "providerMode": "explicit_remote",
            "provider": "mineru",
            "model": "vlm",
            "providerTaskId": provider_task_id,
            "cloudGrounded": True,
            "coordinateContract": "rendered_pixels_mapped_v2",
        },
        "groundingValidation": {
            "coordinateContract": "rendered_pixels_mapped_v2",
            "unmappedCoordinateCount": sum(
                1
                for item in diagnostics
                if item.get("code") == "coordinate_transform_unmapped"
            ),
            "providerConfidenceAvailable": False,
            "invalidCandidateIdCount": 0,
            "unsupportedAttributionCount": 0,
            "droppedUnsupportedAttributionCount": 0,
        },
        "createdAt": server_time(),
    }


def build_mineru_artifacts(
    zip_bytes: bytes,
    *,
    content_bytes: bytes,
    middle_bytes: bytes,
    markdown_bytes: bytes | None,
    result: Mapping[str, Any],
) -> dict[str, MinerUArtifact]:
    raw: dict[str, tuple[str, bytes, str]] = {
        "original_zip": (
            "mineru-result.zip",
            zip_bytes,
            "application/zip",
        ),
        "content_list": (
            "mineru-content-list.json",
            content_bytes,
            "application/json",
        ),
        "middle_json": (
            "mineru-middle.json",
            middle_bytes,
            "application/json",
        ),
        "normalized_json": (
            "normalized-result.json",
            json.dumps(
                result,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8"),
            "application/json",
        ),
    }
    if markdown_bytes is not None:
        raw["markdown"] = ("mineru-full.md", markdown_bytes, "text/markdown")
    return {
        key: MinerUArtifact(
            name=name,
            data=data,
            content_type=content_type,
            sha256=hashlib.sha256(data).hexdigest(),
        )
        for key, (name, data, content_type) in raw.items()
    }


def _load_json(data: bytes, *, expected_type: type[Any]) -> Any:
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MinerUNormalizationError(
            "MINERU_JSON_INVALID",
            "MinerU result contains invalid JSON.",
        ) from exc
    if not isinstance(value, expected_type):
        raise MinerUNormalizationError(
            "MINERU_JSON_INVALID",
            "MinerU result contains invalid JSON.",
        )
    return value


def _content_text(item: Mapping[str, Any]) -> str:
    for key in ("text", "latex", "content", "code"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    list_items = item.get("list_items")
    if isinstance(list_items, list):
        values = []
        for value in list_items:
            if isinstance(value, Mapping):
                value = value.get("text")
            if str(value or "").strip():
                values.append(str(value).strip())
        return "\n".join(values)
    return ""


def _map_bbox(
    raw_bbox: Any,
    page: Mapping[str, Any] | None,
) -> tuple[list[float] | None, str | None]:
    if (
        page is None
        or not isinstance(raw_bbox, (list, tuple))
        or len(raw_bbox) < 4
    ):
        return None, (
            "mineru_normalized_1000" if raw_bbox is not None else None
        )
    values = [_safe_float(value) for value in raw_bbox[:4]]
    if any(value is None for value in values):
        return None, "mineru_normalized_1000"
    x1, y1, x2, y2 = (float(value) for value in values if value is not None)
    if x1 < 0 or y1 < 0 or x2 < x1 or y2 < y1:
        return None, "mineru_normalized_1000"
    scale = 1.0 if max(x1, y1, x2, y2) <= 1 else 1000.0
    source_coordinate_system = (
        "mineru_normalized_1"
        if scale == 1.0
        else "mineru_normalized_1000"
    )
    width = float(page["width"])
    height = float(page["height"])
    return (
        [
            round(x1 / scale * width, 4),
            round(y1 / scale * height, 4),
            round(x2 / scale * width, 4),
            round(y2 / scale * height, 4),
        ],
        source_coordinate_system,
    )


def _candidate_identity(
    page_no: int,
    source_index: int,
    item_type: str,
    item: Mapping[str, Any],
) -> str:
    payload = {
        "pageNo": page_no,
        "sourceIndex": source_index,
        "type": item_type,
        "text": _content_text(item),
        "bbox": item.get("bbox"),
        "imagePath": item.get("img_path"),
    }
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()[:16].upper()


def _diagnostic(
    code: str,
    message: str,
    *,
    severity: str,
    **details: Any,
) -> dict[str, Any]:
    return {
        "code": code,
        "message": message,
        "severity": severity,
        **details,
    }


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in {float("inf"), float("-inf")}:
        return None
    return number
