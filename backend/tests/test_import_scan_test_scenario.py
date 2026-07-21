from __future__ import annotations

from pathlib import Path

from scripts.import_scan_test_scenario import (
    FILE_MAPPINGS,
    fields_from_ocr,
    fragments_from_ocr,
    mapping_binding_targets,
    normalize_ocr_payload,
    resolve_import_source_path,
    sync_project_clause_packages,
    validate_file_mappings,
    vision_bbox_to_xyxy,
)
from libs.material_targeting import load_review_points_from_mapping_doc
from libs.business_pack.clause_store import clause_package_snapshot_for_project_node
from libs.db.repository import InMemoryRepository
from apps.api.routes import requirement_matches_binding


def test_heic_import_uses_full_resolution_png(tmp_path: Path) -> None:
    source = tmp_path / "IMG_6508.heic"
    source.write_bytes(b"heic")
    png = tmp_path / "png" / "IMG_6508.png"
    png.parent.mkdir()
    png.write_bytes(b"png")

    assert resolve_import_source_path(tmp_path, source) == png


def test_vision_bbox_is_converted_from_bottom_left_xywh_to_top_left_xyxy() -> None:
    bbox = vision_bbox_to_xyxy([0.1, 0.7, 0.2, 0.1], 1000, 2000)

    assert bbox == [100.0, 400.0, 300.0, 600.0]


def test_normalize_image_ocr_payload_adds_png_dimensions_and_valid_bbox(tmp_path: Path) -> None:
    from PIL import Image

    png = tmp_path / "IMG_6508.png"
    Image.new("RGB", (1000, 2000), "white").save(png)
    raw = {
        "source_file": "IMG_6508.heic",
        "pages": [
            {
                "source_page": 1,
                "observations": [
                    {"text": "压力管道", "boundingBox": [0.1, 0.7, 0.2, 0.1]},
                ],
            }
        ],
    }

    normalized = normalize_ocr_payload(raw, png)
    page = normalized["pages"][0]
    observation = page["observations"][0]

    assert page["path"] == str(png)
    assert page["coordinateSystem"] == "rendered_pixels"
    assert page["sourceImageWidth"] == 1000
    assert page["sourceImageHeight"] == 2000
    assert observation["bbox"] == [100.0, 400.0, 300.0, 600.0]
    assert observation["coordinateSystem"] == "rendered_pixels"

    fragments = fragments_from_ocr(normalized)
    assert fragments[0]["bbox"] == [100.0, 400.0, 300.0, 600.0]
    assert fragments[0]["coordinateSystem"] == "rendered_pixels"


def test_normalize_pdf_ocr_payload_uses_pdf_page_coordinates(tmp_path: Path) -> None:
    import fitz

    pdf = tmp_path / "drawing.pdf"
    with fitz.open() as document:
        document.new_page(width=600, height=800)
        document.save(pdf)
    raw = {
        "source_file": pdf.name,
        "pages": [
            {
                "source_page": 1,
                "observations": [
                    {"text": "施工图", "boundingBox": [0.1, 0.7, 0.2, 0.1]},
                ],
            }
        ],
    }

    normalized = normalize_ocr_payload(raw, pdf)
    page = normalized["pages"][0]

    assert page["coordinateSystem"] == "pdf_points"
    assert page["width"] == 600
    assert page["height"] == 800
    assert page["observations"][0]["bbox"] == [60.0, 160.0, 180.0, 240.0]


def test_scan_structured_field_inherits_fragment_locator() -> None:
    raw = {
        "pages": [
            {
                "source_page": 3,
                "observations": [
                    {
                        "text": "有效期至：2024年6月21日",
                        "bbox": [80.0, 120.0, 360.0, 150.0],
                        "confidence": 0.91,
                    }
                ],
            }
        ]
    }
    fragments = fragments_from_ocr(raw)

    fields = fields_from_ocr(raw, {"materialCategory": "设计单位许可证"}, fragments)
    validity = next(item for item in fields if item["fieldName"] == "有效期至")

    assert validity["fieldValue"] == "2024年6月21日"
    assert validity["pageNo"] == 3
    assert validity["bbox"] == [80.0, 120.0, 360.0, 150.0]
    assert validity["sourceFragmentId"] == fragments[0]["id"]
    assert validity["formalEvidenceEligible"] is True


def test_scan_import_syncs_current_business_pack_clause_bindings() -> None:
    repository = InMemoryRepository()
    project_id = "P-2026-HDCP-001"
    project = repository.require_project(project_id)
    assert project
    project["businessPackVersion"] = "stale-test-version"
    repository.state["project_node_clause_packages"] = [
        item
        for item in repository.state["project_node_clause_packages"]
        if item.get("projectId") != project_id
    ]

    result = sync_project_clause_packages(project_id, repository=repository)

    snapshot = clause_package_snapshot_for_project_node(repository.state, project_id, 1)
    assert result["boundClausePackageNodes"] == 69
    assert project["businessPackVersion"] == result["businessPackVersion"]
    assert snapshot
    assert snapshot["sourceRuleId"] == "R01"
    assert all(
        node.get("businessPackVersion") == result["businessPackVersion"]
        for node in repository.state["tree_nodes"]
        if node.get("projectId") == project_id
    )


def test_every_scan_binding_target_resolves_to_current_material_review_point() -> None:
    workspace_root = Path(__file__).resolve().parents[2]
    review_points = load_review_points_from_mapping_doc(workspace_root / "docs" / "工程监检资料映射表.md")

    assert len(FILE_MAPPINGS) == 30
    assert validate_file_mappings(review_points) == []
    assert all(
        not str(target.get("requirementId") or "").startswith("REQ-")
        for mapping in FILE_MAPPINGS.values()
        for target in mapping_binding_targets(mapping)
    )


def test_mixed_scan_pdfs_bind_to_their_actual_business_materials() -> None:
    welding_targets = {
        (int(item["nodeId"]), str(item["materialTypeCode"]))
        for item in mapping_binding_targets(FILE_MAPPINGS["20260623105534.pdf"])
    }
    handover_targets = {
        (int(item["nodeId"]), str(item["materialTypeCode"]))
        for item in mapping_binding_targets(FILE_MAPPINGS["20260623104730.pdf"])
    }

    assert (12, "manufacturing_license") not in welding_targets
    assert {(25, "wps_pqr"), (29, "wps_pqr")} <= welding_targets
    assert (32, "wps_pqr") not in welding_targets
    assert (16, "quality_certificate") not in handover_targets
    assert {
        (23, "valve_test_report"),
        (47, "grounding_test_record"),
        (62, "pressure_test_report"),
        (67, "leakage_test_report"),
        (68, "purge_cleaning_record"),
    } <= handover_targets


def test_requirement_matches_secondary_review_point_on_consolidated_binding() -> None:
    binding = {
        "requirementId": "MRP-1-design_document-881699",
        "requirementName": "设计单位许可资质",
        "reviewPointIds": [
            "MRP-1-design_document-881699",
            "MRP-1-design_document-8AE617",
        ],
    }

    assert requirement_matches_binding(
        {"id": "MRP-1-design_document-8AE617", "name": "设计许可范围符合性"},
        binding,
    )
