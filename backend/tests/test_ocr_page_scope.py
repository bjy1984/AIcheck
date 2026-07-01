from __future__ import annotations

from pathlib import Path


def test_document_scope_attach_preserves_page_and_scales_pymupdf_bbox() -> None:
    from apps.ocr_service.service import attach_variant_metadata

    result = {
        "metadata": {"documentLevel": True},
        "fragments": [{"pageNo": 2, "text": "第二页文字", "bbox": [1.0, 2.0, 3.0, 4.0]}],
        "fields": [],
        "tables": [],
        "seals": [],
        "layoutBlocks": [],
    }
    attach_variant_metadata(
        result,
        "pymupdf_text_layer",
        {"variantId": "document_original", "engineScope": "document", "preprocessChain": ["document_original"]},
        document_pages=[{"pageNo": 2, "renderScaleX": 2.0, "renderScaleY": 3.0}],
    )

    fragment = result["fragments"][0]
    assert fragment["pageNo"] == 2
    assert fragment["bbox"] == [2.0, 6.0, 6.0, 12.0]
    assert fragment["coordinateSystem"] == "rendered_pixels"
    assert fragment["sourceCoordinateSystem"] == "pdf_points"
    assert fragment["engineScope"] == "document"


def test_document_engines_route_to_document_variant_for_pdf() -> None:
    from apps.ocr_service.routing import route_engine_variants

    variants = [
        {
            "variantId": "page_1_original",
            "pageNo": 1,
            "path": "/tmp/page-1.png",
            "documentPath": "/tmp/sample.pdf",
            "sourceType": "pdf",
            "preprocessChain": ["original"],
        },
        {
            "variantId": "page_2_original",
            "pageNo": 2,
            "path": "/tmp/page-2.png",
            "documentPath": "/tmp/sample.pdf",
            "sourceType": "pdf",
            "preprocessChain": ["original"],
        },
    ]

    routed = route_engine_variants("docling_local", variants, profile={}, page_quality=[], options={})

    assert len(routed) == 1
    assert routed[0]["variantId"] == "document_original"
    assert routed[0]["engineScope"] == "document"
    assert routed[0]["path"] == "/tmp/sample.pdf"


def test_required_seal_routing_keeps_first_and_last_pages() -> None:
    from apps.ocr_service.routing import route_engine_variants

    variants = [
        {
            "variantId": f"page_{page_no}_original",
            "pageNo": page_no,
            "path": f"/tmp/page-{page_no}.png",
            "documentPath": "/tmp/sample.pdf",
            "sourceType": "pdf",
            "preprocessChain": ["original"],
        }
        for page_no in range(1, 11)
    ]
    page_quality = [
        {"pageNo": page_no, "quality": {"hasVisualSealCandidate": page_no in {2, 3}}}
        for page_no in range(1, 11)
    ]
    profile = {"sealRules": {"required": True}, "preprocessPolicy": {"seal": {"maxPages": 2}}}

    routed = route_engine_variants("paddlex_seal_recognition", variants, profile=profile, page_quality=page_quality)

    assert [item["pageNo"] for item in routed] == [1, 10]


def test_table_and_seal_identity_do_not_cross_pages() -> None:
    from apps.ocr_service.fusion import fuse_parse_result, same_table_identity

    assert not same_table_identity(
        {"tableId": "table_1", "pageNo": 1, "coordinateSystem": "rendered_pixels"},
        {"tableId": "table_1", "pageNo": 2, "coordinateSystem": "rendered_pixels"},
    )

    fused = fuse_parse_result(
        {
            "fragments": [],
            "fields": [],
            "tables": [],
            "seals": [
                {"sealId": "seal_1", "pageNo": 1, "bbox": [0, 0, 100, 100], "visualConfidence": 0.9},
                {"sealId": "seal_1", "pageNo": 2, "bbox": [0, 0, 100, 100], "visualConfidence": 0.9},
            ],
        },
        profile={"requiredFields": [], "requiredTables": [], "sealRules": {"required": False}},
    )

    assert len(fused["seals"]) == 2


