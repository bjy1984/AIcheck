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


def test_disable_raster_text_ocr_keeps_document_and_fallback_pdf_routes() -> None:
    from apps.ocr_service.routing import route_engine_variants

    variants = [
        {
            "variantId": "page_1_original",
            "pageNo": 1,
            "path": "/tmp/page-1.png",
            "documentPath": "/tmp/license.pdf",
            "sourceType": "pdf",
            "preprocessChain": ["original"],
        }
    ]
    options = {
        "documentPath": "/tmp/license.pdf",
        "enableRasterTextOcr": False,
        "enableFallback": True,
        "forceFallbackOcr": True,
    }

    assert route_engine_variants("paddle_ocr_subprocess", variants, profile={}, page_quality=[], options=options) == []
    text_layer = route_engine_variants("pymupdf_text_layer", variants, profile={}, page_quality=[], options=options)
    fallback = route_engine_variants("paddleocr_vl_1_6", variants, profile={}, page_quality=[], options=options)

    assert text_layer[0]["variantId"] == "document_original"
    assert text_layer[0]["engineScope"] == "document"
    assert fallback[0]["variantId"] == "document_original"
    assert fallback[0]["engineScope"] == "document"

    crop_options = {**options, "runRemediation": True}
    crop_variants = [
        {
            "variantId": "page_1_field_crop_certificate_no",
            "pageNo": 1,
            "path": "/tmp/crop.png",
            "source": "remediation_crop",
            "purpose": "field",
            "engineScope": "crop",
        }
    ]
    crop_routes = route_engine_variants(
        "paddle_ocr_subprocess",
        crop_variants,
        profile={},
        page_quality=[],
        options=crop_options,
    )
    assert crop_routes == crop_variants


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
    profile = {"sealRules": {"required": True}, "preprocessPolicy": {"seal": {"maxPages": 2, "enablePaddlexSeal": True}}}

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


def test_merge_parse_result_preserves_candidate_metadata_without_overwriting_existing() -> None:
    from apps.ocr_service.service import merge_parse_result

    target = {
        "metadata": {"fastFirstMode": True, "pageCoverageMode": "fast_first"},
        "fragments": [],
        "layoutBlocks": [],
        "fields": [],
        "tables": [],
        "seals": [],
        "signatures": [],
        "diagnostics": [],
    }
    incoming = {
        "metadata": {
            "pageCoverageMode": "deep_scan",
            "pdfTextLayerFastPathSkipped": True,
            "fallbackOcrForced": True,
        },
        "fragments": [{"pageNo": 1, "text": "许可证"}],
    }

    merge_parse_result(target, incoming)

    assert target["metadata"]["fastFirstMode"] is True
    assert target["metadata"]["pageCoverageMode"] == "fast_first"
    assert target["metadata"]["pdfTextLayerFastPathSkipped"] is True
    assert target["metadata"]["fallbackOcrForced"] is True
    assert target["fragments"][0]["text"] == "许可证"


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
    from apps.ocr_service.fusion import fuse_parse_result, has_evidence_box

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
    from apps.ocr_service.fusion import has_evidence_box
    from apps.ocr_service.service import attach_variant_metadata

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
    assert select_pdf_page_indices(18, 1, profile=profile) == [0]
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
    from libs.ocr.profiles import DEFAULT_VLM_FALLBACK_REASONS

    assert "SEAL_NOT_FOUND" in DEFAULT_VLM_FALLBACK_REASONS


def test_cache_schema_versions_are_upgraded() -> None:
    from apps.ocr_service.pages import PAGE_RENDER_VERSION, rendered_page_cache_dir
    from apps.ocr_service.preprocess import PREPROCESS_CACHE_SCHEMA
    from apps.ocr_service.result_cache import (
        EVIDENCE_CONTRACT_VERSION,
        PAGE_SELECTION_VERSION,
        REMEDIATION_VERSION,
        RESULT_CACHE_SCHEMA,
        cache_contract_versions,
    )

    assert RESULT_CACHE_SCHEMA == "aicheck-ocr-parse-result-cache-v12"
    assert PREPROCESS_CACHE_SCHEMA == "aicheck-ocr-preprocess-cache-v2"
    assert EVIDENCE_CONTRACT_VERSION == "rendered_pixels_mapped_v2"
    assert PAGE_SELECTION_VERSION == "sparse_tail_pages_v2"
    assert REMEDIATION_VERSION == "crop_remediation_v2"
    assert PAGE_RENDER_VERSION == "pymupdf_text_to_pixel_matrix_v4"
    assert cache_contract_versions()["resultCacheSchema"]
    assert cache_contract_versions()["pageRenderVersion"] == PAGE_RENDER_VERSION

    cache_path = rendered_page_cache_dir(Path("/tmp/missing.pdf"), dpi=300, max_pages=2, max_long_side=1200)
    assert cache_path.name


def test_pdf_page_render_manifest_round_trips_matrix_metadata(tmp_path: Path) -> None:
    from PIL import Image

    from apps.ocr_service.pages import (
        PAGE_RENDER_VERSION,
        load_pdf_page_manifest,
        save_pdf_page_manifest,
    )

    page_path = tmp_path / "page-1.png"
    Image.new("RGB", (20, 20), (255, 255, 255)).save(page_path)
    pages = [
        {
            "pageNo": 1,
            "path": str(page_path),
            "totalPages": 1,
            "renderedPages": [1],
            "pageRenderVersion": PAGE_RENDER_VERSION,
            "pdfRenderMatrix": [2, 0, 0, 2, 0, 0],
            "pdfTextToPixelMatrix": [0, 2, -2, 0, 100, 0],
            "pdfPixmapX": -100,
            "pdfPixmapY": 0,
        }
    ]

    save_pdf_page_manifest(tmp_path, pages)
    loaded = load_pdf_page_manifest(tmp_path, rendered_pages=[1], total_pages=1)

    assert loaded == pages


def test_pdf_page_cache_hit_uses_manifest_not_get_pixmap(monkeypatch, tmp_path: Path) -> None:
    import sys
    import types

    from PIL import Image

    from apps.ocr_service.pages import (
        PAGE_RENDER_VERSION,
        render_pdf_pages,
        rendered_page_cache_dir,
        save_pdf_page_manifest,
    )

    source = tmp_path / "cached.pdf"
    source.write_bytes(b"%PDF-1.7 cached")
    monkeypatch.setenv("AICHECK_OCR_PAGE_CACHE_DIR", str(tmp_path / "page-cache"))

    cache_dir = rendered_page_cache_dir(source, dpi=300, max_pages=1, max_long_side=0)
    cache_dir.mkdir(parents=True, exist_ok=True)
    page_path = cache_dir / "page-1.png"
    Image.new("RGB", (40, 30), (255, 255, 255)).save(page_path)
    expected_pages = [
        {
            "pageNo": 1,
            "path": str(page_path),
            "width": 40,
            "height": 30,
            "totalPages": 1,
            "renderedPages": [1],
            "pageRenderVersion": PAGE_RENDER_VERSION,
            "pdfRenderMatrix": [1, 0, 0, 1, 0, 0],
            "pdfTextToPixelMatrix": [1, 0, 0, 1, 0, 0],
            "pdfPixmapX": 0,
            "pdfPixmapY": 0,
        }
    ]
    save_pdf_page_manifest(cache_dir, expected_pages)

    class FakePage:
        rotation = 0

        def get_pixmap(self, *args, **kwargs):
            raise AssertionError("cache hit must not render pixmap")

    class FakeDocument:
        page_count = 1

        def __len__(self):
            return 1

        def __getitem__(self, index):
            return FakePage()

        def close(self):
            return None

    monkeypatch.setitem(sys.modules, "fitz", types.SimpleNamespace(open=lambda _path: FakeDocument()))

    pages = render_pdf_pages(source, dpi=300, max_pages=1)

    assert pages == expected_pages


