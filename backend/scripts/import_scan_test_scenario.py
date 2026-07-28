from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import mimetypes
import shutil
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any
from uuid import uuid4

BACKEND_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = BACKEND_ROOT.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from libs.contracts.responses import server_time
from libs.business_pack import business_pack_snapshot, load_business_pack
from libs.business_pack.clause_store import bind_project_node_clause_packages
from libs.db.repository import flush_state, load_state, repo, stable_doc_id
from libs.knowledge_indexing import (
    OFFLINE_EMBEDDING_MODEL,
    OFFLINE_VECTOR_DIMENSIONS,
    STANDARD_INDEX_VERSION,
    offline_hash_embeddings,
)
from libs.material_review_assets import load_material_review_asset
from libs.material_targeting import run_material_targeting


SCENARIO_TAG = "scan-test-scenario-v1"
SCENARIO_BINDING_VERSION = "scan-binding-v2"
DEFAULT_PROJECT_ID = "P-2026-GDLNG-002"
HEIC_SUFFIXES = {".heic", ".heif"}
CONTRACTOR_USER = {"userId": "USER-CONTRACTOR-001", "org": "粤海安装工程有限公司", "name": "李工"}
NDT_USER = {"userId": "USER-NDT-001", "org": "粤检无损检测", "name": "王工"}
OWNER_USER = {"userId": "USER-OWNER-001", "org": "华东管网建设公司", "name": "赵经理"}
INSPECTION_USER = {"userId": "USER-INSPECTION-001", "org": "省特检院一部", "name": "张工"}
INSPECTION_REVIEWER = "张工"
ROLE_PROFILE_DEFAULTS = {
    "contractor": {
        "username": "contractor",
        "roleId": "3",
        "roleLabel": "施工方",
        "defaultPath": "/workbench/contractor",
    },
    "ndt": {
        "username": "ndt",
        "roleId": "4",
        "roleLabel": "无损检测",
        "defaultPath": "/workbench/ndt",
    },
    "owner": {
        "username": "owner",
        "roleId": "5",
        "roleLabel": "建设方",
        "defaultPath": "/workbench/owner",
    },
    "inspection": {
        "username": "inspection",
        "roleId": "2",
        "roleLabel": "监检人员",
        "defaultPath": "/workbench/inspection",
    },
}


def binding_target(
    node_id: int,
    material_type_code: str,
    *,
    review_point_file_content: str | None = None,
) -> dict[str, Any]:
    target: dict[str, Any] = {
        "nodeId": node_id,
        "materialTypeCode": material_type_code,
    }
    if review_point_file_content:
        target["reviewPointFileContent"] = review_point_file_content
    return target


DESIGN_STAMP_TARGET = binding_target(
    1,
    "design_document",
    review_point_file_content="施工图纸标题栏及设计印章页",
)
DESIGN_SCOPE_TARGET = binding_target(
    1,
    "design_document",
    review_point_file_content="设计说明及管道特性表",
)


FILE_MAPPINGS: dict[str, dict[str, Any]] = {
    "20260623104523.pdf": {
        "role": "contractor",
        "materialCategory": "施工单位许可资质",
        "materialTypeCode": "construction_license",
        "bindingTargets": [binding_target(2, "construction_license")],
    },
    "20260623104555.pdf": {
        "role": "contractor",
        "materialCategory": "制造许可证、安装许可证及焊工资格证",
        "materialTypeCode": "manufacturing_license",
        "bindingTargets": [
            binding_target(2, "construction_license"),
            binding_target(12, "manufacturing_license"),
            binding_target(24, "welder_certificate"),
            binding_target(29, "welder_certificate"),
        ],
    },
    "20260623104703.pdf": {
        "role": "contractor",
        "materialCategory": "管材、管件及焊材质量证明文件",
        "materialTypeCode": "quality_certificate",
        "bindingTargets": [
            binding_target(16, "quality_certificate"),
            binding_target(21, "quality_certificate"),
            binding_target(26, "welding_material_certificate"),
            binding_target(27, "welding_material_certificate"),
        ],
    },
    "20260623104730.pdf": {
        "role": "contractor",
        "materialCategory": "压力管道安装交工资料",
        "materialTypeCode": "installation_record",
        "bindingTargets": [
            binding_target(23, "valve_test_report"),
            binding_target(25, "welding_record"),
            binding_target(29, "welding_record"),
            binding_target(30, "weld_appearance_record"),
            binding_target(44, "anticorrosion_insulation_record"),
            binding_target(47, "grounding_test_record"),
            binding_target(52, "installation_record"),
            binding_target(53, "installation_record"),
            binding_target(55, "installation_record"),
            binding_target(60, "pressure_test_report"),
            binding_target(61, "pressure_test_report"),
            binding_target(62, "pressure_test_report"),
            binding_target(66, "pressure_test_report"),
            binding_target(67, "leakage_test_report"),
            binding_target(68, "purge_cleaning_record"),
        ],
    },
    "20260623104828.pdf": {
        "role": "contractor",
        "materialCategory": "法兰、管件、阀门及防腐材料质量证明文件",
        "materialTypeCode": "quality_certificate",
        "bindingTargets": [
            binding_target(16, "quality_certificate"),
            binding_target(23, "quality_certificate"),
            binding_target(43, "anticorrosion_insulation_material_certificate"),
        ],
    },
    "20260623105454.pdf": {
        "role": "contractor",
        "materialCategory": "施工组织设计",
        "materialTypeCode": "construction_organization_design",
        "bindingTargets": [
            binding_target(11, "construction_organization_design"),
            binding_target(36, "ndt_plan"),
            binding_target(39, "ndt_plan"),
            binding_target(59, "pressure_test_plan"),
            binding_target(61, "pressure_test_plan"),
            binding_target(62, "pressure_test_plan"),
            binding_target(68, "purge_cleaning_record"),
        ],
    },
    "20260623105534.pdf": {
        "role": "contractor",
        "materialCategory": "焊接工艺评定报告和焊接作业指导书",
        "materialTypeCode": "wps_pqr",
        "bindingTargets": [
            binding_target(16, "quality_certificate"),
            binding_target(25, "wps_pqr"),
            binding_target(29, "wps_pqr"),
        ],
    },
    "20260623105636.pdf": {
        "role": "ndt",
        "materialCategory": "无损检测报告",
        "materialTypeCode": "ndt_report",
        "bindingTargets": [
            binding_target(40, "ndt_report"),
            binding_target(31, "ndt_report"),
            binding_target(37, "ndt_report"),
            binding_target(41, "ndt_report"),
            binding_target(42, "ndt_report"),
            binding_target(65, "ndt_report"),
        ],
    },
    "IMG_6508.heic": {
        "role": "contractor",
        "materialCategory": "管道安装材料表",
        "materialTypeCode": "design_document",
        "bindingTargets": [DESIGN_STAMP_TARGET, binding_target(53, "design_document")],
    },
    "IMG_6509.heic": {
        "role": "contractor",
        "materialCategory": "管道特性表",
        "materialTypeCode": "design_document",
        "bindingTargets": [DESIGN_STAMP_TARGET, DESIGN_SCOPE_TARGET, binding_target(9, "design_document")],
    },
    "IMG_6510.heic": {
        "role": "contractor",
        "materialCategory": "管道及仪表流程图",
        "materialTypeCode": "design_document",
        "bindingTargets": [DESIGN_STAMP_TARGET, binding_target(9, "design_document")],
    },
    "IMG_6511.heic": {
        "role": "contractor",
        "materialCategory": "压力管道强度计算书",
        "materialTypeCode": "calculation_report",
        "bindingTargets": [DESIGN_STAMP_TARGET, binding_target(6, "calculation_report")],
    },
    "IMG_6512.heic": {
        "role": "contractor",
        "materialCategory": "工艺设计说明书",
        "materialTypeCode": "design_document",
        "bindingTargets": [binding_target(8, "design_document"), binding_target(9, "design_document")],
    },
    "IMG_6513.heic": {
        "role": "contractor",
        "materialCategory": "设备一览表",
        "materialTypeCode": "design_document",
        "bindingTargets": [binding_target(4, "design_document")],
    },
    "IMG_6514.heic": {
        "role": "contractor",
        "materialCategory": "工艺图纸目录",
        "materialTypeCode": "design_document",
        "bindingTargets": [DESIGN_STAMP_TARGET, binding_target(4, "design_document")],
    },
    "IMG_6515.heic": {
        "role": "contractor",
        "materialCategory": "工艺设计说明书",
        "materialTypeCode": "design_document",
        "bindingTargets": [DESIGN_SCOPE_TARGET, binding_target(4, "design_document")],
    },
    "IMG_6516.heic": {
        "role": "contractor",
        "materialCategory": "设计说明书",
        "materialTypeCode": "design_document",
        "bindingTargets": [binding_target(8, "design_document")],
    },
    "IMG_6517.heic": {
        "role": "contractor",
        "materialCategory": "工艺设计说明书",
        "materialTypeCode": "design_document",
        "bindingTargets": [binding_target(8, "design_document")],
    },
    "IMG_6518.heic": {
        "role": "contractor",
        "materialCategory": "工艺设计说明书",
        "materialTypeCode": "design_document",
        "bindingTargets": [
            binding_target(8, "design_document"),
            binding_target(47, "design_document"),
            binding_target(53, "design_document"),
        ],
    },
    "IMG_6519.heic": {
        "role": "contractor",
        "materialCategory": "工艺设计说明书",
        "materialTypeCode": "design_document",
        "bindingTargets": [
            binding_target(8, "design_document"),
            binding_target(9, "design_document"),
            binding_target(43, "design_document"),
            binding_target(59, "design_document"),
            binding_target(68, "design_document"),
        ],
    },
    "IMG_6520.heic": {
        "role": "contractor",
        "materialCategory": "综合材料表",
        "materialTypeCode": "design_document",
        "bindingTargets": [binding_target(53, "design_document")],
    },
    "IMG_6521.heic": {
        "role": "contractor",
        "materialCategory": "综合材料表",
        "materialTypeCode": "design_document",
        "bindingTargets": [binding_target(53, "design_document")],
    },
    "IMG_6522.heic": {
        "role": "contractor",
        "materialCategory": "综合材料表",
        "materialTypeCode": "design_document",
        "bindingTargets": [binding_target(43, "design_document"), binding_target(53, "design_document")],
    },
    "IMG_6523.heic": {
        "role": "contractor",
        "materialCategory": "综合材料表",
        "materialTypeCode": "design_document",
        "bindingTargets": [binding_target(47, "design_document"), binding_target(53, "design_document")],
    },
    "IMG_6524.heic": {
        "role": "contractor",
        "materialCategory": "配管平面图",
        "materialTypeCode": "design_document",
        "bindingTargets": [
            DESIGN_STAMP_TARGET,
            binding_target(4, "design_document"),
            binding_target(53, "design_document"),
        ],
    },
    "IMG_6526.heic": {
        "role": "contractor",
        "materialCategory": "设计图纸",
        "materialTypeCode": "design_document",
        "bindingTargets": [
            DESIGN_STAMP_TARGET,
            binding_target(4, "design_document"),
            binding_target(53, "design_document"),
        ],
    },
    "IMG_6527.heic": {
        "role": "contractor",
        "materialCategory": "设计图纸",
        "materialTypeCode": "design_document",
        "bindingTargets": [
            DESIGN_STAMP_TARGET,
            binding_target(4, "design_document"),
            binding_target(53, "design_document"),
        ],
    },
    "IMG_6528.heic": {
        "role": "contractor",
        "materialCategory": "设计图纸",
        "materialTypeCode": "design_document",
        "bindingTargets": [
            DESIGN_STAMP_TARGET,
            binding_target(4, "design_document"),
            binding_target(53, "design_document"),
        ],
    },
    "IMG_6529.heic": {
        "role": "contractor",
        "materialCategory": "设备及管道油漆保温一览表",
        "materialTypeCode": "design_document",
        "bindingTargets": [binding_target(43, "design_document")],
    },
    "IMG_6530.heic": {
        "role": "contractor",
        "materialCategory": "管道特性表",
        "materialTypeCode": "design_document",
        "bindingTargets": [DESIGN_SCOPE_TARGET, binding_target(9, "design_document")],
    },
}


def sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def content_type_for(path: Path) -> str:
    if path.suffix.lower() in HEIC_SUFFIXES:
        return "image/heic"
    return mimetypes.guess_type(path.name)[0] or "application/octet-stream"


def load_ocr_items(path: Path) -> dict[str, dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {str(item.get("source_file") or ""): item for item in payload if item.get("source_file")}


def scan_files(scan_dir: Path) -> list[Path]:
    allowed = {".pdf", *HEIC_SUFFIXES}
    return sorted(
        [item for item in scan_dir.iterdir() if item.is_file() and item.suffix.lower() in allowed],
        key=lambda item: item.name,
    )


def resolve_import_source_path(scan_dir: Path, source_path: Path) -> Path:
    if source_path.suffix.lower() not in HEIC_SUFFIXES:
        return source_path
    png_path = scan_dir / "png" / f"{source_path.stem}.png"
    if not png_path.is_file():
        raise FileNotFoundError(f"HEIC source requires a converted PNG: {png_path}")
    return png_path


def vision_bbox_to_xyxy(raw_bbox: Any, width: float, height: float) -> list[float] | None:
    if not isinstance(raw_bbox, (list, tuple)) or len(raw_bbox) < 4 or width <= 0 or height <= 0:
        return None
    try:
        x, y, box_width, box_height = (float(value) for value in raw_bbox[:4])
    except (TypeError, ValueError):
        return None
    values = (x, y, box_width, box_height, width, height)
    if not all(math.isfinite(value) for value in values) or box_width <= 0 or box_height <= 0:
        return None
    left = x * width
    top = (1 - y - box_height) * height
    right = (x + box_width) * width
    bottom = (1 - y) * height
    left = max(0.0, min(width, left))
    top = max(0.0, min(height, top))
    right = max(0.0, min(width, right))
    bottom = max(0.0, min(height, bottom))
    if right <= left or bottom <= top:
        return None
    return [round(left, 4), round(top, 4), round(right, 4), round(bottom, 4)]


def normalize_ocr_payload(raw: dict[str, Any], source_path: Path) -> dict[str, Any]:
    normalized = copy.deepcopy(raw)
    pdf_page_dimensions: list[tuple[float, float]] = []
    image_dimensions: tuple[float, float] | None = None
    if source_path.suffix.lower() == ".pdf":
        import fitz

        with fitz.open(source_path) as document:
            pdf_page_dimensions = [(float(page.rect.width), float(page.rect.height)) for page in document]
    else:
        from PIL import Image

        with Image.open(source_path) as image:
            image_dimensions = (float(image.width), float(image.height))

    for page_index, page in enumerate(normalized.get("pages") or [], start=1):
        if not isinstance(page, dict):
            continue
        page_no = int(page.get("source_page") or page.get("pageNo") or page_index)
        if pdf_page_dimensions and 1 <= page_no <= len(pdf_page_dimensions):
            width, height = pdf_page_dimensions[page_no - 1]
            coordinate_system = "pdf_points"
            page.update({"width": width, "height": height})
        elif image_dimensions:
            width, height = image_dimensions
            coordinate_system = "rendered_pixels"
            page.update(
                {
                    "path": str(source_path),
                    "sourceImageWidth": width,
                    "sourceImageHeight": height,
                    "previewWidth": width,
                    "previewHeight": height,
                }
            )
        else:
            continue
        page["coordinateSystem"] = coordinate_system
        page["ocrCoordinateSystem"] = coordinate_system
        for observation in page.get("observations") or []:
            if not isinstance(observation, dict):
                continue
            raw_bbox = observation.get("boundingBox")
            bbox = vision_bbox_to_xyxy(raw_bbox, width, height)
            if not bbox:
                continue
            observation["originalBoundingBox"] = raw_bbox
            observation["bbox"] = bbox
            observation["coordinateSystem"] = coordinate_system
            observation["sourceImageWidth"] = width
            observation["sourceImageHeight"] = height
    return normalized


def mapping_binding_targets(mapping: dict[str, Any]) -> list[dict[str, Any]]:
    targets = [copy.deepcopy(item) for item in mapping.get("bindingTargets") or [] if isinstance(item, dict)]
    if targets:
        return targets
    if mapping.get("nodeId"):
        return [
            {
                "nodeId": int(mapping["nodeId"]),
                "requirementId": mapping.get("requirementId"),
                "materialTypeCode": mapping.get("materialTypeCode"),
            }
        ]
    return []


def configured_material_review_points() -> list[dict[str, Any]]:
    admin_config = repo.state.get("admin_config") or {}
    return [item for item in admin_config.get("materialReviewPoints") or [] if isinstance(item, dict)]


def sync_material_review_points_from_asset() -> dict[str, Any]:
    asset = load_material_review_asset()
    items = [copy.deepcopy(item) for item in asset.get("items") or [] if isinstance(item, dict)]
    if not items:
        raise RuntimeError("The packaged material review point asset is empty.")
    admin_config = repo.state.setdefault("admin_config", {})
    previous = [item for item in admin_config.get("materialReviewPoints") or [] if isinstance(item, dict)]
    previous_ids = {str(item.get("id") or "") for item in previous}
    current_ids = {str(item.get("id") or "") for item in items}
    changed = previous_ids != current_ids or len(previous) != len(items)
    if changed:
        admin_config["materialReviewPoints"] = items
    admin_config["materialReviewPointsAsset"] = {
        key: asset.get(key)
        for key in ("schemaVersion", "version", "source", "sourceSha256", "itemCount")
    }
    return {
        "changed": changed,
        "previousCount": len(previous),
        "currentCount": len(items),
        "version": asset.get("version"),
    }


def resolve_binding_target(
    target: dict[str, Any],
    review_points: list[dict[str, Any]],
) -> dict[str, Any] | None:
    node_id = int(target.get("nodeId") or 0)
    requirement_id = str(target.get("reviewPointId") or target.get("requirementId") or "").strip()
    material_type_code = str(target.get("materialTypeCode") or "").strip()
    file_content = str(target.get("reviewPointFileContent") or "").strip()
    candidates = [item for item in review_points if int(item.get("nodeId") or 0) == node_id]
    if requirement_id:
        candidates = [item for item in candidates if str(item.get("id") or "") == requirement_id]
    if material_type_code:
        candidates = [item for item in candidates if str(item.get("materialTypeCode") or "") == material_type_code]
    if file_content:
        candidates = [item for item in candidates if str(item.get("fileContent") or "") == file_content]
    return candidates[0] if len(candidates) == 1 else None


def requirement(project_id: str, target: dict[str, Any]) -> dict[str, Any] | None:
    review_point = resolve_binding_target(target, configured_material_review_points())
    if review_point:
        return review_point
    requirement_id = str(target.get("requirementId") or "").strip()
    node_id = int(target.get("nodeId") or 0)
    if requirement_id:
        item = next(
            (
                req
                for req in repo.state.get("requirements", [])
                if req.get("projectId") == project_id and req.get("id") == requirement_id
            ),
            None,
        )
        if item:
            return item
    candidates = [
        req
        for req in repo.state.get("requirements", [])
        if req.get("projectId") == project_id and int(req.get("nodeId") or 0) == node_id
    ]
    return candidates[0] if len(candidates) == 1 else None


def requirement_name(requirement_item: dict[str, Any]) -> str:
    return str(
        requirement_item.get("reviewContent")
        or requirement_item.get("name")
        or requirement_item.get("materialTypeName")
        or requirement_item.get("fileContent")
        or "业务资料审查点"
    )


def find_document(
    project_id: str,
    file_name: str,
    hash_value: str,
    size: int,
    *,
    legacy_file_names: set[str] | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    hash_key = f"sha256-{hash_value}"
    for version in repo.state.get("versions", []):
        if version.get("hash") != hash_key:
            continue
        document = repo.find_one("documents", str(version.get("documentId") or ""))
        if document and document.get("projectId") == project_id:
            return document, version
    accepted_file_names = {file_name, *(legacy_file_names or set())}
    for document in repo.state.get("documents", []):
        if document.get("projectId") != project_id or document.get("fileName") not in accepted_file_names:
            continue
        version = repo.find_one("versions", str(document.get("currentVersionId") or ""))
        if version and (
            document.get("fileName") in (legacy_file_names or set())
            or int(version.get("fileSize") or 0) == size
        ):
            return document, version
    return None, None


def remove_records_by_ids(collection: str, ids: set[str], id_field: str = "id") -> int:
    before = len(repo.state.get(collection, []))
    repo.state[collection] = [item for item in repo.state.get(collection, []) if str(item.get(id_field) or "") not in ids]
    return before - len(repo.state.get(collection, []))


def clear_prior_scan_flow(project_id: str, scan_file_names: set[str]) -> dict[str, int]:
    stats: dict[str, int] = defaultdict(int)
    scan_doc_ids = {
        str(doc.get("id"))
        for doc in repo.state.get("documents", [])
        if doc.get("projectId") == project_id
        and (doc.get("fileName") in scan_file_names or doc.get("scenarioTag") == SCENARIO_TAG)
    }
    scan_version_ids = {
        str(version.get("id"))
        for version in repo.state.get("versions", [])
        if version.get("documentId") in scan_doc_ids or version.get("scenarioTag") == SCENARIO_TAG
    }
    scan_file_ids = {
        str(file.get("id"))
        for file in repo.state.get("knowledge_files", [])
        if file.get("documentId") in scan_doc_ids or file.get("scenarioTag") == SCENARIO_TAG
    }

    binding_ids = {
        str(binding.get("id"))
        for binding in repo.state.get("bindings", [])
        if binding.get("projectId") == project_id
        and (binding.get("documentId") in scan_doc_ids or binding.get("scenarioTag") == SCENARIO_TAG)
    }
    stats["bindingsRemoved"] += remove_records_by_ids("bindings", binding_ids)

    report_ids = {
        str(report.get("id"))
        for report in repo.state.get("ndt_reports", [])
        if report.get("projectId") == project_id
        and (report.get("fileId") in scan_doc_ids or report.get("scenarioTag") == SCENARIO_TAG)
    }
    stats["ndtReportsRemoved"] += remove_records_by_ids("ndt_reports", report_ids)
    repo.state["ndt_records"] = [
        item
        for item in repo.state.get("ndt_records", [])
        if item.get("reportId") not in report_ids and item.get("scenarioTag") != SCENARIO_TAG
    ]
    repo.state["ndt_films"] = [item for item in repo.state.get("ndt_films", []) if item.get("scenarioTag") != SCENARIO_TAG]

    submission_ids = {
        str(submission.get("submissionId"))
        for submission in repo.state.get("submissions", [])
        if submission.get("projectId") == project_id
        and (
            submission.get("scenarioTag") == SCENARIO_TAG
            or bool(set(submission.get("bindingIds") or []) & binding_ids)
            or bool(set(submission.get("reportIds") or []) & report_ids)
        )
    }
    before = len(repo.state.get("submissions", []))
    repo.state["submissions"] = [
        item for item in repo.state.get("submissions", []) if str(item.get("submissionId") or "") not in submission_ids
    ]
    stats["submissionsRemoved"] += before - len(repo.state.get("submissions", []))

    todo_ids = {
        str(todo.get("id"))
        for todo in repo.state.get("todos", [])
        if todo.get("projectId") == project_id
        and (
            todo.get("scenarioTag") == SCENARIO_TAG
            or str(todo.get("targetId") or "") in submission_ids
            or str(todo.get("targetId") or "") in report_ids
        )
    }
    stats["todosRemoved"] += remove_records_by_ids("todos", todo_ids)

    stats["ocrJobsRemoved"] += remove_records_by_ids(
        "ocr_jobs",
        {
            str(job.get("id"))
            for job in repo.state.get("ocr_jobs", [])
            if job.get("documentVersionId") in scan_version_ids or job.get("scenarioTag") == SCENARIO_TAG
        },
    )
    stats["ocrParseResultsRemoved"] += remove_records_by_ids(
        "ocr_parse_results",
        {
            str(result.get("id") or result.get("parseResultId"))
            for result in repo.state.get("ocr_parse_results", [])
            if result.get("documentVersionId") in scan_version_ids or result.get("scenarioTag") == SCENARIO_TAG
        },
    )
    repo.state["extracted_fields"] = [
        item
        for item in repo.state.get("extracted_fields", [])
        if item.get("documentVersionId") not in scan_version_ids and item.get("scenarioTag") != SCENARIO_TAG
    ]
    repo.state["evidence_links"] = [
        item
        for item in repo.state.get("evidence_links", [])
        if item.get("documentVersionId") not in scan_version_ids and item.get("scenarioTag") != SCENARIO_TAG
    ]
    repo.state["node_evidence_links"] = [
        item
        for item in repo.state.get("node_evidence_links", [])
        if not (
            item.get("projectId") == project_id
            and (
                item.get("documentId") in scan_doc_ids
                or item.get("documentVersionId") in scan_version_ids
                or item.get("scenarioTag") == SCENARIO_TAG
            )
        )
    ]
    repo.state["material_targeting_runs"] = [
        item
        for item in repo.state.get("material_targeting_runs", [])
        if not (
            item.get("projectId") == project_id
            and (
                item.get("documentId") in scan_doc_ids
                or item.get("documentVersionId") in scan_version_ids
                or item.get("scenarioTag") == SCENARIO_TAG
            )
        )
    ]
    repo.state["knowledge_chunks"] = [
        item for item in repo.state.get("knowledge_chunks", []) if item.get("fileId") not in scan_file_ids
    ]
    repo.state["knowledge_vectors"] = [
        item for item in repo.state.get("knowledge_vectors", []) if item.get("fileId") not in scan_file_ids
    ]
    repo.state["knowledge_tasks"] = [
        item
        for item in repo.state.get("knowledge_tasks", [])
        if item.get("targetId") not in scan_file_ids and item.get("documentVersionId") not in scan_version_ids
    ]
    repo.state["ai_runs"] = [
        item
        for item in repo.state.get("ai_runs", [])
        if not (item.get("projectId") == project_id and item.get("scenarioTag") == SCENARIO_TAG)
    ]
    repo.state["review_findings"] = [
        item
        for item in repo.state.get("review_findings", [])
        if not (item.get("projectId") == project_id and item.get("scenarioTag") == SCENARIO_TAG)
    ]
    return dict(stats)


def scenario_node_ids() -> set[int]:
    return {
        int(target["nodeId"])
        for mapping in FILE_MAPPINGS.values()
        for target in mapping_binding_targets(mapping)
        if target.get("nodeId")
    }


def ensure_document_records(
    project_id: str,
    source_path: Path,
    mapping: dict[str, Any],
    upload_session_id: str,
    *,
    original_file_name: str | None = None,
) -> dict[str, Any]:
    data = source_path.read_bytes()
    hash_value = hashlib.sha256(data).hexdigest()
    size = len(data)
    file_name = source_path.name
    legacy_file_names = {original_file_name} if original_file_name and original_file_name != file_name else set()
    document, version = find_document(
        project_id,
        file_name,
        hash_value,
        size,
        legacy_file_names=legacy_file_names,
    )
    seed = f"SCAN{hash_value[:8].upper()}"
    created = False
    project = repo.require_project(project_id) or {}
    role = mapping["role"]
    actor = NDT_USER if role == "ndt" else CONTRACTOR_USER
    if not document or not version:
        document, version, knowledge_file, knowledge_task = repo._build_document_records(  # type: ignore[attr-defined]
            project_id,
            file_name,
            content_type_for(source_path),
            source_org_name=actor["org"],
            uploader_name=actor["name"],
            material_category=mapping.get("materialCategory"),
            seed=seed,
        )
        repo._insert_document_records(document, version, knowledge_file, knowledge_task)  # type: ignore[attr-defined]
        created = True
    else:
        knowledge_file = repo.find_one("knowledge_files", f"KF-{document['id']}") or next(
            (
                item
                for item in repo.state.get("knowledge_files", [])
                if item.get("documentVersionId") == version.get("id")
            ),
            None,
        )
        if not knowledge_file:
            knowledge_file = {
                "id": f"KF-{document['id']}",
                "fileName": file_name,
                "sourceId": "KS-PROJECT-FILE",
                "sourceName": "项目文件知识库",
                "projectId": project_id,
                "projectName": project.get("name") or "",
                "documentId": document["id"],
                "documentVersionId": version["id"],
                "chunkCount": 0,
                "vectorCount": 0,
                "actions": ["knowledge:view", "knowledge:reindex"],
            }
            repo.state["knowledge_files"].insert(0, knowledge_file)

    target_dir = WORKSPACE_ROOT / "output" / "document_uploads" / project_id / upload_session_id / version["id"]
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / file_name
    if not target_path.exists() or hashlib.sha256(target_path.read_bytes()).hexdigest() != hash_value:
        shutil.copy2(source_path, target_path)
    storage_key = f"local://{target_path.relative_to(WORKSPACE_ROOT)}"
    now = server_time()
    document.update(
        {
            "projectId": project_id,
            "businessPackId": project.get("businessPackId"),
            "materialTypeCode": mapping.get("materialTypeCode") or "generic_review_material",
            "materialCategory": mapping.get("materialCategory"),
            "fileName": file_name,
            "fileType": content_type_for(source_path),
            "originalFileName": original_file_name or file_name,
            "sourceOrgName": actor["org"],
            "uploaderName": actor["name"],
            "currentVersionId": version["id"],
            "fileStatus": "已上传",
            "currentOcrStatus": "排队中",
            "updatedAt": now,
            "scenarioTag": SCENARIO_TAG,
            "sourceRelativePath": str(source_path.relative_to(WORKSPACE_ROOT)),
            "actions": ["file:view", "file:bind", "file:preview", "file:download"],
        }
    )
    primary_target = (mapping_binding_targets(mapping) or [{}])[0]
    if role == "ndt" and primary_target.get("nodeId"):
        document["nodeId"] = int(primary_target["nodeId"])
    version.update(
        {
            "documentId": document["id"],
            "versionNo": version.get("versionNo") or "V1",
            "hash": f"sha256-{hash_value}",
            "fileSize": size,
            "storageKey": storage_key,
            "storageBucket": "local",
            "ocrStatus": "排队中",
            "sliceStatus": "未切片",
            "vectorStatus": "未向量化",
            "uploaderName": actor["name"],
            "uploadTime": now,
            "isCurrent": True,
            "scenarioTag": SCENARIO_TAG,
            "originalFileName": original_file_name or file_name,
        }
    )
    knowledge_file = repo.find_one("knowledge_files", f"KF-{document['id']}") or next(
        item for item in repo.state["knowledge_files"] if item.get("documentVersionId") == version["id"]
    )
    knowledge_file.update(
        {
            "fileName": file_name,
            "originalFileName": original_file_name or file_name,
            "sourceId": "KS-PROJECT-FILE",
            "sourceName": "项目文件知识库",
            "projectId": project_id,
            "projectName": project.get("name") or "",
            "documentId": document["id"],
            "documentVersionId": version["id"],
            "materialCategory": mapping.get("materialCategory"),
            "ocrStatus": "排队中",
            "sliceStatus": "未切片",
            "vectorStatus": "待向量化",
            "updatedAt": now,
            "scenarioTag": SCENARIO_TAG,
            "sourceRelativePath": str(source_path.relative_to(WORKSPACE_ROOT)),
            "actions": ["knowledge:view", "knowledge:reindex"],
        }
    )
    if role == "ndt" and primary_target.get("nodeId"):
        knowledge_file["nodeId"] = int(primary_target["nodeId"])
    repo.upsert_knowledge_task(
        task_type="ocr",
        target_id=knowledge_file["id"],
        target_name=file_name,
        document_id=document["id"],
        version_id=version["id"],
        status="排队中",
        progress=0,
    )["scenarioTag"] = SCENARIO_TAG
    return {
        "created": created,
        "document": document,
        "version": version,
        "knowledgeFile": knowledge_file,
        "targetPath": target_path,
        "storageKey": storage_key,
    }


def observations_for_page(page: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in page.get("observations") or [] if isinstance(item, dict) and str(item.get("text") or "").strip()]


def fragments_from_ocr(raw: dict[str, Any]) -> list[dict[str, Any]]:
    fragments: list[dict[str, Any]] = []
    for page_index, page in enumerate(raw.get("pages") or [], start=1):
        page_no = int(page.get("source_page") or page.get("pageNo") or page_index)
        observations = observations_for_page(page)
        if observations:
            for observation in observations:
                fragments.append(
                    {
                        "id": f"FRAG-SCAN-{page_no}-{len(fragments) + 1}",
                        "pageNo": page_no,
                        "text": str(observation.get("text") or "").strip(),
                        "bbox": observation.get("bbox") or observation.get("boundingBox"),
                        "confidence": observation.get("confidence"),
                        "sourceMethod": observation.get("extraction_method") or "scan_ocr_import",
                        "ocrEngine": "macos_vision_ocr_v1",
                        "coordinateSystem": observation.get("coordinateSystem") or page.get("coordinateSystem"),
                        "sourceImageWidth": observation.get("sourceImageWidth") or page.get("sourceImageWidth") or page.get("width"),
                        "sourceImageHeight": observation.get("sourceImageHeight") or page.get("sourceImageHeight") or page.get("height"),
                    }
                )
            continue
        text = str(page.get("text") or "").strip()
        if text:
            fragments.append(
                {
                    "id": f"FRAG-SCAN-{page_no}-{len(fragments) + 1}",
                    "pageNo": page_no,
                    "text": text,
                    "confidence": raw.get("avg_confidence"),
                    "sourceMethod": "scan_ocr_import",
                    "ocrEngine": "macos_vision_ocr_v1",
                }
            )
    return fragments


def all_ocr_text(raw: dict[str, Any]) -> str:
    return "\n".join(str(page.get("text") or "").strip() for page in raw.get("pages") or [] if str(page.get("text") or "").strip())


def regex_field_value(text: str, patterns: list[str]) -> str | None:
    import re

    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            values = [group for group in match.groups() if group is not None]
            return " 至 ".join(item.strip() for item in values if item.strip()) if len(values) > 1 else match.group(1).strip()
    return None


def extract_regex_field(
    text: str,
    label: str,
    patterns: list[str],
    *,
    fragments: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    for fragment in fragments or []:
        fragment_text = str(fragment.get("text") or "")
        value = regex_field_value(fragment_text, patterns)
        if value is None:
            continue
        bbox = fragment.get("bbox")
        return {
            "fieldName": label,
            "fieldValue": value,
            "pageNo": int(fragment.get("pageNo") or 1),
            "bbox": bbox,
            "confidence": float(fragment.get("confidence") or 0.8),
            "sourceFragmentId": fragment.get("id"),
            "formalEvidenceEligible": bool(
                isinstance(bbox, (list, tuple))
                and len(bbox) >= 4
                and float(bbox[2]) > float(bbox[0])
                and float(bbox[3]) > float(bbox[1])
            ),
        }
    value = regex_field_value(text, patterns)
    if value is None:
        return None
    return {
        "fieldName": label,
        "fieldValue": value,
        "pageNo": 1,
        "bbox": None,
        "confidence": 0.8,
        "sourceFragmentId": None,
        "formalEvidenceEligible": False,
    }


def fields_from_ocr(
    raw: dict[str, Any],
    mapping: dict[str, Any],
    fragments: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    text = all_ocr_text(raw)
    fragments = fragments if fragments is not None else fragments_from_ocr(raw)
    fields: list[dict[str, Any]] = [
        {
            "fieldName": "资料类型",
            "fieldValue": mapping.get("materialCategory") or raw.get("knowledge_type") or raw.get("category") or "未分类",
            "pageNo": 1,
            "confidence": 0.9,
            "extractionMethod": "scan_ocr_import",
        },
        {
            "fieldName": "OCR分类依据",
            "fieldValue": str(raw.get("evidence") or raw.get("knowledge_type") or "")[:200],
            "pageNo": 1,
            "confidence": float(raw.get("avg_confidence") or 0.8),
            "extractionMethod": "scan_ocr_import",
        },
        {
            "fieldName": "页数",
            "fieldValue": str(raw.get("page_count") or len(raw.get("pages") or []) or 1),
            "pageNo": 1,
            "confidence": 1,
            "extractionMethod": "scan_ocr_import",
        },
    ]
    for field in [
        extract_regex_field(text, "项目名称", [r"项目名称[:：]\s*([^\n]{4,80})", r"工程名称[:：]\s*([^\n]{4,80})"], fragments=fragments),
        extract_regex_field(text, "证书编号", [r"证书编号[:：]\s*([A-Z0-9\-]+)", r"编号[:：]\s*([A-Z]{1,4}[0-9][A-Z0-9\-]+)"], fragments=fragments),
        extract_regex_field(text, "报告编号", [r"报告编号[:：]\s*([A-Z0-9\-]+)"], fragments=fragments),
        extract_regex_field(text, "图号", [r"图号[:：]?\s*([A-ZQX0-9\-—_]{6,40})"], fragments=fragments),
        extract_regex_field(text, "有效期至", [r"有效期至[:：]?\s*([0-9]{4}年[0-9]{1,2}月[0-9]{1,2}日)"], fragments=fragments),
        extract_regex_field(text, "机构名称", [r"(?:单位名称|施工单位|安装单位)[:：]\s*([^\n]{4,80})"], fragments=fragments),
        extract_regex_field(text, "许可范围", [r"((?:工业管道|压力管道)[^\n]{0,80}(?:GC1|GC2|GCD)[^\n]{0,40})"], fragments=fragments),
        extract_regex_field(text, "管道级别", [r"(?:压力管道级别|管道级别)[:：为\s]*([A-Z0-9、,，/ ]{2,40})"], fragments=fragments),
        extract_regex_field(text, "施工计划工期", [r"工期目标[:：]\s*([0-9]{4}年[0-9]{1,2}月[0-9]{1,2}日)[^\n]{0,20}(?:进场|开工)[^\n]{0,20}([0-9]{4}年[0-9]{1,2}月[0-9]{1,2}日)[^\n]{0,20}(?:竣工|完工|验收)"], fragments=fragments),
        extract_regex_field(text, "安装工期", [r"安装开工日期[:：]?\s*([0-9]{4}年[0-9]{1,2}月[0-9]{1,2}日)[\s\S]{0,80}安装竣工日期[:：]?\s*([0-9]{4}年[0-9]{1,2}月[0-9]{1,2}日)"], fragments=fragments),
    ]:
        if field:
            field["extractionMethod"] = "scan_ocr_import"
            fields.append(field)
    return fields


def apply_ocr_and_index(document: dict[str, Any], version: dict[str, Any], raw: dict[str, Any], mapping: dict[str, Any], *, with_vectors: bool) -> dict[str, Any]:
    fragments = fragments_from_ocr(raw)
    result = {
        "parseResultId": f"PARSE-SCAN-{stable_doc_id(version['id'])[:12].upper()}",
        "storageKey": version.get("storageKey"),
        "fileName": document.get("fileName"),
        "status": "success",
        "profileId": "scan_import_v1",
        "documentType": raw.get("category") or mapping.get("materialTypeCode"),
        "parserVersion": "scan_ocr_classifier_v1",
        "engineVersion": "macos_vision_ocr_v1",
        "modelManifest": {"source": "output/ocr/raw_ocr_pages.json", "scenarioTag": SCENARIO_TAG},
        "engineRuns": [
            {
                "engine": "scan_ocr_import",
                "status": "success",
                "avgConfidence": raw.get("avg_confidence"),
                "pageCount": raw.get("page_count"),
            }
        ],
        "diagnostics": [],
        "pages": raw.get("pages") or [],
        "fragments": fragments,
        "fields": fields_from_ocr(raw, mapping, fragments),
        "quality": {
            "avgConfidence": raw.get("avg_confidence"),
            "lineCount": raw.get("line_count"),
            "charCount": raw.get("char_count"),
            "classification": raw.get("category"),
            "knowledgeType": raw.get("knowledge_type"),
        },
        "scenarioTag": SCENARIO_TAG,
    }
    job = repo.create_ocr_job_record(
        document_id=document["id"],
        version_id=version["id"],
        storage_key=version["storageKey"],
        file_name=document["fileName"],
        profile_id="scan_import_v1",
        document_type=str(result.get("documentType") or ""),
    )
    job["scenarioTag"] = SCENARIO_TAG
    parse_result = repo.finish_ocr_job_record(job, result)
    if parse_result:
        parse_result["scenarioTag"] = SCENARIO_TAG
    applied = repo.apply_ocr_result(document["id"], version["id"], result)
    targeting_result = run_material_targeting(
        repo,
        str(document["projectId"]),
        document["id"],
        version["id"],
        triggered_by="scan_import",
    )
    for run in repo.state.get("material_targeting_runs", []):
        if run.get("id") == targeting_result.get("id"):
            run["scenarioTag"] = SCENARIO_TAG
            break
    for link in targeting_result.get("createdLinks") or []:
        link["scenarioTag"] = SCENARIO_TAG
    for binding in targeting_result.get("createdBindings") or []:
        binding["scenarioTag"] = SCENARIO_TAG
    knowledge_file = repo.knowledge_file_for_version(version["id"])
    slice_result = {"status": "skipped", "chunkCount": 0}
    vector_result = {"status": "skipped", "vectorCount": 0}
    if knowledge_file:
        for task in repo.state.get("knowledge_tasks", []):
            if task.get("targetId") == knowledge_file["id"]:
                task["scenarioTag"] = SCENARIO_TAG
        slice_result = repo.apply_slice_result(knowledge_file["id"], fragments)
        if with_vectors and slice_result.get("status") == "success":
            chunks = sorted(
                [item for item in repo.state.get("knowledge_chunks", []) if item.get("fileId") == knowledge_file["id"]],
                key=lambda item: int(item.get("chunkNo") or 0),
            )
            vectors = offline_hash_embeddings([str(item.get("text") or "") for item in chunks])
            vector_result = repo.apply_embed_result(
                knowledge_file["id"],
                vector_count=len(chunks),
                vectors=vectors,
                embedding_model=OFFLINE_EMBEDDING_MODEL,
                index_version=STANDARD_INDEX_VERSION,
                expected_dimensions=OFFLINE_VECTOR_DIMENSIONS,
                vector_status_reason="scan_test_import",
            )
        version["sliceStatus"] = knowledge_file.get("sliceStatus") or version.get("sliceStatus")
        version["vectorStatus"] = knowledge_file.get("vectorStatus") or version.get("vectorStatus")
        version["chunkCount"] = knowledge_file.get("chunkCount", 0)
        version["vectorCount"] = knowledge_file.get("vectorCount", 0)
        if knowledge_file.get("embeddingModel"):
            version["embeddingModel"] = knowledge_file.get("embeddingModel")
        if knowledge_file.get("indexVersion"):
            version["indexVersion"] = knowledge_file.get("indexVersion")
        for chunk in repo.state.get("knowledge_chunks", []):
            if chunk.get("fileId") == knowledge_file["id"]:
                chunk["scenarioTag"] = SCENARIO_TAG
        for vector in repo.state.get("knowledge_vectors", []):
            if vector.get("fileId") == knowledge_file["id"]:
                vector["scenarioTag"] = SCENARIO_TAG
    for field in repo.state.get("extracted_fields", []):
        if field.get("documentVersionId") == version["id"]:
            field["scenarioTag"] = SCENARIO_TAG
    for evidence in repo.state.get("evidence_links", []):
        if evidence.get("documentVersionId") == version["id"]:
            evidence["scenarioTag"] = SCENARIO_TAG
    return {"applied": applied, "targeting": targeting_result, "slice": slice_result, "vector": vector_result}


def ensure_bindings(
    project_id: str,
    document: dict[str, Any],
    version: dict[str, Any],
    mapping: dict[str, Any],
) -> list[dict[str, Any]]:
    targets_by_node: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for target in mapping_binding_targets(mapping):
        targets_by_node[int(target.get("nodeId") or 0)].append(target)

    bindings: list[dict[str, Any]] = []
    for node_id, targets in sorted(targets_by_node.items()):
        if not node_id:
            continue
        resolved = [requirement(project_id, target) for target in targets]
        unresolved = [target for target, item in zip(targets, resolved) if item is None]
        if unresolved:
            raise RuntimeError(
                f"Unresolved Scan binding target for {document.get('fileName')}: "
                f"node={node_id}, targets={unresolved}"
            )
        requirements = [item for item in resolved if item is not None]
        primary = requirements[0]
        binding_id = f"BIND-SCAN-{stable_doc_id(document['id'] + str(node_id))[:10].upper()}"
        matches = [
            item
            for item in repo.state.get("bindings", [])
            if item.get("projectId") == project_id
            and int(item.get("nodeId") or 0) == node_id
            and item.get("documentVersionId") == version["id"]
        ]
        existing = matches[0] if matches else None
        if len(matches) > 1:
            duplicate_ids = {str(item.get("id") or "") for item in matches[1:]}
            repo.state["bindings"] = [
                item for item in repo.state.get("bindings", []) if str(item.get("id") or "") not in duplicate_ids
            ]
        if existing is None:
            existing = {}
            repo.state.setdefault("bindings", []).insert(0, existing)

        review_point_ids = {
            str(item)
            for item in [*(existing.get("reviewPointIds") or []), *(item.get("id") for item in requirements)]
            if item
        }
        existing.update(
            {
                "id": binding_id,
                "projectId": project_id,
                "nodeId": node_id,
                "requirementId": primary.get("id"),
                "requirementName": requirement_name(primary),
                "reviewPointIds": sorted(review_point_ids),
                "materialTypeCodes": sorted(
                    {str(item.get("materialTypeCode") or "") for item in requirements if item.get("materialTypeCode")}
                ),
                "documentId": document["id"],
                "documentVersionId": version["id"],
                "fileName": document["fileName"],
                "versionNo": version.get("versionNo") or "V1",
                "usage": "原始提交" if mapping.get("role") == "contractor" else "检测报告",
                "sourceOrgName": document.get("sourceOrgName") or "",
                "bindingStatus": "已提交",
                "boundByName": document.get("uploaderName") or "李工",
                "boundAt": existing.get("boundAt") or server_time(),
                "source": "scan_explicit_mapping",
                "scenarioTag": SCENARIO_TAG,
                "scenarioBindingVersion": SCENARIO_BINDING_VERSION,
                "actions": (
                    ["review:save", "review:return-correction"]
                    if mapping.get("role") == "contractor"
                    else ["ndt:submit"]
                ),
            }
        )
        bindings.append(existing)
    return bindings


def make_upload_sessions(project_id: str, imported: list[dict[str, Any]]) -> None:
    for role in ("contractor", "ndt"):
        session_id = f"UPS-SCAN-{role.upper()}-V1"
        repo.state["upload_sessions"] = [item for item in repo.state.get("upload_sessions", []) if item.get("id") != session_id]
        actor = NDT_USER if role == "ndt" else CONTRACTOR_USER
        files = [
            {
                "documentId": item["document"]["id"],
                "documentVersionId": item["version"]["id"],
                "fileName": item["document"]["fileName"],
                "materialCategory": item["mapping"].get("materialCategory"),
                "storageBucket": "local",
                "storageKey": item["version"]["storageKey"],
                "status": "已上传",
                "fileSize": item["version"]["fileSize"],
                "contentType": item["document"]["fileType"],
                "uploadedAt": item["version"]["uploadTime"],
            }
            for item in imported
            if item["mapping"].get("role") == role
        ]
        if not files:
            continue
        repo.state["upload_sessions"].insert(
            0,
            {
                "id": session_id,
                "projectId": project_id,
                "status": "已完成",
                "files": files,
                "uploadToken": stable_doc_id(session_id),
                "createdAt": server_time(),
                "completedAt": server_time(),
                "expiresAt": server_time(),
                "scenarioTag": SCENARIO_TAG,
                "sourceOrgName": actor["org"],
                "uploaderName": actor["name"],
            },
        )


def ensure_role_member_scope(project_id: str, role: str, actor: dict[str, str], node_ids: set[int]) -> dict[str, Any]:
    desired_scope = sorted({int(item) for item in node_ids if int(item)})
    existing = next(
        (
            item
            for item in repo.state.get("project_members", [])
            if item.get("projectId") == project_id
            and item.get("role") == role
            and item.get("userId") == actor["userId"]
        ),
        None,
    )
    if existing is None:
        existing = {
            "id": f"PM-SCAN-{role.upper()}-{stable_doc_id(project_id + role)[:8].upper()}",
            "projectId": project_id,
            "userId": actor["userId"],
            "role": role,
            "status": "启用",
            "actions": repo.role_actions(role),
        }
        repo.state.setdefault("project_members", []).insert(0, existing)
    existing_scope = {int(item) for item in existing.get("nodeScope") or []}
    existing.update(
        {
            "name": actor["name"],
            "orgName": actor["org"],
            "nodeScope": sorted(existing_scope | set(desired_scope)),
            "actions": repo.role_actions(role),
            "status": "启用",
            "updatedAt": server_time(),
            "scenarioTag": SCENARIO_TAG,
        }
    )
    return existing


def sync_actor_membership_orgs(actor: dict[str, str], role: str) -> int:
    """Keep every project membership for this actor aligned with the login orgName.

    authorized_node_scope rejects members whose orgName differs from the user profile,
    which previously hid NDT / contractor projects after org renames.
    """
    changed = 0
    for member in repo.state.get("project_members", []):
        if member.get("userId") != actor["userId"] or member.get("role") != role:
            continue
        if (
            member.get("orgName") == actor["org"]
            and member.get("name") == actor["name"]
            and member.get("status") == "启用"
        ):
            continue
        member["orgName"] = actor["org"]
        member["name"] = actor["name"]
        member["status"] = "启用"
        member["updatedAt"] = server_time()
        changed += 1
    return changed


def project_tree_node_ids(project_id: str) -> set[int]:
    return {
        int(item["nodeId"])
        for item in repo.state.get("tree_nodes", [])
        if item.get("projectId") == project_id and item.get("nodeId") is not None
    }


def ensure_owner_progress_report(project_id: str, node_ids: set[int]) -> dict[str, Any] | None:
    """Give建设方 a visible report/archive entry for the Scan scenario project."""
    existing = next(
        (
            item
            for item in repo.state.get("reports", [])
            if item.get("projectId") == project_id and item.get("scenarioTag") == SCENARIO_TAG
        ),
        None,
    )
    report_node_ids = sorted(node_ids) or [1, 16, 24, 40]
    report = existing or {
        "id": f"RPT-SCAN-{stable_doc_id(project_id)[:8].upper()}",
        "projectId": project_id,
    }
    report.update(
        {
            "title": "广东 LNG 支线改造工程监检过程报告（Scan 测试）",
            "reportNo": "RPT-GDLNG-SCAN-001",
            "status": "编制中",
            "nodeIds": report_node_ids[:12],
            "version": "V0.1",
            "ownerOrgName": OWNER_USER["org"],
            "inspectionOrgName": INSPECTION_USER["org"],
            "summary": "施工方与无损检测资料已提交，监检审查进行中；供建设方查看进度。",
            "updatedAt": server_time(),
            "createdAt": report.get("createdAt") or server_time(),
            "actions": ["report:view", "report:export"],
            "scenarioTag": SCENARIO_TAG,
        }
    )
    if existing is None:
        repo.state.setdefault("reports", []).insert(0, report)
    archive = next(
        (
            item
            for item in repo.state.get("archive_items", [])
            if item.get("projectId") == project_id and item.get("scenarioTag") == SCENARIO_TAG
        ),
        None,
    )
    if archive is None:
        repo.state.setdefault("archive_items", []).insert(
            0,
            {
                "id": f"ARC-SCAN-{stable_doc_id(project_id)[:8].upper()}",
                "projectId": project_id,
                "nodeId": report_node_ids[0],
                "title": "Scan 测试过程资料包",
                "category": "过程报告",
                "status": "待归档",
                "reportId": report["id"],
                "updatedAt": server_time(),
                "actions": ["archive:view"],
                "scenarioTag": SCENARIO_TAG,
            },
        )
    return report


def ensure_user_profile(role: str, actor: dict[str, str]) -> dict[str, Any] | None:
    profile_defaults = ROLE_PROFILE_DEFAULTS.get(role)
    user = repo.find_one("users", actor["userId"])
    if not profile_defaults and user is None:
        return None
    if user is None:
        username = (profile_defaults or {}).get("username") or role
        user = {
            "id": actor["userId"],
            "username": username,
            "password": username,
            "passwordHash": f"plain:{username}",
            "role": role,
            "roleId": (profile_defaults or {}).get("roleId"),
            "roleLabel": (profile_defaults or {}).get("roleLabel") or role,
            "defaultPath": (profile_defaults or {}).get("defaultPath") or f"/workbench/{role}",
            "authVersion": 0,
            "mustChangePassword": False,
        }
        repo.state.setdefault("users", []).insert(0, user)
    user.update(
        {
            "role": role,
            "roleId": (profile_defaults or {}).get("roleId") or user.get("roleId"),
            "roleLabel": (profile_defaults or {}).get("roleLabel") or user.get("roleLabel") or role,
            "displayName": actor["name"],
            "name": actor["name"],
            "orgUnitName": actor["org"],
            "orgName": actor["org"],
            "permissions": repo.role_actions(role),
            "status": "启用",
            "defaultPath": (
                (profile_defaults or {}).get("defaultPath")
                or user.get("defaultPath")
                or f"/workbench/{role}"
            ),
            "updatedAt": server_time(),
            "scenarioTag": SCENARIO_TAG,
        }
    )
    return user


def create_contractor_submission(project_id: str, node_id: int, bindings: list[dict[str, Any]]) -> dict[str, Any]:
    submission_id = f"SUB-SCAN-{node_id}-{stable_doc_id('|'.join(sorted(item['id'] for item in bindings)))[:8].upper()}"
    snapshot_id = f"SNAP-{submission_id}"
    todo_id = f"TODO-SCAN-{node_id}-{stable_doc_id(submission_id)[:8].upper()}"
    changed = [repo.set_node_status(project_id, node_id, "待人工确认")]
    todo = {
        "id": todo_id,
        "title": f"节点 {node_id} 资料待人工确认",
        "projectId": project_id,
        "nodeId": node_id,
        "targetType": "submission",
        "targetId": submission_id,
        "status": "待处理",
        "priority": "高",
        "assigneeName": INSPECTION_REVIEWER,
        "actions": ["review:save", "ai:recheck"],
        "scenarioTag": SCENARIO_TAG,
    }
    repo.state["todos"].insert(0, todo)
    submission = {
        "submissionId": submission_id,
        "snapshotId": snapshot_id,
        "projectId": project_id,
        "nodeIds": [node_id],
        "bindingIds": [item["id"] for item in bindings],
        "batchName": f"Scan 测试资料提交 - 节点 {node_id}",
        "submitterComment": "由 Scan 离线资料迁移生成，施工方已完成上传并提交。",
        "nextStatus": "待人工确认",
        "submittedAt": server_time(),
        "createdTodoIds": [todo_id],
        "changed": changed,
        "createdBindingIds": [item["id"] for item in bindings],
        "scenarioTag": SCENARIO_TAG,
        "snapshot": {"bindings": [repo.clone(item) for item in bindings]},
    }
    repo.state["submissions"].insert(0, submission)
    input_versions = [item["documentVersionId"] for item in bindings]
    ai_run_id = f"AIRUN-SCAN-{node_id}-{stable_doc_id(submission_id)[:8].upper()}"
    repo.state["ai_runs"].insert(
        0,
        {
            "id": ai_run_id,
            "projectId": project_id,
            "nodeId": node_id,
            "subject": (repo.node(project_id, node_id) or {}).get("name") or f"节点 {node_id}",
            "model": "scan-import-offline-review",
            "promptVersion": f"scan-node-{node_id}-v1",
            "ruleVersion": "scan-test-fixture",
            "inputDocumentVersionIds": input_versions,
            "status": "待人工确认",
            "startedAt": server_time(),
            "finishedAt": server_time(),
            "steps": [
                {
                    "id": f"STEP-SCAN-{node_id}-001",
                    "title": "Scan OCR 结果导入",
                    "action": "导入已完成 OCR 的测试资料",
                    "conclusion": "待人工确认",
                    "evidenceLinkIds": [
                        item["id"]
                        for item in repo.state.get("evidence_links", [])
                        if item.get("documentVersionId") in set(input_versions)
                    ][:8],
                }
            ],
            "suggestion": {
                "id": f"AIS-SCAN-{node_id}-{stable_doc_id(submission_id)[:8].upper()}",
                "result": "需人工确认",
                "opinionDraft": "Scan 测试资料已完成 OCR 和证据入库，请监检人员核对原文、OCR 字段和节点资料要求。",
                "risks": ["离线 OCR 结果需人工确认", "HEIC 图纸类资料需核对原图可读性"],
                "confidence": 0.72,
                "manualConfirmItems": ["原文一致性", "OCR 字段", "资料项匹配"],
            },
            "evidenceLinks": [
                repo.clone(item)
                for item in repo.state.get("evidence_links", [])
                if item.get("documentVersionId") in set(input_versions)
            ][:12],
            "findingDrafts": [],
            "scenarioTag": SCENARIO_TAG,
        },
    )
    return submission


def create_ndt_submission(project_id: str, ndt_items: list[dict[str, Any]], ndt_bindings: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not ndt_items:
        return None
    node_id = 40
    node_ids = sorted({int(item.get("nodeId") or 0) for item in ndt_bindings if int(item.get("nodeId") or 0)})
    if node_id not in node_ids:
        node_ids.insert(0, node_id)
    report_ids: list[str] = []
    for item in ndt_items:
        document = item["document"]
        report_id = f"NDT-RPT-SCAN-{stable_doc_id(document['id'])[:8].upper()}"
        report = {
            "id": report_id,
            "projectId": project_id,
            "nodeId": node_id,
            "nodeIds": node_ids,
            "reportNo": "2021SHZH-014RTBG-01",
            "entrustNo": "WT-SCAN-2021SHZH-014",
            "method": "RT",
            "detectionRatio": "10%",
            "standardCode": "NB/T 47013.2-2015",
            "evaluatorName": "王工",
            "reviewerName": "赵工",
            "fileId": document["id"],
            "relatedFilmIds": [],
            "status": "待审查",
            "conclusion": "Scan 导入射线检测报告，OCR 已完成，等待监检审查。",
            "uploadedAt": item["version"].get("uploadTime") or server_time(),
            "submittedAt": server_time(),
            "actions": ["ndt:submit", "review:save"],
            "scenarioTag": SCENARIO_TAG,
        }
        repo.state["ndt_reports"].insert(0, report)
        repo.state["ndt_records"].insert(
            0,
            {
                "id": f"NDT-REC-SCAN-{stable_doc_id(document['id'])[:8].upper()}",
                "projectId": project_id,
                "nodeId": node_id,
                "nodeIds": node_ids,
                "recordNo": "REC-RT-SCAN-001",
                "reportId": report_id,
                "weldNo": "W-SCAN-RT-001",
                "pipelineNo": "PL8301",
                "entrustNo": report["entrustNo"],
                "reportNo": report["reportNo"],
                "method": "RT",
                "testDate": "2021-04-01",
                "detectionRatio": report["detectionRatio"],
                "standardCode": report["standardCode"],
                "evaluatorName": report["evaluatorName"],
                "reviewerName": report["reviewerName"],
                "result": "合格",
                "evaluationLevel": "II",
                "signatureStatus": "待人工确认",
                "stampStatus": "待人工确认",
                "sampleStatus": "待审查",
                "conclusion": report["conclusion"],
                "importedAt": server_time(),
                "actions": ["ndt:record-import", "review:save"],
                "scenarioTag": SCENARIO_TAG,
            },
        )
        report_ids.append(report_id)

    submission_id = f"NDT-SUB-SCAN-{stable_doc_id('|'.join(report_ids))[:8].upper()}"
    todo_id = f"TODO-SCAN-NDT-{stable_doc_id(submission_id)[:8].upper()}"
    changed = [repo.set_node_status(project_id, item, "待审查") for item in node_ids]
    todo = {
        "id": todo_id,
        "title": "无损检测资料待审查",
        "projectId": project_id,
        "nodeId": node_id,
        "targetType": "submission",
        "targetId": submission_id,
        "status": "待处理",
        "priority": "高",
        "assigneeName": INSPECTION_REVIEWER,
        "actions": ["review:save"],
        "scenarioTag": SCENARIO_TAG,
    }
    repo.state["todos"].insert(0, todo)
    submission = {
        "submissionId": submission_id,
        "snapshotId": f"SNAP-{submission_id}",
        "projectId": project_id,
        "nodeId": node_id,
        "nodeIds": node_ids,
        "submissionType": "ndt",
        "batchName": "Scan 无损检测资料提交",
        "submitterComment": "由 Scan 离线资料迁移生成，无损机构已完成上传并提交。",
        "nextStatus": "待审查",
        "submittedAt": server_time(),
        "createdTodoIds": [todo_id],
        "reportIds": report_ids,
        "filmIds": [],
        "bindingIds": [item["id"] for item in ndt_bindings],
        "changed": changed,
        "scenarioTag": SCENARIO_TAG,
        "snapshot": {
            "reports": [repo.clone(report) for report in repo.state["ndt_reports"] if report.get("id") in set(report_ids)],
            "films": [],
            "records": [repo.clone(record) for record in repo.state["ndt_records"] if record.get("reportId") in set(report_ids)],
        },
    }
    repo.state["submissions"].insert(0, submission)
    return submission


def refresh_knowledge_source_counts() -> None:
    source = repo.find_one("knowledge_sources", "KS-PROJECT-FILE")
    if not source:
        return
    file_ids = {item["id"] for item in repo.state.get("knowledge_files", []) if item.get("sourceId") == "KS-PROJECT-FILE"}
    source["fileCount"] = len(file_ids)
    source["chunkCount"] = len([item for item in repo.state.get("knowledge_chunks", []) if item.get("fileId") in file_ids])
    source["vectorStatus"] = "已向量化"
    source["updatedAt"] = server_time()


def refresh_project_node_binding_counts(project_id: str) -> None:
    counts: dict[int, set[str]] = defaultdict(set)
    for binding in repo.state.get("bindings", []):
        if binding.get("projectId") != project_id:
            continue
        node_id = int(binding.get("nodeId") or 0)
        document_id = str(binding.get("documentId") or "")
        if node_id and document_id:
            counts[node_id].add(document_id)
    for node in repo.state.get("project_nodes", []):
        if node.get("projectId") != project_id:
            continue
        node["fileCount"] = len(counts.get(int(node.get("nodeId") or 0), set()))
        node["updatedAt"] = server_time()


def sync_project_clause_packages(project_id: str, *, repository: Any = repo) -> dict[str, Any]:
    """Keep the Scan fixture project on the current pack and persist its clause bindings."""
    project = repository.require_project(project_id)
    if not project:
        raise ValueError(f"project not found: {project_id}")
    pack = load_business_pack(str(project.get("businessPackId") or "engineering_inspection_v1"))
    now = server_time()
    project.update(
        {
            "businessPackId": pack["id"],
            "businessPackVersion": pack["version"],
            "domainType": pack["domainType"],
            "businessPackSnapshotHash": pack["snapshotHash"],
            "businessPackSnapshot": business_pack_snapshot(pack),
            "updatedAt": now,
        }
    )
    updated_nodes = 0
    for node in repository.state.get("tree_nodes", []):
        if node.get("projectId") != project_id:
            continue
        node["businessPackId"] = pack["id"]
        node["businessPackVersion"] = pack["version"]
        node["updatedAt"] = now
        updated_nodes += 1
    bound_nodes = bind_project_node_clause_packages(
        repository.state,
        project,
        pack,
        bound_at=now,
    )
    return {
        "businessPackId": pack["id"],
        "businessPackVersion": pack["version"],
        "updatedNodes": updated_nodes,
        "boundClausePackageNodes": bound_nodes,
    }


def validate_file_mappings(review_points: list[dict[str, Any]] | None = None) -> list[str]:
    points = review_points if review_points is not None else configured_material_review_points()
    errors: list[str] = []
    for file_name, mapping in FILE_MAPPINGS.items():
        targets = mapping_binding_targets(mapping)
        if not targets:
            errors.append(f"{file_name}: no binding targets")
            continue
        seen: set[tuple[int, str]] = set()
        for target in targets:
            resolved = resolve_binding_target(target, points)
            if resolved is None:
                errors.append(f"{file_name}: unresolved target {target}")
                continue
            key = (int(target.get("nodeId") or 0), str(resolved.get("id") or ""))
            if key in seen:
                errors.append(f"{file_name}: duplicate target {resolved.get('id')}")
            seen.add(key)
    return errors


def build_plan(scan_dir: Path, raw_ocr: dict[str, dict[str, Any]], project_id: str) -> list[dict[str, Any]]:
    plan = []
    for path in scan_files(scan_dir):
        mapping = FILE_MAPPINGS.get(path.name)
        raw = raw_ocr.get(path.name)
        if not mapping:
            plan.append({"file": path.name, "status": "skipped", "reason": "没有映射规则"})
            continue
        if not raw:
            plan.append({"file": path.name, "status": "skipped", "reason": "没有 OCR 结果"})
            continue
        try:
            import_path = resolve_import_source_path(scan_dir, path)
        except FileNotFoundError as exc:
            plan.append({"file": path.name, "status": "skipped", "reason": str(exc)})
            continue
        hash_value = sha256_file(import_path)
        legacy_file_names = {path.name} if path.name != import_path.name else set()
        document, version = find_document(
            project_id,
            import_path.name,
            hash_value,
            import_path.stat().st_size,
            legacy_file_names=legacy_file_names,
        )
        binding_plan = []
        for target in mapping_binding_targets(mapping):
            req = requirement(project_id, target)
            binding_plan.append(
                {
                    "nodeId": int(target.get("nodeId") or 0),
                    "requirementId": (req or {}).get("id"),
                    "requirementName": requirement_name(req) if req else None,
                }
            )
        plan.append(
            {
                "file": import_path.name,
                "sourceFile": path.name,
                "status": "ready",
                "role": mapping["role"],
                "bindings": binding_plan,
                "materialCategory": mapping.get("materialCategory"),
                "existingDocumentId": (document or {}).get("id"),
                "existingVersionId": (version or {}).get("id"),
                "ocrPages": raw.get("page_count"),
                "ocrCategory": raw.get("category"),
            }
        )
    return plan


def print_plan(plan: list[dict[str, Any]]) -> None:
    print("file\trole\tbindings\tmaterial\texisting\tocr")
    for item in plan:
        if item["status"] != "ready":
            print(f"{item['file']}\t-\t-\t-\t{item['status']}\t{item['reason']}")
            continue
        existing = item.get("existingDocumentId") or "NEW"
        bindings = "; ".join(
            f"{binding['nodeId']}:{binding.get('requirementName') or binding.get('requirementId') or 'UNRESOLVED'}"
            for binding in item.get("bindings") or []
        )
        print(
            f"{item['file']}\t{item['role']}\t{bindings}\t{item['materialCategory']}\t{existing}\t"
            f"{item.get('ocrCategory')}:{item.get('ocrPages')}p"
        )


def apply_import(scan_dir: Path, raw_ocr: dict[str, dict[str, Any]], project_id: str, *, with_vectors: bool) -> dict[str, Any]:
    clause_package_sync = sync_project_clause_packages(project_id)
    clear_stats = clear_prior_scan_flow(project_id, set(raw_ocr.keys()))
    imported: list[dict[str, Any]] = []
    bindings_by_role: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for path in scan_files(scan_dir):
        mapping = FILE_MAPPINGS.get(path.name)
        raw = raw_ocr.get(path.name)
        if not mapping or not raw:
            continue
        import_path = resolve_import_source_path(scan_dir, path)
        normalized_ocr = normalize_ocr_payload(raw, import_path)
        upload_session_id = f"UPS-SCAN-{mapping['role'].upper()}-V1"
        records = ensure_document_records(
            project_id,
            import_path,
            mapping,
            upload_session_id,
            original_file_name=path.name,
        )
        apply_ocr_and_index(
            records["document"],
            records["version"],
            normalized_ocr,
            mapping,
            with_vectors=with_vectors,
        )
        bindings = ensure_bindings(project_id, records["document"], records["version"], mapping)
        imported.append({**records, "mapping": mapping, "ocr": normalized_ocr, "bindings": bindings})
        bindings_by_role[mapping["role"]].extend(bindings)
    make_upload_sessions(project_id, imported)

    contractor_by_node: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for binding in bindings_by_role.get("contractor", []):
        contractor_by_node[int(binding["nodeId"])].append(binding)
    contractor_submissions = [
        create_contractor_submission(project_id, node_id, bindings)
        for node_id, bindings in sorted(contractor_by_node.items())
        if bindings
    ]
    ndt_items = [item for item in imported if item["mapping"].get("role") == "ndt"]
    ndt_submission = create_ndt_submission(project_id, ndt_items, bindings_by_role.get("ndt", []))
    contractor_member = ensure_role_member_scope(
        project_id,
        "contractor",
        CONTRACTOR_USER,
        {int(item["nodeId"]) for item in bindings_by_role.get("contractor", [])},
    )
    ndt_member = ensure_role_member_scope(
        project_id,
        "ndt",
        NDT_USER,
        {int(item["nodeId"]) for item in bindings_by_role.get("ndt", [])},
    )
    shared_scope = {
        int(item["nodeId"])
        for item in bindings_by_role.get("contractor", []) + bindings_by_role.get("ndt", [])
    }
    owner_member = ensure_role_member_scope(
        project_id,
        "owner",
        OWNER_USER,
        shared_scope | {1, 16, 24, 40, 59, 68},
    )
    inspection_member = ensure_role_member_scope(
        project_id,
        "inspection",
        INSPECTION_USER,
        project_tree_node_ids(project_id) or shared_scope,
    )
    contractor_user = ensure_user_profile("contractor", CONTRACTOR_USER)
    ndt_user = ensure_user_profile("ndt", NDT_USER)
    owner_user = ensure_user_profile("owner", OWNER_USER)
    inspection_user = ensure_user_profile("inspection", INSPECTION_USER)
    membership_org_sync = {
        "contractor": sync_actor_membership_orgs(CONTRACTOR_USER, "contractor"),
        "ndt": sync_actor_membership_orgs(NDT_USER, "ndt"),
        "owner": sync_actor_membership_orgs(OWNER_USER, "owner"),
        "inspection": sync_actor_membership_orgs(INSPECTION_USER, "inspection"),
    }
    owner_report = ensure_owner_progress_report(project_id, shared_scope)
    refresh_knowledge_source_counts()
    refresh_project_node_binding_counts(project_id)
    project = repo.require_project(project_id)
    if project:
        project["status"] = "在监检审查中"
        project["currentNodeId"] = 40 if ndt_submission else (contractor_submissions[0]["nodeIds"][0] if contractor_submissions else project.get("currentNodeId"))
        project["updatedAt"] = server_time()
        project["scenarioTag"] = SCENARIO_TAG
        project["ownerOrgName"] = OWNER_USER["org"]
        project["contractorOrgName"] = CONTRACTOR_USER["org"]
        project["ndtOrgName"] = NDT_USER["org"]
        project["inspectionOrgName"] = INSPECTION_USER["org"]
    return {
        "clausePackages": clause_package_sync,
        "clear": clear_stats,
        "importedFiles": len(imported),
        "convertedHeicFiles": sum(
            Path(str(item["document"].get("originalFileName") or "")).suffix.lower() in HEIC_SUFFIXES
            for item in imported
        ),
        "contractorSubmissions": len(contractor_submissions),
        "ndtSubmission": bool(ndt_submission),
        "bindings": len([item for values in bindings_by_role.values() for item in values]),
        "ownerReportId": (owner_report or {}).get("id"),
        "membershipOrgSync": membership_org_sync,
        "roleScopes": {
            "contractor": contractor_member.get("nodeScope", []),
            "ndt": ndt_member.get("nodeScope", []),
            "owner": owner_member.get("nodeScope", []),
            "inspection": inspection_member.get("nodeScope", []),
        },
        "users": {
            "contractor": (contractor_user or {}).get("orgName"),
            "ndt": (ndt_user or {}).get("orgName"),
            "owner": (owner_user or {}).get("orgName"),
            "inspection": (inspection_user or {}).get("orgName"),
        },
    }


def backup_sqlite() -> Path | None:
    if not repo.sqlite_path:
        return None
    source = Path(repo.sqlite_path)
    if not source.exists():
        return None
    backup = source.with_suffix(source.suffix + f".bak-{server_time().replace(':', '').replace(' ', '-')}")
    shutil.copy2(source, backup)
    return backup


def main() -> int:
    parser = argparse.ArgumentParser(description="Import Scan files and OCR output as a complete review-ready test scenario.")
    parser.add_argument("--project-id", default=DEFAULT_PROJECT_ID)
    parser.add_argument("--scan-dir", default=str(WORKSPACE_ROOT / "Scan"))
    parser.add_argument("--ocr-json", default=str(WORKSPACE_ROOT / "output" / "ocr" / "raw_ocr_pages.json"))
    parser.add_argument("--apply", action="store_true", help="Write changes. Default is dry-run.")
    parser.add_argument("--skip-vectors", action="store_true", help="Do not generate offline vectors.")
    parser.add_argument("--no-backup", action="store_true", help="Do not back up SQLite before apply.")
    args = parser.parse_args()

    scan_dir = Path(args.scan_dir).resolve()
    ocr_json = Path(args.ocr_json).resolve()
    if not scan_dir.is_dir():
        raise SystemExit(f"Scan directory not found: {scan_dir}")
    if not ocr_json.is_file():
        raise SystemExit(f"OCR JSON not found: {ocr_json}")

    load_state()
    material_review_sync = sync_material_review_points_from_asset()
    mapping_errors = validate_file_mappings()
    if mapping_errors:
        raise SystemExit("Invalid Scan binding mappings:\n- " + "\n- ".join(mapping_errors))
    raw_ocr = load_ocr_items(ocr_json)
    plan = build_plan(scan_dir, raw_ocr, args.project_id)
    print_plan(plan)
    ready_count = len([item for item in plan if item.get("status") == "ready"])
    print(f"\nready={ready_count} skipped={len(plan) - ready_count} project={args.project_id} scenarioTag={SCENARIO_TAG}")
    if not args.apply:
        print("dry-run only; rerun with --apply to write.")
        return 0

    backup = None if args.no_backup else backup_sqlite()
    if backup:
        print(f"sqliteBackup={backup}")
    result = apply_import(scan_dir, raw_ocr, args.project_id, with_vectors=not args.skip_vectors)
    result["materialReviewPoints"] = material_review_sync
    flush_state()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