def test_visual_seal_fragment_enrichment_is_same_page_only() -> None:
    from apps.ocr_service.fusion import fragments_for_seal

    seal = {"pageNo": 2, "bbox": [0, 0, 200, 200], "coordinateSystem": "rendered_pixels"}
    fragments = [
        {"pageNo": 1, "text": "第一页公司章", "bbox": [20, 20, 80, 40], "coordinateSystem": "rendered_pixels"},
        {"pageNo": 2, "text": "第二页公司章", "bbox": [20, 20, 80, 40], "coordinateSystem": "rendered_pixels"},
    ]

    hits = fragments_for_seal(seal, fragments)

    assert [item["text"] for item in hits] == ["第二页公司章"]


def test_docling_table_does_not_use_header_booleans_as_row_col() -> None:
    from apps.ocr_service.engines import docling_table

    table = docling_table(
        {
            "data": {
                "table_cells": [
                    {
                        "text": "管号",
                        "row_header": True,
                        "col_header": True,
                        "start_row_offset_idx": 3,
                        "start_col_offset_idx": 4,
                    }
                ]
            }
        },
        index=1,
        page_no=1,
        bbox=None,
        engine_name="docling_local",
    )

    assert table is not None
    assert table["cells"][0]["row"] == 3
    assert table["cells"][0]["col"] == 4
    assert table["cells"][0]["isHeader"] is True


def test_remediation_control_options_do_not_change_engine_cache_key(tmp_path: Path) -> None:
    from apps.ocr_service.result_cache import build_engine_result_cache_key

    source = tmp_path / "sample.png"
    source.write_bytes(b"sample")
    kwargs = {
        "source_path": source,
        "engine_status": {"engine": "paddleocr_vl_1_6", "version": "test"},
        "variant": {"variantId": "page_1_original", "imageHash": "sha256:image", "preprocessChain": ["original"]},
        "profile": {"profileId": "generic_document_v1", "documentType": "generic_document", "preprocessPolicy": {}},
        "model_manifest": {"modelDirs": {"vl": {"hash": "sha256:model"}}},
    }

    base = build_engine_result_cache_key(**kwargs, options={})
    remediation = build_engine_result_cache_key(
        **kwargs,
        options={"runRemediation": True, "remediationReasons": ["REQUIRED_FIELD_MISSING"], "traceId": "trace-1"},
    )

    assert base == remediation


def test_text_only_seal_candidate_cannot_satisfy_required_seal() -> None:
    from apps.ocr_service.fusion import fuse_parse_result

    result = fuse_parse_result(
        {
            "fragments": [
                {"pageNo": 1, "text": "压力管道设计许可", "bbox": [10, 10, 120, 30], "confidence": 0.95},
                {"pageNo": 1, "text": "TS1810648-2021", "bbox": [10, 35, 120, 55], "confidence": 0.95},
            ],
            "fields": [],
            "tables": [],
            "seals": [],
        },
        profile={
            "requiredFields": [],
            "requiredTables": [],
            "sealRules": {"required": True, "expectedSealTypes": ["design_license_seal"]},
        },
    )

    assert result["seals"]
    assert result["seals"][0]["candidateOnly"] is True
    assert result["seals"][0]["canSatisfyRequiredSeal"] is False
    assert "SEAL_TEXT_LOW_CONFIDENCE" in result["quality"]["reasons"]
    assert result["quality"]["sealCompleteness"] == 0.0


def test_unmapped_bbox_does_not_count_as_valid_evidence() -> None:
    from apps.ocr_service.fusion import has_evidence_box, fuse_parse_result

    field = {
        "fieldCode": "report_no",
        "fieldName": "报告编号",
        "fieldValue": "R-001",
        "pageNo": 1,
        "bbox": [0, 0, 10, 10],
        "coordinateSystem": "docling_local_document",
        "qualityFlags": ["document_coordinate_unmapped"],
    }

    assert has_evidence_box(field) is False

    result = fuse_parse_result(
        {"fragments": [], "fields": [field], "tables": [], "seals": []},
        profile={"requiredFields": ["report_no"], "requiredTables": [], "sealRules": {"required": False}},
    )

    assert result["quality"]["evidenceCompleteness"] == 0.0
    assert "FIELD_EVIDENCE_MISSING" in result["quality"]["reasons"]


def test_bbox_without_explicit_coordinate_system_is_not_valid_evidence() -> None:
    from apps.ocr_service.fusion import has_evidence_box

    assert has_evidence_box({"pageNo": 1, "bbox": [0, 0, 10, 10]}) is False
    assert (
        has_evidence_box(
            {
                "pageNo": 1,
                "bbox": [0, 0, 10, 10],
                "coordinateSystem": "rendered_pixels",
                "coordinateTransformStatus": "original",
            }
        )
        is True
    )