def test_pdf_page_render_falls_back_to_configured_subprocess(monkeypatch, tmp_path: Path) -> None:
    import json
    import subprocess
    import sys

    from PIL import Image

    from apps.ocr_service.pages import PAGE_RENDER_VERSION, render_pdf_pages

    source = tmp_path / "subprocess.pdf"
    source.write_bytes(b"%PDF-1.7 subprocess")
    monkeypatch.setenv("AICHECK_OCR_SUBPROCESS_PYTHON", sys.executable)
    monkeypatch.setenv("AICHECK_OCR_PAGE_CACHE_DIR", str(tmp_path / "page-cache"))
    monkeypatch.setitem(sys.modules, "fitz", None)

    def fake_run(args, **_kwargs):
        out_dir = Path(args[4])
        out_dir.mkdir(parents=True, exist_ok=True)
        page_path = out_dir / "page-1.png"
        Image.new("RGB", (60, 40), (255, 255, 255)).save(page_path)
        return subprocess.CompletedProcess(
            args,
            0,
            stdout=json.dumps(
                {
                    "records": [
                        {
                            "path": str(page_path),
                            "pageNo": 1,
                            "renderDpi": 180,
                            "rotation": 0,
                            "sourceWidth": 120.0,
                            "sourceHeight": 80.0,
                            "renderScaleX": 1.5,
                            "renderScaleY": 1.5,
                            "pdfRenderMatrix": [1.5, 0, 0, 1.5, 0, 0],
                            "pdfTextToPixelMatrix": [1.5, 0, 0, 1.5, 0, 0],
                            "pdfPixmapX": 0,
                            "pdfPixmapY": 0,
                            "requestedRenderDpi": 180,
                            "effectiveRenderDpi": 180,
                            "totalPages": 1,
                            "renderedPages": [1],
                            "truncated": False,
                            "requestedMaxPages": 1,
                            "effectiveMaxPages": 1,
                            "protectedPages": ["first"],
                            "pageRenderVersion": PAGE_RENDER_VERSION,
                        }
                    ]
                }
            ),
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    pages = render_pdf_pages(source, dpi=180, max_pages=1)

    assert len(pages) == 1
    assert pages[0]["width"] == 60
    assert pages[0]["height"] == 40
    assert pages[0]["sourceCoordinateSystem"] == "pdf_points"
    assert pages[0]["pageRenderVersion"] == PAGE_RENDER_VERSION


def test_profile_validator_checks_min_table_cell_evidence_coverage() -> None:
    from copy import deepcopy

    from libs.ocr.profiles import DEFAULT_PROFILE_ID, OCR_PROFILES, validate_profiles

    profile = deepcopy(OCR_PROFILES[DEFAULT_PROFILE_ID])
    profile["qualityRules"]["minTableCellEvidenceCoverage"] = 1.2

    failures = validate_profiles({DEFAULT_PROFILE_ID: profile})

    assert any(item["path"] == "qualityRules.minTableCellEvidenceCoverage" for item in failures)

    profile["qualityRules"]["minTableCellEvidenceCoverage"] = "0.72"
    failures = validate_profiles({DEFAULT_PROFILE_ID: profile})

    assert not any(item["path"] == "qualityRules.minTableCellEvidenceCoverage" for item in failures)

    profile["qualityRules"]["minTableCellEvidenceCoverage"] = "not-a-number"
    failures = validate_profiles({DEFAULT_PROFILE_ID: profile})

    assert any(item["path"] == "qualityRules.minTableCellEvidenceCoverage" for item in failures)


def test_profile_validator_accepts_parseable_boolean_strings_for_required_seal() -> None:
    from copy import deepcopy

    from libs.ocr.profiles import DEFAULT_PROFILE_ID, OCR_PROFILES, validate_profiles

    profile = deepcopy(OCR_PROFILES[DEFAULT_PROFILE_ID])
    profile["sealRules"]["required"] = "false"

    failures = validate_profiles({DEFAULT_PROFILE_ID: profile})

    assert not any(item["path"] == "sealRules.required" for item in failures)

    profile["sealRules"]["required"] = "definitely"
    failures = validate_profiles({DEFAULT_PROFILE_ID: profile})

    assert any(item["path"] == "sealRules.required" for item in failures)


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


def test_opencv_grid_table_is_text_aligned_from_fragment_coordinates() -> None:
    from apps.ocr_service.service import align_grid_tables_with_fragments

    result = {
        "fragments": [
            {"pageNo": 1, "text": "序号", "bbox": [10, 8, 30, 22], "confidence": 0.95},
            {"pageNo": 1, "text": "名称", "bbox": [70, 8, 105, 22], "confidence": 0.94},
            {"pageNo": 1, "text": "图号", "bbox": [170, 8, 205, 22], "confidence": 0.94},
            {"pageNo": 1, "text": "1", "bbox": [14, 38, 24, 52], "confidence": 0.92},
            {"pageNo": 1, "text": "工艺图纸目录", "bbox": [62, 38, 128, 52], "confidence": 0.93},
            {"pageNo": 1, "text": "QX-001", "bbox": [168, 38, 220, 52], "confidence": 0.93},
            {"pageNo": 1, "text": "2", "bbox": [14, 68, 24, 82], "confidence": 0.92},
            {"pageNo": 1, "text": "设备表", "bbox": [62, 68, 102, 82], "confidence": 0.93},
            {"pageNo": 1, "text": "QX-002", "bbox": [168, 68, 220, 82], "confidence": 0.93},
            {"pageNo": 1, "text": "孤立备注", "bbox": [62, 105, 120, 118], "confidence": 0.9},
        ],
        "tables": [
            {
                "tableId": "grid_1",
                "pageNo": 1,
                "sourceEngine": "opencv_table_grid_subprocess",
                "bbox": [0, 0, 260, 130],
                "rows": 4,
                "columns": 3,
                "gridCellCount": 12,
                "gridLineXs": [0, 50, 150, 260],
                "gridLineYs": [0, 30, 60, 90, 130],
                "cells": [{"row": 0, "col": 0, "text": ""}],
                "structureConfidence": 0.82,
            }
        ],
        "diagnostics": [],
    }

    align_grid_tables_with_fragments(result)

    assert len(result["tables"]) == 1
    table = result["tables"][0]
    assert table["sourceEngine"] == "opencv_grid_text_aligned"
    assert table["rows"] == 3
    assert table["columns"] == 3
    assert table["bbox"] == [0.0, 0.0, 260.0, 90.0]
    assert table["normalizedRows"][0]["名称"] == "工艺图纸目录"
    assert table["normalizedRows"][1]["图号"] == "QX-002"
    assert any(cell["text"] == "设备表" for cell in table["cells"])
    assert result["diagnostics"][0]["code"] == "OPENCV_GRID_TEXT_ALIGNED"


def test_opencv_grid_alignment_keeps_multiple_text_segments() -> None:
    from apps.ocr_service.service import align_opencv_grid_table_with_fragments

    grid_table = {
        "tableId": "grid_1",
        "pageNo": 1,
        "sourceEngine": "opencv_table_grid_subprocess",
        "bbox": [0, 0, 520, 380],
        "rows": 9,
        "columns": 3,
        "gridCellCount": 27,
        "gridLineXs": [0, 120, 320, 520],
        "gridLineYs": [0, 40, 80, 120, 180, 220, 260, 300, 340, 380],
        "structureConfidence": 0.82,
    }
    fragments = []

    def add_fragment(row: int, col: int, text: str) -> None:
        x0 = grid_table["gridLineXs"][col] + 12
        y0 = grid_table["gridLineYs"][row] + 10
        fragments.append(
            {
                "pageNo": 1,
                "text": text,
                "bbox": [x0, y0, x0 + 80, y0 + 18],
                "confidence": 0.92,
            }
        )

    for col, text in enumerate(["字段", "值", "备注"]):
        add_fragment(0, col, text)
    for row, values in [(1, ["项目", "卸车站", "A"]), (2, ["阶段", "施工图", "B"])]:
        for col, text in enumerate(values):
            add_fragment(row, col, text)

    for col, text in enumerate(["序号", "名称", "图号"]):
        add_fragment(5, col, text)
    for row, values in [
        (6, ["1", "工艺图纸目录", "QX-001"]),
        (7, ["2", "设备表", "QX-002"]),
        (8, ["3", "管道特性表", "QX-003"]),
    ]:
        for col, text in enumerate(values):
            add_fragment(row, col, text)

    tables = align_opencv_grid_table_with_fragments(grid_table, fragments)

    assert [table["tableId"] for table in tables] == ["grid_1_text_aligned_1", "grid_1_text_aligned_2"]
    assert [table["rows"] for table in tables] == [3, 4]
    assert tables[0]["bbox"] == [0.0, 0.0, 520.0, 120.0]
    assert tables[1]["bbox"] == [0.0, 220.0, 520.0, 380.0]
    assert tables[0]["normalizedRows"][0]["字段"] == "项目"
    assert tables[1]["normalizedRows"][2]["图号"] == "QX-003"


def test_piping_profile_keeps_drawing_title_block_table_candidate() -> None:
    from apps.ocr_service.service import enrich_parse_result
    from libs.ocr.profiles import profile_for

    fragments = [
        {"pageNo": 1, "text": "广东星燃石化设计院有限公司", "bbox": [120, 12, 430, 42], "confidence": 0.95},
        {"pageNo": 1, "text": "项目名称", "bbox": [610, 32, 690, 54], "confidence": 0.94},
        {"pageNo": 1, "text": "PROJECT", "bbox": [610, 55, 690, 74], "confidence": 0.94},
        {"pageNo": 1, "text": "职责", "bbox": [55, 102, 95, 122], "confidence": 0.93},
        {"pageNo": 1, "text": "姓名", "bbox": [145, 102, 190, 122], "confidence": 0.93},
        {"pageNo": 1, "text": "日期", "bbox": [280, 102, 330, 122], "confidence": 0.93},
        {"pageNo": 1, "text": "DUTY", "bbox": [55, 124, 95, 140], "confidence": 0.93},
        {"pageNo": 1, "text": "NAME", "bbox": [145, 124, 190, 140], "confidence": 0.93},
        {"pageNo": 1, "text": "DATE", "bbox": [280, 124, 330, 140], "confidence": 0.93},
        {"pageNo": 1, "text": "编制", "bbox": [55, 150, 95, 170], "confidence": 0.92},
        {"pageNo": 1, "text": "张三", "bbox": [145, 150, 190, 170], "confidence": 0.92},
        {"pageNo": 1, "text": "2021.3", "bbox": [280, 150, 335, 170], "confidence": 0.92},
        {"pageNo": 1, "text": "工艺图纸目录", "bbox": [420, 175, 550, 202], "confidence": 0.95},
        {"pageNo": 1, "text": "DRAWING LIST", "bbox": [420, 205, 560, 226], "confidence": 0.95},
        {"pageNo": 1, "text": "图纸编号", "bbox": [690, 150, 760, 170], "confidence": 0.94},
        {"pageNo": 1, "text": "QX201903S-13-Y-00", "bbox": [815, 150, 980, 170], "confidence": 0.94},
    ]
    result = enrich_parse_result(
        {
            "status": "success",
            "fragments": fragments,
            "fields": [],
            "tables": [
                {
                    "tableId": "large_grid_covering_title_and_drawing_list",
                    "pageNo": 1,
                    "bbox": [35, 0, 1040, 620],
                    "rows": 6,
                    "columns": 6,
                    "structureConfidence": 0.86,
                    "sourceEngine": "opencv_grid_text_aligned",
                    "cells": [
                        {"row": 0, "col": 0, "text": "序号", "bbox": [40, 270, 80, 292], "isHeader": True},
                        {"row": 0, "col": 1, "text": "名称", "bbox": [120, 270, 170, 292], "isHeader": True},
                        {"row": 1, "col": 0, "text": "1", "bbox": [40, 305, 80, 327]},
                        {"row": 1, "col": 1, "text": "工艺图纸目录", "bbox": [120, 305, 250, 327]},
                    ],
                    "normalizedRows": [{"名称": "工艺图纸目录"}],
                    "qualityFlags": ["opencv_grid_structure", "ocr_text_aligned"],
                }
            ],
            "seals": [],
            "diagnostics": [],
        },
        profile=profile_for("piping_characteristic_list_v1"),
        document_version_id="docv-title-block",
        business_pack_id="engineering_inspection_v1",
        model_manifest={},
    )

    table_ids = {table["tableId"] for table in result["tables"]}
    schemas = {table.get("businessSchema") for table in result["tables"]}

    assert "page_1_engineering_drawing_title_block_1" in table_ids
    assert "engineering_drawing_title_block_v1" in schemas
    assert len(result["tables"]) >= 2
    title_block = next(table for table in result["tables"] if table["tableId"] == "page_1_engineering_drawing_title_block_1")
    assert title_block["auxiliaryTable"] is True
    assert title_block["bbox"][3] < 260
    assert any(item["code"] == "ENGINEERING_DRAWING_TITLE_BLOCK_INFERRED" for item in result["diagnostics"])


def test_pp_structure_model_names_follow_local_model_dirs(monkeypatch) -> None:
    from pathlib import Path

    from apps.ocr_service.engines import pp_structure_model_names

    dirs = {
        "layout": Path("/models/PP-DocLayout-L"),
        "text_det": Path("/models/PP-OCRv6_medium_det"),
        "text_rec": Path("/models/PP-OCRv6_medium_rec"),
        "wired_table_structure": Path("/models/SLANeXt_wired"),
        "wired_table_cells": Path("/models/RT-DETR-L_wired_table_cell_det"),
        "wireless_table_structure": Path("/models/SLANeXt_wireless"),
        "wireless_table_cells": Path("/models/RT-DETR-L_wireless_table_cell_det"),
    }

    names = pp_structure_model_names(dirs)

    assert names["layout"] == "PP-DocLayout-L"
    assert names["wired_table_structure"] == "SLANeXt_wired"

    monkeypatch.setenv("AICHECK_PPSTRUCTURE_LAYOUT_MODEL_NAME", "PP-DocLayout_plus-L")
    names = pp_structure_model_names(dirs)

    assert names["layout"] == "PP-DocLayout_plus-L"


def test_pp_structure_empty_table_blocks_are_not_formal_tables() -> None:
    from apps.ocr_service.engines import normalize_structure_result

    tables, blocks = normalize_structure_result(
        [
            {
                "type": "table",
                "bbox": [10, 10, 500, 500],
                "res": {"html": ""},
                "confidence": 0.95,
            }
        ],
        "pp_structure_v3",
    )

    assert tables == []
    assert blocks[0]["blockType"] == "table"


def test_visual_plus_page_text_cannot_satisfy_required_seal_without_crop_ocr() -> None:
    from apps.ocr_service.fusion import fuse_parse_result

    result = fuse_parse_result(
        {
            "fragments": [
                {
                    "pageNo": 1,
                    "text": "压力管道设计许可",
                    "bbox": [20, 20, 160, 40],
                    "confidence": 0.96,
                    "coordinateSystem": "rendered_pixels",
                    "coordinateTransformStatus": "original",
                },
                {
                    "pageNo": 1,
                    "text": "TS1810648-2021",
                    "bbox": [20, 52, 160, 72],
                    "confidence": 0.96,
                    "coordinateSystem": "rendered_pixels",
                    "coordinateTransformStatus": "original",
                },
            ],
            "fields": [],
            "tables": [],
            "seals": [
                {
                    "sealId": "visual_1",
                    "pageNo": 1,
                    "bbox": [0, 0, 220, 120],
                    "visualColor": "red",
                    "visualConfidence": 0.9,
                    "coordinateSystem": "rendered_pixels",
                    "coordinateTransformStatus": "original",
                    "qualityFlags": ["visual_candidate_only", "requires_seal_ocr_text"],
                }
            ],
        },
        profile={
            "requiredFields": [],
            "requiredTables": [],
            "sealRules": {
                "required": True,
                "preferredVisualColors": ["red"],
                "expectedSealTypes": ["design_license_seal"],
            },
        },
    )

    seal = result["seals"][0]
    assert seal["sourceEngine"] == "fragment_seal_text_fusion"
    assert seal["candidateOnly"] is True
    assert seal["canSatisfyRequiredSeal"] is False
    assert "requires_seal_ocr_text" in seal["qualityFlags"]
    assert result["quality"]["sealCompleteness"] == 0.0
    assert "SEAL_TEXT_LOW_CONFIDENCE" in result["quality"]["reasons"]


def test_fragments_for_seal_rejects_missing_coordinate_system() -> None:
    from apps.ocr_service.fusion import fragments_for_seal

    seal = {
        "pageNo": 1,
        "bbox": [0, 0, 200, 120],
        "coordinateSystem": "rendered_pixels",
        "coordinateTransformStatus": "original",
    }
    fragments = [
        {"pageNo": 1, "text": "公司章", "bbox": [20, 20, 80, 40], "confidence": 0.9},
        {
            "pageNo": 1,
            "text": "有效公司章",
            "bbox": [20, 50, 100, 70],
            "confidence": 0.9,
            "coordinateSystem": "rendered_pixels",
            "coordinateTransformStatus": "original",
        },
    ]

    assert [item["text"] for item in fragments_for_seal(seal, fragments)] == ["有效公司章"]
    assert fragments_for_seal({"pageNo": 1, "bbox": [0, 0, 200, 120]}, fragments) == []


def test_overlap_and_table_identity_reject_missing_coordinate_system() -> None:
    from apps.ocr_service.fusion import same_page_overlap, same_table_identity

    assert not same_page_overlap(
        {"pageNo": 1, "bbox": [0, 0, 100, 100]},
        {"pageNo": 1, "bbox": [0, 0, 100, 100], "coordinateSystem": "rendered_pixels"},
    )
    assert not same_table_identity(
        {"pageNo": 1, "tableId": "table_1"},
        {"pageNo": 1, "tableId": "table_1", "coordinateSystem": "rendered_pixels"},
    )


def test_nested_crop_bbox_is_not_double_offset() -> None:
    from apps.ocr_service.service import attach_variant_metadata

    result = {
        "fragments": [],
        "fields": [],
        "tables": [
            {
                "tableId": "t1",
                "bbox": [0, 0, 50, 50],
                "cells": [{"text": "A", "bbox": [1, 2, 11, 12]}],
            }
        ],
        "seals": [],
        "layoutBlocks": [],
    }
    variant = {
        "variantId": "page_2_table_crop_t1",
        "pageNo": 2,
        "source": "remediation_crop",
        "engineScope": "crop",
        "coordinateSystem": "crop_pixels",
        "sourceCoordinateSystem": "rendered_pixels",
        "coordinateTransformStatus": "crop_local",
        "cropOffsetX": 100,
        "cropOffsetY": 200,
        "preprocessChain": ["table", "crop"],
    }

    attach_variant_metadata(result, "pp_structure_v3", variant, document_pages=[{"pageNo": 2}])

    assert result["tables"][0]["bbox"] == [100.0, 200.0, 150.0, 250.0]
    assert result["tables"][0]["cells"][0]["bbox"] == [101.0, 202.0, 111.0, 212.0]


def test_build_crop_variants_rejects_coordinate_transform_unmapped(tmp_path: Path) -> None:
    from PIL import Image

    from apps.ocr_service.service import remediation_variants_for_reasons

    source = tmp_path / "page-1.png"
    Image.new("RGB", (200, 200), (255, 255, 255)).save(source)
    variants = [{"variantId": "page_1_original", "pageNo": 1, "path": str(source)}]
    result = {
        "tables": [
            {
                "tableId": "bad",
                "pageNo": 1,
                "bbox": [20, 20, 120, 120],
                "coordinateSystem": "rendered_pixels",
                "coordinateTransformStatus": "unmapped",
                "qualityFlags": ["coordinate_transform_unmapped"],
            }
        ],
        "seals": [],
    }

    routed = remediation_variants_for_reasons(result, variants, {"TABLE_STRUCTURE_LOW_CONFIDENCE"})

    assert all(item.get("source") != "remediation_crop" for item in routed)


def test_purpose_variant_does_not_route_all_pages_without_page_clue() -> None:
    from apps.ocr_service.routing import route_engine_variants

    variants = [
        {"variantId": "page_1_original", "pageNo": 1, "path": "/tmp/p1.png"},
        {"variantId": "page_1_table_line_enhanced", "pageNo": 1, "path": "/tmp/p1-table.png", "purpose": "table"},
        {"variantId": "page_2_original", "pageNo": 2, "path": "/tmp/p2.png"},
        {"variantId": "page_2_table_line_enhanced", "pageNo": 2, "path": "/tmp/p2-table.png", "purpose": "table"},
    ]
    quality = [
        {"pageNo": 1, "quality": {"hasVisualTableCandidate": True}},
        {"pageNo": 2, "quality": {"hasVisualTableCandidate": False, "hasTableCandidate": False}},
    ]

    routed = route_engine_variants("opencv_table_grid_subprocess", variants, profile={}, page_quality=quality)

    assert [item["pageNo"] for item in routed] == [1]


def test_field_remediation_prioritizes_missing_field_label_crop(tmp_path: Path) -> None:
    from PIL import Image

    from apps.ocr_service.service import remediation_variants_for_reasons

    source = tmp_path / "page-1.png"
    Image.new("RGB", (500, 300), (255, 255, 255)).save(source)
    variants = [{"variantId": "page_1_original", "pageNo": 1, "path": str(source)}]
    fields = [
        {
            "fieldCode": f"existing_{idx}",
            "pageNo": 1,
            "bbox": [10 + idx, 100, 30 + idx, 120],
            "coordinateSystem": "rendered_pixels",
            "coordinateTransformStatus": "original",
        }
        for idx in range(8)
    ]
    result = {
        "quality": {"missingFields": ["report_no"]},
        "fragments": [
            {
                "text": "报告编号",
                "pageNo": 1,
                "bbox": [50, 30, 100, 50],
                "coordinateSystem": "rendered_pixels",
                "coordinateTransformStatus": "original",
                "pageWidth": 500,
                "pageHeight": 300,
            }
        ],
        "fields": fields,
        "tables": [],
        "seals": [],
    }

    routed = remediation_variants_for_reasons(result, variants, {"REQUIRED_FIELD_MISSING"})

    assert routed[0]["purpose"] == "field"
    assert routed[0]["remediationTarget"]["id"] == "report_no"


def test_required_table_missing_generates_page_region_crop(tmp_path: Path) -> None:
    from PIL import Image

    from apps.ocr_service.service import remediation_variants_for_reasons

    source = tmp_path / "page-1.png"
    Image.new("RGB", (400, 300), (255, 255, 255)).save(source)
    variants = [{"variantId": "page_1_original", "pageNo": 1, "path": str(source)}]
    result = {"quality": {"missingTables": ["weld_detection_result_table"]}, "tables": [], "seals": []}

    routed = remediation_variants_for_reasons(
        result,
        variants,
        {"REQUIRED_TABLE_MISSING"},
        profile={"requiredTables": ["weld_detection_result_table"]},
    )

    assert routed[0]["purpose"] == "table"
    assert routed[0]["source"] == "remediation_crop"


def test_seal_not_found_generates_tail_page_signature_region_crop(tmp_path: Path) -> None:
    from PIL import Image

    from apps.ocr_service.service import remediation_variants_for_reasons

    first = tmp_path / "page-1.png"
    last = tmp_path / "page-8.png"
    Image.new("RGB", (400, 300), (255, 255, 255)).save(first)
    Image.new("RGB", (400, 300), (255, 255, 255)).save(last)
    variants = [
        {"variantId": "page_1_original", "pageNo": 1, "path": str(first)},
        {"variantId": "page_8_original", "pageNo": 8, "path": str(last)},
    ]
    result = {"tables": [], "seals": []}

    routed = remediation_variants_for_reasons(
        result,
        variants,
        {"SEAL_NOT_FOUND"},
        profile={"sealRules": {"required": True}},
    )

    seal_crops = [item for item in routed if item.get("purpose") == "seal" and item.get("source") == "remediation_crop"]
    assert {item["pageNo"] for item in seal_crops} == {1, 8}


def test_agentdesign_page_index_zero_based_normalization() -> None:
    from apps.ocr_service.engines import normalize_agentdesign_seal_result, normalize_vl_result

    seals = normalize_agentdesign_seal_result(
        {
            "seals": [
                {
                    "seal_result_id": "seal-1",
                    "page_index": 1,
                    "polygon": [[0, 0], [10, 0], [10, 10], [0, 10]],
                    "fields": {"seal_text": {"value": "测试章", "calibrated_confidence": 0.9}},
                }
            ]
        }
    )
    _, fragments, _, _ = normalize_vl_result({"page_index": 1, "text": "第二页"}, "vl")

    assert seals[0]["pageNo"] == 2
    assert fragments[0]["pageNo"] == 2


def test_piping_regex_field_preserves_source_fragment_page_and_coordinate_system() -> None:
    from apps.ocr_service.service import extract_piping_fields

    result = {
        "fragments": [
            {
                "pageNo": 3,
                "text": "PL8301",
                "bbox": [10, 20, 80, 40],
                "confidence": 0.88,
                "coordinateSystem": "rendered_pixels",
                "coordinateTransformStatus": "original",
                "variantId": "page_3_original",
                "sourceEngine": "paddle_ocr_v6",
            }
        ],
        "fields": [],
        "tables": [],
    }

    extract_piping_fields(result, profile={})

    pipe_field = next(field for field in result["fields"] if field["fieldCode"] == "pipe_no")
    assert pipe_field["pageNo"] == 3
    assert pipe_field["coordinateSystem"] == "rendered_pixels"
    assert pipe_field["coordinateTransformStatus"] == "original"


def test_normalize_raw_seals_preserves_candidate_safety_flags() -> None:
    from apps.ocr_service.fusion import fuse_parse_result
    from apps.ocr_service.service import normalize_raw_seals

    seals = normalize_raw_seals(
        [
            {
                "sealId": "raw_candidate",
                "pageNo": 1,
                "sealType": "quality_seal",
                "sealName": "质检专用章",
                "bbox": [0, 0, 100, 100],
                "coordinateSystem": "rendered_pixels",
                "coordinateTransformStatus": "original",
                "ocrConfidence": 0.96,
                "candidateOnly": True,
                "canSatisfyRequiredSeal": False,
                "sealEvidenceLevel": "text_only",
                "qualityFlags": ["text_only_seal_candidate"],
                "sourceEngine": "external_detector",
            }
        ]
    )

    assert seals[0]["candidateOnly"] is True
    assert seals[0]["canSatisfyRequiredSeal"] is False
    assert seals[0]["sealEvidenceLevel"] == "text_only"
    assert seals[0]["sourceEngine"] == "external_detector"

    fused = fuse_parse_result(
        {"fragments": [], "fields": [], "tables": [], "seals": seals},
        profile={"requiredFields": [], "requiredTables": [], "sealRules": {"required": True}},
    )

    assert fused["quality"]["sealCompleteness"] == 0.0
    assert "SEAL_TEXT_LOW_CONFIDENCE" in fused["quality"]["reasons"]


def test_fields_from_candidate_only_seal_are_not_promoted() -> None:
    from apps.ocr_service.service import fields_from_seals

    fields = fields_from_seals(
        [
            {
                "pageNo": 1,
                "candidateOnly": True,
                "canSatisfyRequiredSeal": False,
                "fields": {"organization_name": {"value": "候选公司", "confidence": 0.99}},
            }
        ]
    )

    assert fields == []


def test_candidate_only_string_false_is_parsed_safely() -> None:
    from apps.ocr_service.fusion import seal_text_is_readable
    from apps.ocr_service.service import fields_from_seals, normalize_raw_seals

    seals = normalize_raw_seals(
        [
            {
                "sealId": "s1",
                "page_no": 3,
                "sealName": "质量专用章",
                "bbox": [0, 0, 100, 100],
                "coordinateSystem": "rendered_pixels",
                "coordinateTransformStatus": "original",
                "ocrConfidence": 0.95,
                "candidateOnly": "false",
                "canSatisfyRequiredSeal": "false",
                "fields": {"organization_name": {"value": "候选公司", "confidence": 0.9}},
            }
        ]
    )

    assert seals[0]["pageNo"] == 3
    assert seals[0]["candidateOnly"] is False
    assert seals[0]["canSatisfyRequiredSeal"] is False
    assert seal_text_is_readable(seals[0]) is False
    assert fields_from_seals(seals) == []


def test_normalized_raw_seal_none_metadata_gets_variant_metadata() -> None:
    from apps.ocr_service.fusion import has_evidence_box
    from apps.ocr_service.service import attach_variant_metadata, normalize_raw_seals

    result = {
        "fragments": [],
        "fields": [],
        "tables": [],
        "seals": normalize_raw_seals(
            [
                {
                    "sealId": "real_seal",
                    "page_no": 2,
                    "sealName": "质量专用章",
                    "bbox": [10, 10, 80, 80],
                    "ocrConfidence": 0.9,
                    "canSatisfyRequiredSeal": True,
                }
            ]
        ),
        "layoutBlocks": [],
    }

    attach_variant_metadata(
        result,
        "visual_seal_candidate_subprocess",
        {"variantId": "page_2_original", "pageNo": 2, "coordinateSystem": "rendered_pixels", "coordinateTransformStatus": "original"},
        document_pages=[{"pageNo": 2}],
    )

    seal = result["seals"][0]
    assert seal["sourceEngine"] == "visual_seal_candidate_subprocess"
    assert seal["coordinateSystem"] == "rendered_pixels"
    assert seal["coordinateTransformStatus"] == "original"
    assert has_evidence_box(seal) is True


def test_normalized_raw_field_none_source_engine_gets_engine_metadata() -> None:
    from apps.ocr_service.service import attach_variant_metadata, normalize_raw_fields

    result = {
        "fragments": [],
        "fields": normalize_raw_fields(
            [
                {
                    "fieldName": "报告编号",
                    "fieldValue": "RT-2026-001",
                    "page_no": 4,
                    "bbox": [10, 10, 100, 30],
                }
            ]
        ),
        "tables": [],
        "seals": [],
        "layoutBlocks": [],
    }

    attach_variant_metadata(
        result,
        "paddle_ocr_v6",
        {"variantId": "page_4_original", "pageNo": 4, "coordinateSystem": "rendered_pixels", "coordinateTransformStatus": "original"},
        document_pages=[{"pageNo": 4}],
    )

    field = result["fields"][0]
    assert field["pageNo"] == 4
    assert field["sourceEngine"] == "paddle_ocr_v6"
    assert field["coordinateSystem"] == "rendered_pixels"


def test_field_crop_ocr_creates_field_candidate_from_remediation_target() -> None:
    from apps.ocr_service.fusion import fuse_parse_result
    from apps.ocr_service.service import attach_variant_metadata

    result = {
        "fragments": [
            {"text": "报告编号", "bbox": [0, 0, 50, 20], "confidence": 0.7},
            {"text": "R-2026-001", "bbox": [60, 0, 150, 20], "confidence": 0.95},
        ],
        "fields": [],
        "tables": [],
        "seals": [],
        "layoutBlocks": [],
    }
    variant = {
        "variantId": "page_1_field_crop_report_no_abc12345",
        "pageNo": 1,
        "source": "remediation_crop",
        "engineScope": "crop",
        "coordinateSystem": "crop_pixels",
        "sourceCoordinateSystem": "rendered_pixels",
        "coordinateTransformStatus": "crop_local",
        "cropOffsetX": 100,
        "cropOffsetY": 200,
        "cropSourceBbox": [100, 200, 300, 260],
        "remediationTarget": {"type": "field", "fieldCode": "report_no", "fieldName": "报告编号"},
    }

    attach_variant_metadata(result, "paddle_ocr_v6", variant, document_pages=[{"pageNo": 1}])

    field = result["fields"][0]
    assert field["fieldCode"] == "report_no"
    assert field["fieldValue"] == "R-2026-001"
    assert field["bbox"] == [160.0, 200.0, 250.0, 220.0]
    assert field["coordinateSystem"] == "rendered_pixels"
    assert field["coordinateTransformStatus"] == "mapped_from_crop"

    fused = fuse_parse_result(
        result,
        profile={"requiredFields": ["report_no"], "requiredTables": [], "sealRules": {"required": False}},
    )
    assert "REQUIRED_FIELD_MISSING" not in fused["quality"]["reasons"]


def test_low_confidence_field_crop_is_candidate_only_and_does_not_clear_missing() -> None:
    from apps.ocr_service.fusion import fuse_parse_result
    from apps.ocr_service.service import attach_variant_metadata

    result = {
        "fragments": [{"text": "项目", "bbox": [0, 0, 40, 20], "confidence": 0.42}],
        "fields": [],
        "tables": [],
        "seals": [],
        "layoutBlocks": [],
    }
    variant = {
        "variantId": "page_1_field_crop_project_name_low",
        "pageNo": 1,
        "source": "remediation_crop",
        "engineScope": "crop",
        "coordinateSystem": "crop_pixels",
        "coordinateTransformStatus": "crop_local",
        "cropOffsetX": 100,
        "cropOffsetY": 200,
        "cropSourceBbox": [100, 200, 220, 250],
        "remediationTarget": {"type": "field", "fieldCode": "project_name", "reason": "REQUIRED_FIELD_MISSING", "reasons": ["REQUIRED_FIELD_MISSING"]},
    }

    attach_variant_metadata(result, "paddle_ocr_v6", variant, document_pages=[{"pageNo": 1}])

    field = result["fields"][0]
    assert field["remediationCandidateOnly"] is True
    assert "field_crop_low_confidence" in field["qualityFlags"]

    fused = fuse_parse_result(
        result,
        profile={"requiredFields": ["project_name"], "requiredTables": [], "sealRules": {"required": False}},
    )
    assert "REQUIRED_FIELD_MISSING" in fused["quality"]["reasons"]


def test_seal_crop_ocr_creates_formal_seal_candidate() -> None:
    from apps.ocr_service.fusion import fuse_parse_result, seal_text_is_readable
    from apps.ocr_service.service import attach_variant_metadata

    result = {
        "fragments": [
            {"text": "广东星燃石化设计院有限公司", "bbox": [0, 0, 150, 24], "confidence": 0.93},
            {"text": "压力管道设计许可章", "bbox": [0, 30, 150, 54], "confidence": 0.91},
        ],
        "fields": [],
        "tables": [],
        "seals": [],
        "layoutBlocks": [],
    }
    variant = {
        "variantId": "page_3_seal_crop_missing_seal_abc12345",
        "pageNo": 3,
        "purpose": "seal",
        "source": "remediation_crop",
        "engineScope": "crop",
        "coordinateSystem": "crop_pixels",
        "sourceCoordinateSystem": "rendered_pixels",
        "coordinateTransformStatus": "crop_local",
        "cropOffsetX": 300,
        "cropOffsetY": 500,
        "cropSourceBbox": [300, 500, 520, 640],
        "remediationTarget": {
            "type": "seal",
            "id": "visual_seal",
            "reason": "SEAL_TEXT_LOW_CONFIDENCE",
            "sourceKind": "visual_seal_candidate",
            "sourceVisualConfidence": 0.86,
            "sourceQualityFlags": ["visual_candidate_only"],
        },
    }

    attach_variant_metadata(result, "paddle_ocr_v6", variant, document_pages=[{"pageNo": 3}])

    seal = result["seals"][0]
    assert seal["sealEvidenceLevel"] == "visual_plus_seal_crop_ocr"
    assert seal["candidateOnly"] is False
    assert seal["canSatisfyRequiredSeal"] is True
    assert seal["bbox"] == [300.0, 500.0, 450.0, 554.0]
    assert seal_text_is_readable(seal) is True

    fused = fuse_parse_result(
        result,
        profile={"requiredFields": [], "requiredTables": [], "sealRules": {"required": True}},
    )
    assert fused["quality"]["sealCompleteness"] == 1.0
    assert "SEAL_NOT_FOUND" not in fused["quality"]["reasons"]
    assert "SEAL_TEXT_LOW_CONFIDENCE" not in fused["quality"]["reasons"]


def test_generic_seal_region_crop_ocr_is_candidate_only() -> None:
    from apps.ocr_service.fusion import fuse_parse_result, seal_text_is_readable
    from apps.ocr_service.service import attach_variant_metadata

    result = {
        "fragments": [{"text": "广东星燃石化设计院有限公司 2026年6月1日", "bbox": [0, 0, 180, 30], "confidence": 0.96}],
        "fields": [],
        "tables": [],
        "seals": [],
        "layoutBlocks": [],
    }
    variant = {
        "variantId": "page_9_seal_crop_missing_seal_abcd1234",
        "pageNo": 9,
        "purpose": "seal",
        "source": "remediation_crop",
        "engineScope": "crop",
        "coordinateSystem": "crop_pixels",
        "sourceCoordinateSystem": "rendered_pixels",
        "coordinateTransformStatus": "crop_local",
        "cropOffsetX": 500,
        "cropOffsetY": 700,
        "cropSourceBbox": [500, 700, 760, 820],
        "remediationTarget": {
            "type": "seal",
            "id": "missing_seal",
            "reason": "SEAL_NOT_FOUND",
            "sourceKind": "generic_signature_region",
            "sourceVisualConfidence": 0.0,
            "sourceQualityFlags": ["generic_seal_region_crop"],
        },
    }

    attach_variant_metadata(result, "paddle_ocr_v6", variant, document_pages=[{"pageNo": 9}])

    seal = result["seals"][0]
    assert seal["sealEvidenceLevel"] == "generic_region_seal_crop_ocr"
    assert seal["candidateOnly"] is True
    assert seal["canSatisfyRequiredSeal"] is False
    assert "seal_crop_ocr_without_visual_evidence" in seal["qualityFlags"]
    assert seal_text_is_readable(seal) is False

    fused = fuse_parse_result(result, profile={"requiredFields": [], "requiredTables": [], "sealRules": {"required": True}})
    assert fused["quality"]["sealCompleteness"] == 0.0
    assert "SEAL_TEXT_LOW_CONFIDENCE" in fused["quality"]["reasons"]


def test_seal_not_found_routes_tail_crop_to_visual_seal_candidate_engine(tmp_path: Path) -> None:
    from PIL import Image

    from apps.ocr_service.routing import route_engine_variants
    from apps.ocr_service.service import remediation_variants_for_reasons

    first = tmp_path / "page-1.png"
    last = tmp_path / "page-9.png"
    Image.new("RGB", (400, 300), (255, 255, 255)).save(first)
    Image.new("RGB", (400, 300), (255, 255, 255)).save(last)
    variants = [
        {"variantId": "page_1_original", "pageNo": 1, "path": str(first)},
        {"variantId": "page_9_original", "pageNo": 9, "path": str(last)},
    ]
    remediation_variants = remediation_variants_for_reasons(
        {"tables": [], "seals": []},
        variants,
        {"SEAL_NOT_FOUND"},
        profile={"sealRules": {"required": True}},
    )

    routed = route_engine_variants(
        "visual_seal_candidate_subprocess",
        remediation_variants,
        profile={"sealRules": {"required": True}, "preprocessPolicy": {"seal": {"enableColorCandidate": False}}},
        page_quality=[],
        options={"runRemediation": True},
    )

    assert routed
    assert all(item["purpose"] == "seal" for item in routed)
    assert {item["pageNo"] for item in routed} == {1, 9}

    text_routed = route_engine_variants(
        "paddle_ocr_v6",
        remediation_variants,
        profile={"sealRules": {"required": True}},
        page_quality=[],
        options={"runRemediation": True},
    )

    assert text_routed
    assert all(item["purpose"] == "seal" for item in text_routed)


def test_seal_not_found_targets_middle_visual_seal_page(tmp_path: Path) -> None:
    from PIL import Image

    from apps.ocr_service.service import remediation_variants_for_reasons

    variants = []
    for page_no in [1, 5, 9]:
        source = tmp_path / f"page-{page_no}.png"
        Image.new("RGB", (400, 300), (255, 255, 255)).save(source)
        variants.append({"variantId": f"page_{page_no}_original", "pageNo": page_no, "path": str(source)})
    variants.append({"variantId": "page_5_seal_color_mask", "pageNo": 5, "path": str(tmp_path / "page-5.png"), "purpose": "seal"})

    remediation_variants = remediation_variants_for_reasons(
        {"tables": [], "seals": [], "fragments": []},
        variants,
        {"SEAL_NOT_FOUND"},
        profile={"sealRules": {"required": True}},
    )

    seal_crops = [item for item in remediation_variants if item.get("purpose") == "seal" and item.get("source") == "remediation_crop"]
    assert seal_crops[0]["pageNo"] == 5
    assert any(item["pageNo"] == 5 and "visual_" in item["cropSourceTargetId"] for item in seal_crops)
    visual_crops = [item for item in seal_crops if item["pageNo"] == 5 and "visual_" in item["cropSourceTargetId"]]
    assert visual_crops
    assert all((item.get("remediationTarget") or {}).get("sourceKind") == "visual_seal_candidate" for item in visual_crops)
    assert all(float((item.get("remediationTarget") or {}).get("sourceVisualConfidence") or 0) > 0 for item in visual_crops)
    assert all("visual_candidate_only" in set((item.get("remediationTarget") or {}).get("sourceQualityFlags") or []) for item in visual_crops)


def test_missing_table_crop_targets_table_clue_pages_not_only_first_three(tmp_path: Path) -> None:
    from PIL import Image

    from apps.ocr_service.service import remediation_variants_for_reasons

    variants = []
    for page_no in range(1, 6):
        source = tmp_path / f"page-{page_no}.png"
        Image.new("RGB", (400, 300), (255, 255, 255)).save(source)
        variants.append({"variantId": f"page_{page_no}_original", "pageNo": page_no, "path": str(source)})
    result = {
        "fragments": [
            {
                "pageNo": 5,
                "text": "焊口编号 检测方法 评定级别 检测比例",
                "bbox": [10, 10, 300, 30],
                "coordinateSystem": "rendered_pixels",
            }
        ],
        "tables": [],
        "seals": [],
    }

    routed = remediation_variants_for_reasons(
        result,
        variants,
        {"REQUIRED_TABLE_MISSING"},
        profile={"requiredTables": ["weld_detection_result_table"]},
    )

    table_crops = [item for item in routed if item.get("purpose") == "table" and item.get("source") == "remediation_crop"]
    assert table_crops[0]["pageNo"] == 5


def test_crop_variant_id_unique_for_same_field_multiple_bboxes(tmp_path: Path) -> None:
    from PIL import Image

    from apps.ocr_service.service import remediation_variants_for_reasons

    source = tmp_path / "page-1.png"
    Image.new("RGB", (400, 300), (255, 255, 255)).save(source)
    variants = [{"variantId": "page_1_original", "pageNo": 1, "path": str(source)}]
    result = {
        "quality": {"lowConfidenceFields": [{"fieldCode": "report_no"}]},
        "fields": [
            {
                "fieldCode": "report_no",
                "pageNo": 1,
                "bbox": [10, 10, 80, 30],
                "coordinateSystem": "rendered_pixels",
                "coordinateTransformStatus": "original",
            },
            {
                "fieldCode": "report_no",
                "pageNo": 1,
                "bbox": [100, 10, 180, 30],
                "coordinateSystem": "rendered_pixels",
                "coordinateTransformStatus": "original",
            },
        ],
        "tables": [],
        "seals": [],
    }

    routed = remediation_variants_for_reasons(result, variants, {"FIELD_LOW_CONFIDENCE"})
    crop_ids = [item["variantId"] for item in routed if item.get("source") == "remediation_crop"]

    assert len(crop_ids) == 2
    assert len(set(crop_ids)) == 2


def test_normalize_nested_coordinates_does_not_mutate_coordinate_transform_dict() -> None:
    from apps.ocr_service.service import attach_variant_metadata

    result = {
        "fragments": [],
        "fields": [],
        "tables": [{"tableId": "t1", "bbox": [0, 0, 20, 20], "cells": [{"text": "A", "bbox": [1, 1, 5, 5]}]}],
        "seals": [],
        "layoutBlocks": [],
    }
    variant = {
        "variantId": "page_1_table_crop_t1_abc12345",
        "pageNo": 1,
        "source": "remediation_crop",
        "engineScope": "crop",
        "coordinateSystem": "crop_pixels",
        "coordinateTransformStatus": "crop_local",
        "cropOffsetX": 100,
        "cropOffsetY": 200,
    }

    attach_variant_metadata(result, "pp_structure_v3", variant, document_pages=[{"pageNo": 1}])

    transform = result["tables"][0]["cells"][0]["coordinateTransform"]
    assert transform == {"offsetX": 100.0, "offsetY": 200.0}
    assert "pageNo" not in transform
    assert "sourceEngine" not in transform


def test_crop_mapping_accepts_paddle_dt_poly_bbox() -> None:
    from apps.ocr_service.service import attach_variant_metadata

    result = {
        "fragments": [
            {
                "text": "报告编号",
                "bbox": [[10, 20], [50, 20], [50, 60], [10, 60]],
                "confidence": 0.9,
            }
        ],
        "fields": [],
        "tables": [],
        "seals": [],
        "layoutBlocks": [],
    }
    variant = {
        "variantId": "page_1_field_crop_report_no_poly",
        "pageNo": 1,
        "source": "remediation_crop",
        "engineScope": "crop",
        "coordinateSystem": "crop_pixels",
        "coordinateTransformStatus": "crop_local",
        "cropOffsetX": 100,
        "cropOffsetY": 200,
    }

    attach_variant_metadata(result, "paddle_ocr_v6", variant, document_pages=[{"pageNo": 1}])

    fragment = result["fragments"][0]
    assert fragment["polygon"] == [[110.0, 220.0], [150.0, 220.0], [150.0, 260.0], [110.0, 260.0]]
    assert fragment["bbox"] == [110.0, 220.0, 150.0, 260.0]
    assert fragment["coordinateSystem"] == "rendered_pixels"


def test_required_table_score_uses_cell_evidence_coverage() -> None:
    from apps.ocr_service.fusion import table_cell_evidence_score, table_score

    base_table = {
        "tableId": "t1",
        "pageNo": 1,
        "bbox": [0, 0, 100, 100],
        "coordinateSystem": "rendered_pixels",
        "coordinateTransformStatus": "original",
        "structureConfidence": 0.8,
        "cells": [{"text": "报告编号", "bbox": [0, 0, 10, 10]}],
    }
    evidenced_table = {
        **base_table,
        "cells": [
            {
                "text": "报告编号",
                "pageNo": 1,
                "bbox": [0, 0, 10, 10],
                "coordinateSystem": "rendered_pixels",
                "coordinateTransformStatus": "original",
            }
        ],
    }

    assert table_cell_evidence_score(base_table) == 0.0
    assert table_cell_evidence_score(evidenced_table) == 1.0
    assert table_score(evidenced_table) > table_score(base_table)


def test_required_table_auto_pass_requires_cell_evidence_coverage() -> None:
    from apps.ocr_service.fusion import fuse_parse_result

    result = {
        "fragments": [],
        "fields": [],
        "seals": [],
        "tables": [
            {
                "tableId": "weld_detection_result_table",
                "pageNo": 1,
                "bbox": [0, 0, 200, 120],
                "coordinateSystem": "rendered_pixels",
                "coordinateTransformStatus": "original",
                "structureConfidence": 0.9,
                "cells": [{"text": "焊口编号", "bbox": [0, 0, 60, 20]}],
            }
        ],
    }

    fused = fuse_parse_result(
        result,
        profile={"requiredFields": [], "requiredTables": ["weld_detection_result_table"], "sealRules": {"required": False}},
    )

    assert fused["quality"]["missingTables"] == []
    assert "TABLE_CELL_EVIDENCE_LOW" in fused["quality"]["reasons"]
    assert fused["quality"]["lowTableCellEvidenceTables"][0]["tableCode"] == "weld_detection_result_table"
    assert fused["quality"]["tableCompleteness"] == 1.0
    assert fused["quality"]["tableAutoUsableCompleteness"] == 0.0


def test_table_cell_evidence_low_triggers_remediation(tmp_path: Path) -> None:
    from PIL import Image

    from apps.ocr_service.routing import route_engine_variants
    from apps.ocr_service.service import remediation_variants_for_reasons
    from libs.ocr.profiles import DEFAULT_VLM_FALLBACK_REASONS

    assert "TABLE_CELL_EVIDENCE_LOW" in DEFAULT_VLM_FALLBACK_REASONS

    source = tmp_path / "page-1.png"
    Image.new("RGB", (400, 300), (255, 255, 255)).save(source)
    variants = [{"variantId": "page_1_original", "pageNo": 1, "path": str(source)}]
    result = {
        "tables": [
            {
                "tableId": "weld_detection_result_table",
                "pageNo": 1,
                "bbox": [10, 10, 300, 200],
                "coordinateSystem": "rendered_pixels",
                "coordinateTransformStatus": "original",
                "cells": [{"text": "焊口编号", "bbox": [20, 20, 80, 40]}],
            }
        ],
        "fields": [],
        "seals": [],
    }

    remediation_variants = remediation_variants_for_reasons(
        result,
        variants,
        {"TABLE_CELL_EVIDENCE_LOW"},
        profile={"requiredTables": ["weld_detection_result_table"]},
    )
    table_crops = [item for item in remediation_variants if item.get("purpose") == "table" and item.get("source") == "remediation_crop"]

    assert table_crops
    routed = route_engine_variants(
        "pp_structure_v3",
        remediation_variants,
        profile={"requiredTables": ["weld_detection_result_table"]},
        page_quality=[],
        options={"runRemediation": True},
    )
    assert routed == table_crops[:3]


def test_remediation_variants_built_once_per_pass(monkeypatch, tmp_path: Path) -> None:
    from apps.ocr_service.service import OcrService

    class FakeEngine:
        version = "test"

        def __init__(self, name: str) -> None:
            self.name = name

        def available(self):
            return True

        def status(self):
            return {"engine": self.name, "version": self.version, "available": True}

        def parse(self, source_path, *, file_name=None, profile=None, variant=None):
            return {"ok": True, "fragments": [], "fields": [], "tables": [], "seals": []}

    source = tmp_path / "page-1.png"
    source.write_bytes(b"fake-image")
    variants = [{"variantId": "page_1_original", "pageNo": 1, "path": str(source), "purpose": "general", "source": "original"}]
    calls = {"count": 0}

    def fake_remediation_variants(result, base_variants, reasons, profile=None):
        calls["count"] += 1
        return base_variants

    monkeypatch.setattr("apps.ocr_service.service.remediation_variants_for_reasons", fake_remediation_variants)

    service = OcrService()
    service.engines = [FakeEngine("paddle_ocr_v6"), FakeEngine("paddleocr_vl_1_6")]
    service.run_remediation_pass(
        {"status": "success", "quality": {"reasons": ["REQUIRED_FIELD_MISSING"]}, "fragments": [], "fields": [], "tables": [], "seals": []},
        source_path=source,
        storage_key=str(source),
        file_name="page-1.png",
        profile={"requiredFields": ["report_no"], "requiredTables": [], "sealRules": {"required": False}},
        variants=variants,
        page_quality=[{"pageNo": 1, "quality": {}}],
        model_manifest={"modelDirs": {}},
        document_version_id=None,
        business_pack_id=None,
        options={},
        document_pages=[{"pageNo": 1}],
    )

    assert calls["count"] == 1


def test_field_value_conflict_candidates_include_spatial_metadata() -> None:
    from apps.ocr_service.fusion import fuse_parse_result

    fused = fuse_parse_result(
        {
            "fragments": [],
            "tables": [],
            "seals": [],
            "fields": [
                {
                    "fieldCode": "report_no",
                    "fieldName": "报告编号",
                    "fieldValue": "RT-2026-001",
                    "confidence": 0.92,
                    "pageNo": 1,
                    "bbox": [10, 10, 100, 30],
                    "coordinateSystem": "rendered_pixels",
                    "coordinateTransformStatus": "original",
                    "sourceEngine": "paddle_ocr_v6",
                    "variantId": "page_1_original",
                },
                {
                    "fieldCode": "report_no",
                    "fieldName": "报告编号",
                    "fieldValue": "RT-2026-007",
                    "confidence": 0.86,
                    "pageNo": 2,
                    "bbox": [20, 20, 120, 42],
                    "coordinateSystem": "rendered_pixels",
                    "coordinateTransformStatus": "mapped_from_crop",
                    "sourceEngine": "paddle_ocr_subprocess",
                    "variantId": "page_2_field_crop_report_no_abcd",
                },
            ],
        },
        profile={"requiredFields": ["report_no"], "requiredTables": [], "sealRules": {"required": False}},
    )

    conflict = fused["fields"][0]["conflictingValues"][0]
    assert conflict["pageNo"] in {1, 2}
    assert conflict["coordinateSystem"] == "rendered_pixels"
    assert conflict["bbox"]


def test_run_all_variants_does_not_bypass_disabled_seal_policy() -> None:
    from apps.ocr_service.routing import route_engine_variants

    variants = [{"variantId": "page_1_original", "pageNo": 1, "path": "/tmp/page-1.png"}]

    routed = route_engine_variants(
        "visual_seal_candidate_subprocess",
        variants,
        profile={"sealRules": {"required": False}, "preprocessPolicy": {"seal": {"enableColorCandidate": False}}},
        page_quality=[],
        options={"runAllVariants": True},
    )

    assert routed == []

    disabled_paddlex = route_engine_variants(
        "paddlex_seal_recognition",
        variants,
        profile={"sealRules": {"required": True}, "preprocessPolicy": {"seal": {"enablePaddlexSeal": False}}},
        page_quality=[],
        options={"runAllVariants": True},
    )

    assert disabled_paddlex == []

    disabled_string_paddlex = route_engine_variants(
        "paddlex_seal_recognition",
        variants,
        profile={"sealRules": {"required": True}, "preprocessPolicy": {"seal": {"enablePaddlexSeal": "false"}}},
        page_quality=[],
        options={"runAllVariants": True},
    )

    assert disabled_string_paddlex == []


def test_string_false_required_seal_is_false_across_ocr_policy_paths(monkeypatch) -> None:
    from apps.ocr_service.engines import seal_max_pages
    from apps.ocr_service.fusion import fuse_parse_result
    from apps.ocr_service.pages import profile_requires_tail_pages
    from apps.ocr_service.quality import apply_business_need_flags, unreadable_quality
    from apps.ocr_service.routing import route_engine_variants
    from apps.ocr_service.service import missing_seal_remediation_targets

    profile = {"requiredFields": [], "requiredTables": [], "sealRules": {"required": "false"}}
    variants = [
        {
            "variantId": "page_1_original",
            "pageNo": 1,
            "path": "/tmp/page-1.png",
            "width": 1000,
            "height": 1000,
            "preprocessChain": ["original"],
        }
    ]

    assert profile_requires_tail_pages(profile) is False
    assert route_engine_variants("paddlex_seal_recognition", variants, profile=profile, page_quality=[]) == []
    assert missing_seal_remediation_targets({"quality": {"reasons": []}, "seals": []}, variants, profile) == []

    quality = unreadable_quality(Path("/tmp/missing.png"), profile=profile, page_no=1)["quality"]
    assert quality["requiresSealSearch"] is False
    quality = {"hasSealCandidate": False}
    apply_business_need_flags(quality, profile)
    assert quality["requiresSealSearch"] is False

    fused = fuse_parse_result({"fragments": [], "fields": [], "tables": [], "seals": []}, profile=profile)
    assert "SEAL_NOT_FOUND" not in set(fused["quality"].get("reasons") or [])

    monkeypatch.delenv("AICHECK_AGENTDESIGN_SEAL_MAX_PAGES", raising=False)
    assert seal_max_pages(profile) == 1


def test_pymupdf_bbox_uses_render_matrix_transform() -> None:
    from apps.ocr_service.service import attach_variant_metadata

    result = {
        "metadata": {"documentLevel": True},
        "fragments": [{"pageNo": 1, "text": "旋转页", "bbox": [1.0, 2.0, 3.0, 4.0]}],
        "fields": [],
        "tables": [],
        "seals": [],
        "layoutBlocks": [],
    }

    attach_variant_metadata(
        result,
        "pymupdf_text_layer",
        {"variantId": "document_original", "engineScope": "document"},
        document_pages=[
            {
                "pageNo": 1,
                "renderScaleX": 2.0,
                "renderScaleY": 2.0,
                "pdfRenderMatrix": [2, 0, 0, 2, 0, 0],
                "pdfTextToPixelMatrix": [0, 2, -2, 0, 100, 0],
                "pdfPixmapX": -100,
                "pdfPixmapY": 0,
            }
        ],
    )

    fragment = result["fragments"][0]
    assert fragment["bbox"] == [192.0, 2.0, 196.0, 6.0]
    assert fragment["coordinateTransform"] == {
        "matrix": [0.0, 2.0, -2.0, 0.0, 100.0, 0.0],
        "pixmapX": -100.0,
        "pixmapY": 0.0,
    }


def test_pymupdf_bbox_maps_all_rotation_matrices_to_rendered_pixels() -> None:
    from apps.ocr_service.service import attach_variant_metadata

    cases = [
        ("0", [2, 0, 0, 2, 0, 0], 0, 0, [2.0, 4.0, 6.0, 8.0]),
        ("90", [0, 2, -2, 0, 100, 0], -100, 0, [192.0, 2.0, 196.0, 6.0]),
        ("180", [-2, 0, 0, -2, 100, 120], 0, 0, [94.0, 112.0, 98.0, 116.0]),
        ("270", [0, -2, 2, 0, 0, 120], 0, 0, [4.0, 114.0, 8.0, 118.0]),
    ]

    for rotation, matrix, pixmap_x, pixmap_y, expected_bbox in cases:
        result = {
            "metadata": {"documentLevel": True},
            "fragments": [{"pageNo": 1, "text": f"旋转{rotation}", "bbox": [1.0, 2.0, 3.0, 4.0]}],
            "fields": [],
            "tables": [],
            "seals": [],
            "layoutBlocks": [],
        }

        attach_variant_metadata(
            result,
            "pymupdf_text_layer",
            {"variantId": "document_original", "engineScope": "document"},
            document_pages=[
                {
                    "pageNo": 1,
                    "renderScaleX": 2.0,
                    "renderScaleY": 2.0,
                    "pdfTextToPixelMatrix": matrix,
                    "pdfPixmapX": pixmap_x,
                    "pdfPixmapY": pixmap_y,
                }
            ],
        )

        fragment = result["fragments"][0]
        assert fragment["bbox"] == expected_bbox
        assert fragment["coordinateSystem"] == "rendered_pixels"
        assert fragment["sourceCoordinateSystem"] == "pdf_points"
        assert fragment["coordinateTransformStatus"] == "mapped_from_pdf_points"


def test_observability_metrics_cover_profile_remediation_cache_and_rotation() -> None:
    from apps.ocr_service.service import build_observability_metrics

    before = {
        "quality": {"reasons": ["FIELD_LOW_CONFIDENCE", "SEAL_NOT_FOUND", "TABLE_CELL_EVIDENCE_LOW"]},
        "tables": [
            {
                "tableId": "t-before",
                "cells": [{"text": "焊口编号"}, {"text": "W-001"}],
            }
        ],
    }
    result = {
        "profileId": "engineering_table_photo",
        "documentType": "piping_characteristic_list",
        "quality": {"reasons": ["LOW_CONFIDENCE_FIELD_REVIEW"]},
        "pages": [{"pageNo": 1, "rotation": 90}],
        "fragments": [
            {
                "pageNo": 1,
                "text": "旋转文本层",
                "bbox": [10, 20, 90, 40],
                "coordinateSystem": "rendered_pixels",
                "sourceCoordinateSystem": "pdf_points",
                "coordinateTransformStatus": "mapped_from_pdf_points",
                "sourceEngine": "pymupdf_text_layer",
            }
        ],
        "fields": [
            {
                "fieldCode": "report_no",
                "fieldValue": "RT-001",
                "extractionMethod": "remediation_field_crop_ocr",
                "remediationCandidateOnly": False,
            }
        ],
        "tables": [
            {
                "tableId": "t-after",
                "variantId": "page_1_table_crop_t-after_abcd1234",
                "cells": [
                    {
                        "text": "焊口编号",
                        "pageNo": 1,
                        "bbox": [10, 10, 60, 30],
                        "coordinateSystem": "rendered_pixels",
                        "coordinateTransformStatus": "mapped_from_crop",
                    },
                    {
                        "text": "W-001",
                        "pageNo": 1,
                        "bbox": [60, 10, 110, 30],
                        "coordinateSystem": "rendered_pixels",
                        "coordinateTransformStatus": "mapped_from_crop",
                    },
                ],
            }
        ],
        "seals": [
            {
                "sealId": "seal-1",
                "sealEvidenceLevel": "visual_plus_seal_crop_ocr",
                "canSatisfyRequiredSeal": True,
            },
            {
                "sealId": "seal-2",
                "sealEvidenceLevel": "generic_region_seal_crop_ocr",
                "candidateOnly": True,
                "canSatisfyRequiredSeal": False,
            },
        ],
        "engineRuns": [
            {"durationMs": 10, "engineCacheHit": True, "variantCacheHit": True},
            {"durationMs": 30, "engineCacheHit": False, "variantCacheHit": False},
        ],
        "remediationRuns": [
            {"durationMs": 50, "engineCacheHit": True, "variantId": "page_1_seal_crop_missing_seal_abcd1234"},
        ],
        "imageVariants": [{"cacheHit": True}, {"cacheHit": False}],
    }

    metrics = build_observability_metrics(result, before_remediation=before)

    assert metrics["profileId"] == "engineering_table_photo"
    assert metrics["fieldCropRemediationTriggered"] is True
    assert metrics["fieldCropRemediationSucceeded"] == 1
    assert metrics["fieldCropFalseFillRate"] is None
    assert metrics["sealNotFoundTriggered"] is True
    assert metrics["sealCropGenerated"] == 1
    assert metrics["visualSealCropOcrSucceeded"] == 1
    assert metrics["genericSealCropCandidateOnlyRate"] == 1.0
    assert metrics["requiredSealFalsePassRate"] == 0.0
    assert metrics["tableCellEvidenceLowTriggered"] is True
    assert metrics["tableCropRemediationSucceeded"] == 1
    assert metrics["tableCellEvidenceCoverageBefore"] == 0.0
    assert metrics["tableCellEvidenceCoverageAfter"] == 1.0
    assert metrics["pymupdfTextLayerBBoxValidRate"] == 1.0
    assert metrics["rotatedPdfDetectedCount"] == 1
    assert metrics["rotatedPdfOverlayErrorRate"] == 0.0
    assert metrics["cacheHitRate"] == 0.666667
    assert metrics["pageRenderCacheHitRate"] == 0.5
    assert metrics["remediationPassLatency"] == 50
    assert metrics["P95Latency"] == 50