def test_crop_bbox_maps_to_page_coordinates() -> None:
    from apps.ocr_service.service import attach_variant_metadata
    from apps.ocr_service.fusion import has_evidence_box

    result = {
        "fragments": [{"text": "报告编号 R-001", "bbox": [5, 6, 25, 16], "confidence": 0.9}],
        "fields": [],
        "tables": [],
        "seals": [],
        "layoutBlocks": [],
    }
    variant = {
        "variantId": "page_3_field_crop_report_no",
        "pageNo": 3,
        "source": "remediation_crop",
        "engineScope": "crop",
        "coordinateSystem": "crop_pixels",
        "sourceCoordinateSystem": "rendered_pixels",
        "coordinateTransformStatus": "crop_local",
        "cropOffsetX": 120,
        "cropOffsetY": 340,
        "cropSourceVariantId": "page_3_original",
        "cropSourceBbox": [100, 320, 500, 430],
        "preprocessChain": ["field", "crop"],
    }

    attach_variant_metadata(result, "paddle_ocr_v6", variant, document_pages=[{"pageNo": 3}])

    fragment = result["fragments"][0]
    assert fragment["bbox"] == [125.0, 346.0, 145.0, 356.0]
    assert fragment["pageNo"] == 3
    assert fragment["coordinateSystem"] == "rendered_pixels"
    assert fragment["sourceCoordinateSystem"] == "crop_pixels"
    assert fragment["coordinateTransformStatus"] == "mapped_from_crop"
    assert has_evidence_box(fragment) is True


def test_profile_inferred_field_preserves_source_evidence_metadata() -> None:
    from apps.ocr_service.service import add_field_if_missing

    result = {"fields": []}
    fragment = {
        "pageNo": 3,
        "text": "报告编号 R-001",
        "bbox": [1, 2, 3, 4],
        "confidence": 0.91,
        "coordinateSystem": "docling_local_document",
        "sourceCoordinateSystem": "docling_page_coordinates",
        "coordinateTransformStatus": "unmapped",
        "qualityFlags": ["document_coordinate_unmapped"],
        "variantId": "document_original",
        "selectedVariantId": "document_original",
        "sourceEngine": "docling_local",
    }

    add_field_if_missing(result, "report_no", "报告编号", {"text": "R-001", "fragment": fragment})

    field = result["fields"][0]
    assert field["coordinateSystem"] == "docling_local_document"
    assert field["sourceCoordinateSystem"] == "docling_page_coordinates"
    assert field["coordinateTransformStatus"] == "unmapped"
    assert field["qualityFlags"] == ["document_coordinate_unmapped"]
    assert field["variantId"] == "document_original"
    assert field["sourceEngine"] == "docling_local"


def test_long_pdf_page_selection_includes_real_tail_pages() -> None:
    from apps.ocr_service.pages import select_pdf_page_indices

    profile = {"sealRules": {"required": True}}

    assert select_pdf_page_indices(18, 6, profile=profile) == [0, 1, 2, 3, 16, 17]
    assert select_pdf_page_indices(18, 2, profile=profile) == [0, 17]
    assert select_pdf_page_indices(18, 3, profile=profile) == [0, 16, 17]
    assert select_pdf_page_indices(18, 6, profile={"sealRules": {"required": False}}) == [0, 1, 2, 3, 4, 5]


def test_document_level_pdf_routes_without_page_variants() -> None:
    from apps.ocr_service.routing import route_engine_variants

    routed = route_engine_variants(
        "pymupdf_text_layer",
        [],
        profile={},
        page_quality=[],
        options={"documentPath": "/tmp/source.pdf"},
    )

    assert routed == [
        {
            "variantId": "document_original",
            "pageNo": None,
            "path": "/tmp/source.pdf",
            "documentPath": "/tmp/source.pdf",
            "sourceType": "pdf",
            "preprocessChain": ["document_original"],
            "purpose": "document",
            "source": "document",
            "engineScope": "document",
        }
    ]


def test_remediation_builds_table_crop_variant(tmp_path: Path) -> None:
    from PIL import Image
    from apps.ocr_service.service import remediation_variants_for_reasons

    source = tmp_path / "page-1.png"
    Image.new("RGB", (200, 200), (255, 255, 255)).save(source)

    variants = [
        {
            "variantId": "page_1_original",
            "pageNo": 1,
            "path": str(source),
            "documentPath": str(source),
            "sourceType": "png",
            "preprocessChain": ["original"],
        }
    ]
    result = {
        "tables": [
            {
                "tableId": "T1",
                "pageNo": 1,
                "bbox": [20, 30, 160, 170],
                "coordinateSystem": "rendered_pixels",
            }
        ],
        "seals": [],
    }

    routed = remediation_variants_for_reasons(result, variants, {"TABLE_STRUCTURE_LOW_CONFIDENCE"})

    assert routed[0]["purpose"] == "table"
    assert routed[0]["source"] == "remediation_crop"
    assert routed[0]["coordinateSystem"] == "crop_pixels"
    assert routed[0]["sourceCoordinateSystem"] == "rendered_pixels"
    assert routed[0]["cropOffsetX"] < 20
    assert routed[0]["cropOffsetY"] < 30
    assert Path(routed[0]["path"]).exists()


def test_remediation_builds_field_crop_and_routes_to_text_engine(tmp_path: Path) -> None:
    from PIL import Image
    from apps.ocr_service.routing import route_engine_variants
    from apps.ocr_service.service import remediation_variants_for_reasons

    source = tmp_path / "page-1.png"
    Image.new("RGB", (300, 200), (255, 255, 255)).save(source)

    variants = [
        {
            "variantId": "page_1_original",
            "pageNo": 1,
            "path": str(source),
            "documentPath": str(source),
            "sourceType": "png",
            "preprocessChain": ["original"],
        }
    ]
    result = {
        "quality": {"missingFields": ["report_no"]},
        "fragments": [
            {
                "text": "报告编号",
                "pageNo": 1,
                "bbox": [20, 20, 80, 40],
                "coordinateSystem": "rendered_pixels",
                "pageWidth": 300,
                "pageHeight": 200,
            }
        ],
        "fields": [],
        "tables": [],
        "seals": [],
    }

    remediation_variants = remediation_variants_for_reasons(result, variants, {"REQUIRED_FIELD_MISSING"})
    routed = route_engine_variants(
        "paddle_ocr_v6",
        remediation_variants,
        profile={},
        page_quality=[],
        options={"runRemediation": True},
    )

    assert routed
    assert routed[0]["purpose"] == "field"
    assert routed[0]["source"] == "remediation_crop"


def test_default_vlm_fallback_reasons_include_seal_not_found() -> None:
    from apps.ocr_service.profiles import DEFAULT_VLM_FALLBACK_REASONS

    assert "SEAL_NOT_FOUND" in DEFAULT_VLM_FALLBACK_REASONS


def test_cache_schema_versions_are_upgraded() -> None:
    from apps.ocr_service.preprocess import PREPROCESS_CACHE_SCHEMA
    from apps.ocr_service.result_cache import (
        EVIDENCE_CONTRACT_VERSION,
        PAGE_SELECTION_VERSION,
        REMEDIATION_VERSION,
        RESULT_CACHE_SCHEMA,
    )

    assert RESULT_CACHE_SCHEMA == "aicheck-ocr-parse-result-cache-v4"
    assert PREPROCESS_CACHE_SCHEMA == "aicheck-ocr-preprocess-cache-v2"
    assert EVIDENCE_CONTRACT_VERSION == "rendered_pixels_mapped_v1"
    assert PAGE_SELECTION_VERSION == "sparse_tail_pages_v1"
    assert REMEDIATION_VERSION == "crop_remediation_v1"


def test_piping_table_helpers_are_page_scoped() -> None:
    from apps.ocr_service.service import align_piping_text_table_with_grid, best_opencv_grid_table

    tables = [
        {"tableId": "grid_p1", "pageNo": 1, "sourceEngine": "opencv_table_grid_subprocess", "gridCellCount": 100},
        {"tableId": "grid_p2", "pageNo": 2, "sourceEngine": "opencv_table_grid_subprocess", "gridCellCount": 20},
    ]

    assert best_opencv_grid_table(tables, page_no=2)["tableId"] == "grid_p2"
    aligned = align_piping_text_table_with_grid(
        {"tableId": "raw", "pageNo": 2, "rows": 1, "columns": 1, "normalizedRows": [{"pipeNo": "P1"}]},
        {"tableId": "grid_p2", "pageNo": 2, "rows": 2, "columns": 3, "gridCellCount": 6},
    )
    assert aligned["tableId"] == "page_2_piping_characteristic_table_1"
