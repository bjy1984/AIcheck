from apps.ocr_service.fusion import fragment_seal_candidates_from_text, fuse_parse_result
from apps.ocr_service.service import (
    apply_business_pdf_deep_scan_default_options,
    apply_fast_first_default_options,
    apply_profile_postprocessing,
    attach_variant_metadata,
    detect_engineering_drawing_list_profile,
    detect_engineering_drawing_profile,
    detect_scan_business_document_profile,
    extract_engineering_drawing_common_fields,
    extract_engineering_drawing_list_fields,
    extract_ndt_rt_report_fields,
    extract_piping_requirement_fields,
    extract_qualification_certificate_fields,
    find_project_fragment,
    should_defer_heavy_engine,
)
from libs.ocr.profiles import profile_for


def test_engineering_photo_profile_enables_fast_first_defaults() -> None:
    profile = profile_for("piping_characteristic_list_v1")

    options = apply_fast_first_default_options({}, profile)

    assert options["fastFirstMode"] is True
    assert options["quickMode"] is True
    assert options["disableRemediation"] is True
    assert options["enableFallback"] is False
    assert options["maxPages"] == 1
    assert options["variants"] == ["original", "gray_clahe", "seal_color_mask"]


def test_business_pdf_profile_enables_deep_scan_defaults_without_touching_standard_text_layer() -> None:
    quality_profile = profile_for("quality_certificate_v1")

    options = apply_business_pdf_deep_scan_default_options({}, quality_profile, suffix=".pdf")

    assert options["fullOcr"] is True
    assert options["deepScanPdf"] is True
    assert options["disablePdfTextLayerFastPath"] is True
    assert options["forceTableOcr"] is True
    assert options["forceSealOcr"] is True
    assert options["pageCoverageMode"] == "deep_scan"
    assert options["maxPages"] == 6

    standard_options = apply_business_pdf_deep_scan_default_options(
        {"standardIndexingStrategy": "auto_text_layer_then_remote_ocr", "preferTextLayer": True},
        quality_profile,
        suffix=".pdf",
    )
    assert "deepScanPdf" not in standard_options
    assert "disablePdfTextLayerFastPath" not in standard_options


def test_business_pdf_deep_scan_defaults_respect_explicit_text_layer_only() -> None:
    profile = profile_for("quality_certificate_v1")

    options = apply_business_pdf_deep_scan_default_options({"textLayerOnly": True}, profile, suffix=".pdf")

    assert options == {"textLayerOnly": True}


def test_license_pdf_deep_scan_default_is_seal_focused_not_full_ocr() -> None:
    profile = profile_for("qualification_certificate_v1")

    options = apply_business_pdf_deep_scan_default_options({}, profile, suffix=".pdf")

    assert options["deepScanPdf"] is True
    assert options["disablePdfTextLayerFastPath"] is True
    assert options["forceSealOcr"] is True
    assert options["maxPages"] == 2
    assert options["enablePaddlexSeal"] is False
    assert options["enableSealTextRecognition"] is False
    assert options["enableRasterTextOcr"] is False
    assert options["enableTables"] is False
    assert options["forceFallbackOcr"] is True
    assert options["disableRemediation"] is False
    assert options["enableVlLayoutTextRemediation"] is True
    assert options["renderDpi"] == 250
    assert options["maxLongSide"] == 1800
    assert options["textDetLimitSideLen"] == 1800
    assert options["variants"] == ["original"]
    assert "fullOcr" not in options
    assert "forceTableOcr" not in options


def test_license_pdf_default_skips_raster_text_and_forces_vl_fallback(monkeypatch, tmp_path) -> None:
    from apps.ocr_service.service import OcrService

    source = tmp_path / "license.pdf"
    source.write_bytes(b"%PDF-1.4\n")
    page = tmp_path / "page-1.png"
    page.write_bytes(b"fake-image")
    monkeypatch.setenv("AICHECK_OCR_ALLOWED_LOCAL_DIRS", str(tmp_path))
    calls = {"vl": 0}

    class RasterTextEngineShouldNotRun:
        name = "paddle_ocr_subprocess"
        version = "test"

        def available(self):
            return True

        def status(self):
            return {"engine": self.name, "version": self.version, "available": True}

        def parse(self, *args, **kwargs):
            raise AssertionError("license PDF default must skip raster text OCR")

    class FakePaddleOcrVlEngine:
        name = "paddleocr_vl_1_6"
        version = "test"

        def available(self):
            return True

        def status(self):
            return {"engine": self.name, "version": self.version, "available": True}

        def parse(self, source_path, *, file_name=None, profile=None, variant=None):
            calls["vl"] += 1
            assert str(variant.get("variantId")) == "document_original"
            assert str(variant.get("engineScope")) == "document"
            assert str(variant.get("path")).endswith("license.pdf")
            return {
                "ok": True,
                "text": "中华人民共和国特种设备生产许可证 许可证编号 TS3810436-2021 有效期至 2024年6月21日",
                "fragments": [
                    {
                        "pageNo": 1,
                        "text": "许可证编号 TS3810436-2021",
                        "confidence": 0.91,
                        "sourceEngine": self.name,
                    }
                ],
                "fields": [],
                "tables": [],
                "seals": [],
                "metadata": {"documentLevel": True, "engineScope": "document"},
            }

    class TableEngineShouldNotRun:
        name = "pp_structure_v3"
        version = "test"

        def available(self):
            return True

        def status(self):
            return {"engine": self.name, "version": self.version, "available": True}

        def parse(self, *args, **kwargs):
            raise AssertionError("license PDF default must skip table OCR before VL fallback")

    monkeypatch.setattr(
        "apps.ocr_service.service.render_document_pages",
        lambda source_path, profile=None: [
            {
                "pageNo": 1,
                "path": str(page),
                "width": 100,
                "height": 100,
                "sourceType": "pdf",
                "documentPath": str(source),
            }
        ],
    )
    monkeypatch.setattr(
        "apps.ocr_service.service.call_probe_page_quality",
        lambda source_path, profile=None, pages=None: [{"pageNo": 1, "quality": {"isLowQuality": True}}],
    )
    monkeypatch.setattr(
        "apps.ocr_service.service.call_generate_image_variants",
        lambda source_path, profile=None, page_quality=None, pages=None, options=None: [
            {
                "variantId": "page_1_original",
                "pageNo": 1,
                "path": str(page),
                "documentPath": str(source),
                "sourceType": "pdf",
                "preprocessChain": ["original"],
            }
        ],
    )

    service = OcrService()
    service.pipeline = None
    service.engines = [RasterTextEngineShouldNotRun(), TableEngineShouldNotRun(), FakePaddleOcrVlEngine()]

    result = service.parse_document(
        str(source),
        file_name="license.pdf",
        profile_id="qualification_certificate_v1",
        options={"disableResultCache": True, "disableEngineResultCache": True, "disableRemediation": True},
    )

    assert calls["vl"] == 1
    assert result["status"] == "success"
    assert result["metadata"]["deepScanDefaultReason"] == "business_pdf_profile:qualification_certificate_v1"
    assert result["metadata"]["rasterTextOcrEnabled"] is False
    assert result["metadata"]["fallbackOcrForced"] is True
    assert any(item.get("engine") == "paddle_ocr_subprocess" and item.get("status") == "skipped" for item in result["engineRuns"])
    assert any(item.get("engine") == "pp_structure_v3" and item.get("status") == "skipped" for item in result["engineRuns"])
    assert any(item.get("engine") == "paddleocr_vl_1_6" and item.get("status") == "success" for item in result["engineRuns"])


def test_fast_first_defer_heavy_engines_after_text_evidence() -> None:
    profile = profile_for("piping_characteristic_list_v1")
    options = apply_fast_first_default_options({}, profile)
    result = {
        "fragments": [
            {
                "text": "珠海恒基达鑫国际化工仓储股份有限公司 施工图 QX201903S-13-Y-00",
                "sourceEngine": "paddle_ocr_subprocess",
            }
        ]
    }

    assert should_defer_heavy_engine("pp_structure_v3", result, profile=profile, options=options) is True
    assert should_defer_heavy_engine("paddlex_seal_recognition", result, profile=profile, options=options) is True
    assert should_defer_heavy_engine("paddleocr_vl_1_6", result, profile=profile, options=options) is True
    assert should_defer_heavy_engine("opencv_table_grid_subprocess", result, profile=profile, options=options) is True
    assert should_defer_heavy_engine("visual_seal_candidate_subprocess", result, profile=profile, options=options) is True


def test_paddleocr_vl_document_bbox_can_drive_crop_remediation() -> None:
    result = {
        "layoutBlocks": [
            {
                "blockId": "layout_1",
                "blockType": "text",
                "pageNo": 1,
                "bbox": [100, 120, 420, 180],
                "sourceEngine": "paddleocr_vl_1_6",
            }
        ],
        "fields": [],
        "fragments": [],
        "tables": [],
        "seals": [],
    }
    variant = {
        "variantId": "document_original",
        "engineScope": "document",
        "preprocessChain": ["document_original"],
    }

    attach_variant_metadata(
        result,
        "paddleocr_vl_1_6",
        variant,
        document_pages=[{"pageNo": 1, "width": 800, "height": 1000}],
    )

    block = result["layoutBlocks"][0]
    assert block["coordinateSystem"] == "rendered_pixels"
    assert block["coordinateTransformStatus"] == "vl_document_pixels_match_rendered_page"
    assert "document_coordinate_unmapped" not in block.get("qualityFlags", [])


def test_project_name_can_join_lines_after_project_label() -> None:
    text_items = [
        ("项目名称", {"pageNo": 1, "bbox": [10, 10, 50, 20], "confidence": 0.99}),
        ("珠海恒基达鑫国际化工仓储股份有限公司", {"pageNo": 1, "bbox": [60, 10, 200, 20], "confidence": 0.98}),
        ("PROJECT", {"pageNo": 1, "bbox": [10, 25, 50, 35], "confidence": 0.98}),
        ("二期装车站新增两套卸车系统项目", {"pageNo": 1, "bbox": [60, 25, 200, 35], "confidence": 0.97}),
    ]

    candidate = find_project_fragment(text_items)

    assert candidate is not None
    assert candidate["text"] == "珠海恒基达鑫国际化工仓储股份有限公司二期装车站新增两套卸车系统项目"
    assert candidate["fragment"]["bbox"] == [60.0, 10.0, 200.0, 35.0]


def test_engineering_drawing_list_profile_does_not_require_piping_table() -> None:
    profile = profile_for("engineering_drawing_list")

    assert profile["profileId"] == "engineering_drawing_list_v1"
    assert "pipe_no" not in profile["requiredFields"]
    assert "piping_characteristic_table" not in profile["requiredTables"]
    assert profile["requiredTables"] == ["engineering_drawing_list_rows_v1"]


def test_drawing_list_text_routes_piping_request_to_drawing_list_profile() -> None:
    requested = profile_for("piping_characteristic_list_v1")
    result = {
        "fragments": [
            {"text": "工艺图纸目录", "bbox": [100, 100, 220, 130], "confidence": 0.97},
            {"text": "DRAWING LIST", "bbox": [100, 132, 230, 160], "confidence": 0.97},
            {"text": "QX201903S-13-Y-00", "bbox": [300, 100, 460, 130], "confidence": 0.96},
            {"text": "QX201903S-13-Y-01", "bbox": [300, 132, 460, 160], "confidence": 0.96},
        ]
    }

    routed = detect_engineering_drawing_list_profile(result, requested)

    assert routed is not None
    assert routed["profile"]["profileId"] == "engineering_drawing_list_v1"
    assert "drawing_list_title" in routed["reason"]


def test_engineering_drawing_router_detects_specialized_profiles() -> None:
    requested = profile_for("piping_characteristic_list_v1")
    material = detect_engineering_drawing_profile(
        {"fragments": [{"text": "管道安装材料表 QX201903S-13-Y-08"}]},
        requested,
    )
    strength = detect_engineering_drawing_profile(
        {"fragments": [{"text": "压力管道强度计算书 QX201903S-13-Y-13"}]},
        requested,
    )
    design_spec = detect_engineering_drawing_profile(
        {"fragments": [{"text": "工艺设计说明书 施工图"}]},
        requested,
    )

    assert material is not None
    assert material["profile"]["profileId"] == "drawing_material_list_v1"
    assert strength is not None
    assert strength["profile"]["profileId"] == "strength_calculation_v1"
    assert design_spec is not None
    assert design_spec["profile"]["profileId"] == "design_specification_v1"


def test_engineering_drawing_router_detects_site_layout_pages() -> None:
    requested = profile_for("piping_characteristic_list_v1")
    routed = detect_engineering_drawing_profile(
        {
            "fragments": [
                {"text": "TK403 5000m3"},
                {"text": "TK404 4000m3"},
                {"text": "消防道路 装车站 泵区 临海道防道路"},
            ]
        },
        requested,
    )

    assert routed is not None
    assert routed["profile"]["profileId"] == "site_layout_drawing_v1"
    assert routed["reason"] == "site_layout_spatial_tokens"


def test_engineering_drawing_router_does_not_treat_plain_drawing_numbers_as_list() -> None:
    requested = profile_for("piping_characteristic_list_v1")
    result = {
        "fragments": [
            {"text": "QX201903S-13-Y-01"},
            {"text": "QX201903S-13-Y-02"},
            {"text": "项目名称 珠海恒基达鑫项目"},
        ]
    }

    routed = detect_engineering_drawing_profile(result, requested)

    assert routed is None


def test_engineering_drawing_router_keeps_requested_piping_profile_on_strong_title() -> None:
    requested = profile_for("piping_characteristic_list_v1")
    result = {
        "fragments": [
            {"text": "管道特性表"},
            {"text": "PIPING CHARACTERISTIC LIST"},
            {"text": "P&ID"},
        ]
    }

    routed = detect_engineering_drawing_profile(result, requested)

    assert routed is None


def test_engineering_drawing_router_prioritizes_drawing_list_title_over_piping_row() -> None:
    requested = profile_for("piping_characteristic_list_v1")
    result = {
        "fragments": [
            {"text": "工艺图纸目录"},
            {"text": "管道特性表"},
            {"text": "QX201903S-13-Y-07"},
        ]
    }

    routed = detect_engineering_drawing_profile(result, requested)

    assert routed is not None
    assert routed["profile"]["profileId"] == "engineering_drawing_list_v1"


def test_generic_profile_routes_to_piping_characteristic_profile() -> None:
    requested = profile_for("generic_document_v1")
    result = {
        "fragments": [
            {"text": "管道特性表"},
            {"text": "PIPING CHARACTERISTIC LIST"},
            {"text": "PL8301 GC2 RT 10% III AB"},
        ]
    }

    routed = detect_engineering_drawing_profile(result, requested)

    assert routed is not None
    assert routed["profile"]["profileId"] == "piping_characteristic_list_v1"


def test_generic_profile_routes_scan_pdf_quality_and_rt_documents() -> None:
    requested = profile_for("generic_document_v1")
    quality_route = detect_scan_business_document_profile(
        {
            "fragments": [
                {"text": "产品质量证明书"},
                {"text": "执行标准 GB/T 8163-2018"},
                {"text": "化学成分 C Si Mn P S"},
                {"text": "力学性能 抗拉强度 屈服强度"},
                {"text": "质检专用章 检验合格"},
            ]
        },
        requested,
    )
    rt_route = detect_scan_business_document_profile(
        {
            "fragments": [
                {"text": "射线检测报告 RT"},
                {"text": "报告编号 RTBG-2021-001"},
                {"text": "焊口编号 W-001"},
                {"text": "底片 评定级别 II 检测比例 10%"},
            ]
        },
        requested,
    )

    assert quality_route is not None
    assert quality_route["profile"]["profileId"] == "quality_certificate_v1"
    assert rt_route is not None
    assert rt_route["profile"]["profileId"] == "ndt_rt_report_v1"


def test_generic_profile_routes_scan_pdf_ut_documents() -> None:
    requested = profile_for("generic_document_v1")

    routed = detect_scan_business_document_profile(
        {
            "fragments": [
                {"text": "超声检测报告 UT"},
                {"text": "报告编号 UTBG-2021-001"},
                {"text": "焊口编号 W-002"},
                {"text": "探头 评定级别 II 检测比例 10%"},
            ]
        },
        requested,
    )

    assert routed is not None
    assert routed["profile"]["profileId"] == "ndt_ut_report_v1"


def test_generic_profile_routes_construction_plan_without_confusing_welding_record() -> None:
    requested = profile_for("generic_document_v1")

    routed = detect_scan_business_document_profile(
        {
            "fragments": [
                {"text": "工艺管道施工方案"},
                {"text": "项目名称 二期装车站新增两套卸车系统项目"},
                {"text": "施工单位 广东政和工程有限公司"},
                {"text": "编制依据 施工方法 质量保证措施 安全技术措施"},
                {"text": "2021年4月15日"},
            ]
        },
        requested,
    )

    assert routed is not None
    assert routed["profile"]["profileId"] == "construction_plan_v1"


def test_construction_plan_profile_extracts_basic_consistency_fields() -> None:
    result = {
        "fragments": [
            {"text": "工艺管道施工方案", "bbox": [10, 10, 160, 30], "confidence": 0.98, "pageNo": 1},
            {"text": "项目名称", "bbox": [10, 40, 80, 60], "confidence": 0.98, "pageNo": 1},
            {"text": "二期装车站新增两套卸车系统项目", "bbox": [90, 40, 320, 60], "confidence": 0.97, "pageNo": 1},
            {"text": "施工单位", "bbox": [10, 70, 80, 90], "confidence": 0.98, "pageNo": 1},
            {"text": "广东政和工程有限公司", "bbox": [90, 70, 260, 90], "confidence": 0.97, "pageNo": 1},
            {"text": "2021年4月15日", "bbox": [10, 100, 120, 120], "confidence": 0.96, "pageNo": 1},
            {"text": "编制依据 施工方法 质量保证措施", "bbox": [10, 130, 240, 150], "confidence": 0.95, "pageNo": 1},
        ],
        "fields": [],
        "tables": [],
        "seals": [],
        "diagnostics": [],
    }

    apply_profile_postprocessing(result, profile_for("construction_plan_v1"))
    fields = {item["fieldCode"]: item["fieldValue"] for item in result["fields"]}

    assert fields["document_title"] == "管道施工方案"
    assert fields["project_name"] == "二期装车站新增两套卸车系统项目"
    assert fields["construction_unit"] == "广东政和工程有限公司"
    assert fields["issue_date"] == "2021年4月15日"


def test_generic_profile_routes_welding_procedure_qualification_separately_from_record() -> None:
    requested = profile_for("generic_document_v1")

    routed = detect_scan_business_document_profile(
        {
            "fragments": [
                {"text": "承压设备焊接工艺评定报告"},
                {"text": "PQR-2021-001 WPS-2021-001"},
                {"text": "焊接方法 GTAW/SMAW"},
                {"text": "母材 Q345R 厚度范围 3-12mm"},
                {"text": "评定日期 2021年4月12日"},
            ]
        },
        requested,
    )

    assert routed is not None
    assert routed["profile"]["profileId"] == "welding_procedure_qualification_v1"


def test_welding_procedure_qualification_profile_extracts_scope_fields_and_table_schema() -> None:
    result = {
        "fragments": [
            {"text": "承压设备焊接工艺评定报告", "bbox": [10, 10, 220, 35], "confidence": 0.94, "pageNo": 1},
            {"text": "报告编号 PQR-2021-001", "bbox": [10, 45, 180, 65], "confidence": 0.93, "pageNo": 1},
            {"text": "项目名称", "bbox": [10, 75, 90, 95], "confidence": 0.95, "pageNo": 1},
            {"text": "二期装车站新增两套卸车系统项目", "bbox": [100, 75, 350, 95], "confidence": 0.94, "pageNo": 1},
            {"text": "WPS编号 WPS-2021-001", "bbox": [10, 105, 170, 125], "confidence": 0.93, "pageNo": 1},
            {"text": "焊接方法 GTAW/SMAW", "bbox": [10, 135, 180, 155], "confidence": 0.92, "pageNo": 1},
            {"text": "母材 Q345R", "bbox": [10, 165, 120, 185], "confidence": 0.92, "pageNo": 1},
            {"text": "厚度范围 3-12mm", "bbox": [10, 195, 150, 215], "confidence": 0.91, "pageNo": 1},
            {"text": "评定日期 2021年4月12日", "bbox": [10, 225, 190, 245], "confidence": 0.93, "pageNo": 1},
        ],
        "fields": [],
        "tables": [
            {
                "tableId": "pqr_table_1",
                "cells": [
                    {"text": "PQR", "row": 0, "col": 0},
                    {"text": "焊接方法", "row": 0, "col": 1},
                    {"text": "母材", "row": 0, "col": 2},
                    {"text": "厚度范围", "row": 0, "col": 3},
                ],
            }
        ],
        "seals": [],
        "diagnostics": [],
    }

    apply_profile_postprocessing(result, profile_for("welding_procedure_qualification_v1"))
    fields = {item["fieldCode"]: item["fieldValue"] for item in result["fields"]}

    assert fields["report_no"] == "PQR-2021-001"
    assert fields["project_name"] == "二期装车站新增两套卸车系统项目"
    assert fields["procedure_no"] == "WPS-2021-001"
    assert fields["welding_method"] == "GTAW/SMAW"
    assert fields["base_material"] == "Q345R"
    assert fields["thickness_range"] == "3-12mm"
    assert fields["qualification_date"] == "2021年4月12日"
    assert result["tables"][0]["businessSchema"] == "welding_procedure_qualification_table"


def test_scan_business_router_does_not_override_explicit_profile() -> None:
    requested = profile_for("quality_certificate_v1")
    result = {
        "fragments": [
            {"text": "射线检测报告 RT"},
            {"text": "底片 评定级别 II"},
        ]
    }

    routed = detect_scan_business_document_profile(result, requested)

    assert routed is None


def test_engineering_drawing_common_fields_extract_title_block_values() -> None:
    result = {
        "fragments": [
            {"text": "广东政和工程有限公司", "bbox": [10, 10, 200, 30], "confidence": 0.98, "pageNo": 1},
            {"text": "项目名称", "bbox": [10, 40, 80, 60], "confidence": 0.98, "pageNo": 1},
            {"text": "珠海恒基达鑫二期装车站新增两套卸车系统项目", "bbox": [90, 40, 360, 60], "confidence": 0.96, "pageNo": 1},
            {"text": "管道安装材料表", "bbox": [10, 70, 160, 90], "confidence": 0.98, "pageNo": 1},
            {"text": "QX201903S-13-Y-08", "bbox": [10, 100, 180, 120], "confidence": 0.97, "pageNo": 1},
            {"text": "施工图", "bbox": [10, 130, 80, 150], "confidence": 0.97, "pageNo": 1},
        ],
        "fields": [],
    }

    extract_engineering_drawing_common_fields(result, profile_for("drawing_material_list_v1"))
    fields = {item["fieldCode"]: item["fieldValue"] for item in result["fields"]}

    assert fields["company_name"] == "广东政和工程有限公司"
    assert fields["project_name"] == "珠海恒基达鑫二期装车站新增两套卸车系统项目"
    assert fields["document_title"] == "管道安装材料表"
    assert fields["drawing_no"] == "QX201903S-13-Y-08"
    assert fields["design_phase"] == "施工图"


def test_engineering_drawing_common_fields_ignore_license_number_as_drawing_no() -> None:
    result = {
        "fragments": [
            {"text": "资质证书编号：A244010070", "bbox": [10, 10, 120, 30], "confidence": 0.98, "pageNo": 1},
            {"text": "TS1810648-2021", "bbox": [10, 40, 120, 60], "confidence": 0.98, "pageNo": 1},
            {"text": "QX201903S-13-Y-10", "bbox": [10, 70, 180, 90], "confidence": 0.97, "pageNo": 1},
            {"text": "施工图", "bbox": [10, 100, 80, 120], "confidence": 0.97, "pageNo": 1},
        ],
        "fields": [],
    }

    extract_engineering_drawing_common_fields(result, profile_for("strength_calculation_v1"))
    fields = {item["fieldCode"]: item["fieldValue"] for item in result["fields"]}

    assert fields["drawing_no"] == "QX201903S-13-Y-10"


def test_engineering_drawing_common_fields_do_not_use_license_only_as_drawing_no() -> None:
    result = {
        "fragments": [
            {"text": "专质证书编号：A244010070", "bbox": [10, 10, 120, 30], "confidence": 0.98, "pageNo": 1},
            {"text": "TS1810648-2021", "bbox": [10, 40, 120, 60], "confidence": 0.98, "pageNo": 1},
            {"text": "GB/T20801.3-2006", "bbox": [10, 70, 120, 90], "confidence": 0.98, "pageNo": 1},
            {"text": "PL7304-100MIB-EL", "bbox": [10, 95, 160, 115], "confidence": 0.98, "pageNo": 1},
            {"text": "施工图", "bbox": [10, 100, 80, 120], "confidence": 0.97, "pageNo": 1},
        ],
        "fields": [],
    }

    extract_engineering_drawing_common_fields(result, profile_for("process_flow_diagram_v1"))
    fields = {item["fieldCode"]: item["fieldValue"] for item in result["fields"]}

    assert "drawing_no" not in fields


def test_piping_requirement_fields_are_structured_from_business_rows() -> None:
    result = {
        "fragments": [
            {"text": "GC2", "bbox": [10, 10, 40, 30], "confidence": 0.96, "pageNo": 1},
            {"text": "RT", "bbox": [50, 10, 80, 30], "confidence": 0.96, "pageNo": 1},
            {"text": "10%", "bbox": [90, 10, 130, 30], "confidence": 0.96, "pageNo": 1},
            {"text": "III", "bbox": [140, 10, 175, 30], "confidence": 0.96, "pageNo": 1},
            {"text": "AB", "bbox": [185, 10, 220, 30], "confidence": 0.96, "pageNo": 1},
        ],
        "fields": [],
        "tables": [
            {
                "businessRows": [
                    {
                        "pressureLevel": "GC2",
                        "weldDetectionMethod": "RT",
                        "weldDetectionScale": "10%",
                        "eligibleLevel": "III",
                        "ranking": "AB",
                    }
                ]
            }
        ],
    }

    extract_piping_requirement_fields(result)
    fields = {item["fieldCode"]: item["fieldValue"] for item in result["fields"]}

    assert fields["pressure_pipe_level"] == "GC2"
    assert fields["weld_detection_method"] == "RT"
    assert fields["weld_detection_ratio"] == "10%"
    assert fields["weld_acceptance_level"] == "III"
    assert fields["weld_tech_level"] == "AB"


def test_piping_requirement_fields_are_structured_from_ocr_row_fragments() -> None:
    result = {
        "fragments": [
            {"text": "RT", "bbox": [1407, 270, 1428, 285], "confidence": 0.99, "pageNo": 1},
            {"text": "10%", "bbox": [1459, 269, 1486, 287], "confidence": 0.99, "pageNo": 1},
            {"text": "III", "bbox": [1515, 272, 1539, 290], "confidence": 0.96, "pageNo": 1},
            {"text": "AB", "bbox": [1568, 274, 1588, 289], "confidence": 0.99, "pageNo": 1},
            {"text": "广东星燃石化设计院有限公司", "bbox": [350, 100, 720, 130], "confidence": 0.99, "pageNo": 1},
        ],
        "fields": [],
        "tables": [],
    }

    extract_piping_requirement_fields(result)
    fields = {item["fieldCode"]: item["fieldValue"] for item in result["fields"]}

    assert fields["weld_detection_method"] == "RT"
    assert fields["weld_detection_ratio"] == "10%"
    assert fields["weld_acceptance_level"] == "III"
    assert fields["weld_tech_level"] == "AB"


def test_fragment_seal_fields_extract_blue_expiry_without_reusing_red_date() -> None:
    fragments = [
        {"pageNo": 1, "text": "出图专用章", "bbox": [580, 1000, 690, 1030], "confidence": 0.92},
        {"pageNo": 1, "text": "单位名称 广东政和工程有限公司", "bbox": [590, 1035, 850, 1065], "confidence": 0.91},
        {"pageNo": 1, "text": "资质证书编号 A244010070", "bbox": [590, 1070, 850, 1100], "confidence": 0.9},
        {"pageNo": 1, "text": "有效期至：2024年6月21日", "bbox": [590, 1105, 850, 1135], "confidence": 0.9},
        {"pageNo": 1, "text": "设计许可 压力管道", "bbox": [80, 750, 250, 790], "confidence": 0.91},
        {"pageNo": 1, "text": "TS1810648-2021", "bbox": [90, 795, 250, 825], "confidence": 0.91},
        {"pageNo": 1, "text": "2017年8月31日", "bbox": [90, 830, 250, 860], "confidence": 0.9},
    ]

    seals = fragment_seal_candidates_from_text(fragments, existing_seals=[])
    blue = next(item for item in seals if item["sealType"] == "drawing_approval_seal")
    red = next(item for item in seals if item["sealType"] == "design_license_seal")
    blue_fields = {item["fieldCode"]: item["fieldValue"] for item in blue["fields"]}
    red_fields = {item["fieldCode"]: item["fieldValue"] for item in red["fields"]}

    assert blue["canSatisfyRequiredSeal"] is False
    assert blue["candidateOnly"] is True
    assert blue["sealEvidenceLevel"] == "fragment_roi_text"
    assert blue_fields["blue_seal_license_no"] == "A244010070"
    assert blue_fields["blue_seal_expiry"] == "2024年6月21日"
    assert red["canSatisfyRequiredSeal"] is False
    assert red["candidateOnly"] is True
    assert red["sealEvidenceLevel"] == "fragment_roi_text"
    assert red_fields["red_seal_date"] == "2017年8月31日"
    assert "blue_seal_expiry" not in red_fields


def test_fragment_seal_fields_do_not_promote_without_crop_ocr() -> None:
    fragments = [
        {
            "pageNo": 1,
            "text": "出图专用章",
            "bbox": [580, 1000, 690, 1030],
            "confidence": 0.92,
            "coordinateSystem": "rendered_pixels",
            "coordinateTransformStatus": "original",
        },
        {
            "pageNo": 1,
            "text": "单位名称 广东政和工程有限公司",
            "bbox": [590, 1035, 850, 1065],
            "confidence": 0.91,
            "coordinateSystem": "rendered_pixels",
            "coordinateTransformStatus": "original",
        },
        {
            "pageNo": 1,
            "text": "资质证书编号 A244010070",
            "bbox": [590, 1070, 850, 1100],
            "confidence": 0.9,
            "coordinateSystem": "rendered_pixels",
            "coordinateTransformStatus": "original",
        },
        {
            "pageNo": 1,
            "text": "有效期至：2024年6月21日",
            "bbox": [590, 1105, 850, 1135],
            "confidence": 0.9,
            "coordinateSystem": "rendered_pixels",
            "coordinateTransformStatus": "original",
        },
    ]

    fused = fuse_parse_result(
        {"status": "success", "fragments": fragments, "fields": [], "tables": [], "seals": []},
        profile=profile_for("engineering_drawing_list_v1"),
    )
    fields = {item["fieldCode"]: item for item in fused["fields"]}

    assert "blue_seal_expiry" not in fields
    assert fused["seals"][0]["candidateOnly"] is True
    assert "SEAL_TEXT_LOW_CONFIDENCE" in fused["quality"]["reasons"]


def test_seal_crop_ocr_outputs_crop_evidence_and_promoted_fields() -> None:
    result = {
        "fragments": [
            {"text": "广东省建设工程勘察设计出图专用章", "bbox": [0, 0, 180, 22], "confidence": 0.94},
            {"text": "资质证书编号 A244010070", "bbox": [0, 26, 180, 48], "confidence": 0.93},
            {"text": "有效期至：2024年6月21日", "bbox": [0, 52, 180, 74], "confidence": 0.92},
        ],
        "fields": [],
        "tables": [],
        "seals": [],
        "layoutBlocks": [],
    }
    variant = {
        "variantId": "page_1_seal_crop_drawing_approval_abcd1234",
        "pageNo": 1,
        "purpose": "seal",
        "source": "remediation_crop",
        "engineScope": "crop",
        "coordinateSystem": "crop_pixels",
        "sourceCoordinateSystem": "rendered_pixels",
        "coordinateTransformStatus": "crop_local",
        "cropOffsetX": 588,
        "cropOffsetY": 1005,
        "cropSourceBbox": [588, 1005, 890, 1152],
        "cropWidth": 302,
        "cropHeight": 147,
        "remediationTarget": {
            "type": "seal",
            "id": "fragment_drawing_approval_seal_1_2",
            "sourceKind": "fragment_seal_bbox",
            "sourceSealType": "drawing_approval_seal",
            "sourceQualityFlags": ["seal_bbox_from_ocr_fragments"],
            "sourceSealEvidenceLevel": "fragment_roi_text",
        },
    }

    attach_variant_metadata(result, "paddle_ocr_subprocess", variant, document_pages=[{"pageNo": 1}])
    fused = fuse_parse_result(result, profile=profile_for("engineering_drawing_list_v1"))
    seal = fused["seals"][0]
    fields = {item["fieldCode"]: item for item in fused["fields"]}

    assert seal["sealEvidenceLevel"] == "visual_plus_seal_crop_ocr"
    assert seal["sealName"] == "广东省建设工程勘察设计出图专用章 资质证书编号 A244010070 有效期至：2024年6月21日"
    assert seal["canSatisfyRequiredSeal"] is True
    assert seal["cropBbox"] == [588, 1005, 890, 1152]
    assert seal["sealCropEvidence"]["sourceEngine"] == "paddle_ocr_subprocess"
    assert fields["blue_seal_expiry"]["fieldValue"] == "2024年6月21日"
    assert fields["blue_seal_expiry"]["sourcePriority"] == "crop_ocr"


def test_seal_crop_ocr_removes_adjacent_drawing_list_noise() -> None:
    result = {
        "fragments": [
            {"text": "8", "bbox": [0, 0, 10, 16], "confidence": 0.99},
            {"text": "管道特性表", "bbox": [20, 0, 90, 18], "confidence": 0.98},
            {"text": "QX201903S-13-Y-07", "bbox": [160, 0, 260, 18], "confidence": 0.99},
            {"text": "1", "bbox": [270, 0, 280, 18], "confidence": 0.99},
            {"text": "压力管道", "bbox": [10, 80, 80, 104], "confidence": 0.93},
            {"text": "TS1810648-2021", "bbox": [90, 80, 210, 104], "confidence": 0.92},
        ],
        "fields": [],
        "tables": [],
        "seals": [],
        "layoutBlocks": [],
    }
    variant = {
        "variantId": "page_1_seal_crop_design_license_abcd1234",
        "pageNo": 1,
        "purpose": "seal",
        "source": "remediation_crop",
        "engineScope": "crop",
        "coordinateSystem": "crop_pixels",
        "sourceCoordinateSystem": "rendered_pixels",
        "coordinateTransformStatus": "crop_local",
        "cropOffsetX": 89,
        "cropOffsetY": 754,
        "cropSourceBbox": [89, 754, 513, 1086],
        "cropWidth": 424,
        "cropHeight": 332,
        "remediationTarget": {
            "type": "seal",
            "id": "fragment_design_license_seal_1_1",
            "sourceKind": "fragment_seal_bbox",
            "sourceSealType": "design_license_seal",
            "sourceQualityFlags": ["seal_bbox_from_ocr_fragments"],
            "sourceSealEvidenceLevel": "fragment_roi_text",
        },
    }

    attach_variant_metadata(result, "paddle_ocr_subprocess", variant, document_pages=[{"pageNo": 1}])
    fused = fuse_parse_result(result, profile=profile_for("engineering_drawing_list_v1"))
    seal = fused["seals"][0]
    fields = {item["fieldCode"]: item for item in fused["fields"]}

    assert seal["sealName"] == "压力管道 TS1810648-2021"
    assert seal["cropOcrText"] == "压力管道 TS1810648-2021"
    assert "管道特性表" in seal["cropOcrRawText"]
    assert "seal_crop_adjacent_text_removed" in seal["qualityFlags"]
    assert fields["license_scope"]["fieldValue"] == "压力管道"
    assert fields["license_no"]["fieldValue"] == "TS1810648-2021"


def test_engineering_drawing_list_rows_are_structured_from_fragments() -> None:
    result = {"fragments": [], "fields": [], "tables": []}
    fragments = [
        {"text": "1", "bbox": [80, 480, 100, 500], "confidence": 0.95, "pageNo": 1, "coordinateSystem": "rendered_pixels", "coordinateTransformStatus": "original"},
        {"text": "工艺图纸目录", "bbox": [120, 480, 220, 500], "confidence": 0.99, "pageNo": 1, "coordinateSystem": "rendered_pixels", "coordinateTransformStatus": "original"},
        {"text": "QX201903S-13-Y-00", "bbox": [380, 480, 520, 500], "confidence": 0.99, "pageNo": 1, "coordinateSystem": "rendered_pixels", "coordinateTransformStatus": "original"},
        {"text": "2", "bbox": [80, 520, 100, 540], "confidence": 0.95, "pageNo": 1, "coordinateSystem": "rendered_pixels", "coordinateTransformStatus": "original"},
        {"text": "设备表一览表", "bbox": [120, 520, 220, 540], "confidence": 0.99, "pageNo": 1, "coordinateSystem": "rendered_pixels", "coordinateTransformStatus": "original"},
        {"text": "QX201903S-13-Y-01", "bbox": [380, 520, 520, 540], "confidence": 0.99, "pageNo": 1, "coordinateSystem": "rendered_pixels", "coordinateTransformStatus": "original"},
    ]
    result["fragments"] = fragments

    extract_engineering_drawing_list_fields(result, profile_for("engineering_drawing_list_v1"))
    fields = {item["fieldCode"]: item for item in result["fields"]}
    rows = fields["drawing_list_rows"]["fieldValue"]
    row_table = next(item for item in result["tables"] if item["businessSchema"] == "engineering_drawing_list_rows_v1")

    assert rows[0]["drawingName"] == "工艺图纸目录"
    assert rows[0]["drawingNo"] == "QX201903S-13-Y-00"
    assert rows[1]["sequenceNo"] == "2"
    assert row_table["rows"] == 2
    assert row_table["bbox"] == [80.0, 480.0, 520.0, 540.0]


def test_quality_certificate_summary_tables_are_created_from_fragments() -> None:
    result = {
        "fragments": [
            {"text": "产品质量证明书", "bbox": [10, 10, 130, 30], "confidence": 0.96, "pageNo": 1},
            {"text": "材质 20#", "bbox": [10, 40, 130, 60], "confidence": 0.96, "pageNo": 1},
            {"text": "执行标准 GB/T 8163-2018", "bbox": [10, 70, 220, 90], "confidence": 0.96, "pageNo": 1},
            {"text": "化学成分 C Si Mn P S", "bbox": [10, 100, 230, 120], "confidence": 0.95, "pageNo": 1},
            {"text": "力学性能 抗拉强度 屈服 延伸率", "bbox": [10, 130, 270, 150], "confidence": 0.95, "pageNo": 1},
        ],
        "fields": [],
        "tables": [],
        "seals": [],
    }

    apply_profile_postprocessing(result, profile_for("quality_certificate_v1"))
    schemas = {
        schema
        for table in result["tables"]
        for schema in [table.get("businessSchema"), *(table.get("businessSchemas") or [])]
        if schema
    }
    fields = {item["fieldCode"]: item["fieldValue"] for item in result["fields"]}

    assert "material_chemical_composition_table" in schemas
    assert "mechanical_property_table" in schemas
    assert fields["chemical_composition_summary"] == "化学成分"
    assert fields["mechanical_property_summary"] == "力学性能"


def test_quality_certificate_infers_quality_seal_from_zhijian_text() -> None:
    result = fuse_parse_result(
        {
            "status": "success",
            "fields": [
                {"fieldCode": "certificate_no", "fieldValue": "QC-001", "confidence": 0.9, "bbox": [0, 0, 10, 10]},
                {"fieldCode": "manufacturer", "fieldValue": "制造有限公司", "confidence": 0.9, "bbox": [0, 0, 10, 10]},
                {"fieldCode": "material_grade", "fieldValue": "20#", "confidence": 0.9, "bbox": [0, 0, 10, 10]},
                {"fieldCode": "specification", "fieldValue": "DN100", "confidence": 0.9, "bbox": [0, 0, 10, 10]},
                {"fieldCode": "batch_no", "fieldValue": "B001", "confidence": 0.9, "bbox": [0, 0, 10, 10]},
                {"fieldCode": "standard_no", "fieldValue": "GB/T8163-2018", "confidence": 0.9, "bbox": [0, 0, 10, 10]},
                {"fieldCode": "inspection_conclusion", "fieldValue": "检验合格", "confidence": 0.9, "bbox": [0, 0, 10, 10]},
                {"fieldCode": "issue_date", "fieldValue": "2021年3月18日", "confidence": 0.9, "bbox": [0, 0, 10, 10]},
                {"fieldCode": "seal", "fieldValue": "质检专用章", "confidence": 0.9, "bbox": [0, 0, 10, 10]},
            ],
            "tables": [
                {
                    "tableId": "T1",
                    "businessSchemas": ["material_chemical_composition_table", "mechanical_property_table"],
                    "structureConfidence": 0.9,
                    "bbox": [0, 0, 10, 10],
                    "cells": [{"text": "化学成分"}, {"text": "抗拉强度"}],
                }
            ],
            "seals": [
                {"sealId": "S1", "sealName": "制造有限公司公章", "sealType": "company_official_seal", "ocrConfidence": 0.9, "bbox": [0, 0, 10, 10]},
                {"sealId": "S2", "sealName": "质检专用章", "sealType": "unknown", "ocrConfidence": 0.9, "bbox": [20, 0, 40, 20]},
            ],
            "diagnostics": [],
        },
        profile=profile_for("quality_certificate_v1"),
    )

    assert "quality_seal" in result["quality"]["matchedSealTypes"]
    assert "quality_seal" not in result["quality"]["missingExpectedSealTypes"]


def test_quality_certificate_uses_zhijian_fragment_as_quality_seal_candidate() -> None:
    result = fuse_parse_result(
        {
            "status": "success",
            "fields": [
                {"fieldCode": "certificate_no", "fieldValue": "QC-002", "confidence": 0.9, "bbox": [0, 0, 10, 10]},
                {"fieldCode": "manufacturer", "fieldValue": "制造有限公司", "confidence": 0.9, "bbox": [0, 0, 10, 10]},
                {"fieldCode": "material_grade", "fieldValue": "20#", "confidence": 0.9, "bbox": [0, 0, 10, 10]},
                {"fieldCode": "specification", "fieldValue": "DN100", "confidence": 0.9, "bbox": [0, 0, 10, 10]},
                {"fieldCode": "batch_no", "fieldValue": "B002", "confidence": 0.9, "bbox": [0, 0, 10, 10]},
                {"fieldCode": "standard_no", "fieldValue": "HG/T20592-2009", "confidence": 0.9, "bbox": [0, 0, 10, 10]},
                {"fieldCode": "inspection_conclusion", "fieldValue": "检验合格", "confidence": 0.9, "bbox": [0, 0, 10, 10]},
                {"fieldCode": "issue_date", "fieldValue": "2021年3月18日", "confidence": 0.9, "bbox": [0, 0, 10, 10]},
            ],
            "fragments": [
                {"text": "产品出厂检验合格证", "confidence": 0.99, "bbox": [100, 100, 300, 130], "pageNo": 1},
                {"text": "检验合格", "confidence": 0.99, "bbox": [120, 400, 180, 430], "pageNo": 1},
                {"text": "质检专用章", "confidence": 0.99, "bbox": [250, 500, 330, 540], "pageNo": 1},
            ],
            "tables": [
                {
                    "tableId": "T1",
                    "businessSchemas": ["material_chemical_composition_table", "mechanical_property_table"],
                    "structureConfidence": 0.9,
                    "bbox": [0, 0, 10, 10],
                    "cells": [{"text": "化学成分"}, {"text": "抗拉强度"}],
                }
            ],
            "seals": [],
            "diagnostics": [],
        },
        profile=profile_for("quality_certificate_v1"),
    )

    quality_candidates = [
        seal
        for seal in result["seals"]
        if seal.get("sealType") == "quality_seal"
        and seal.get("sourceEngine") == "fragment_seal_text_detector"
    ]

    assert quality_candidates
    assert quality_candidates[0]["bbox"] == [100.0, 100.0, 330.0, 540.0]
    assert "text_only_seal_candidate" in quality_candidates[0]["qualityFlags"]
    assert "quality_seal" in result["quality"]["matchedSealTypes"]
    assert "quality_seal" not in result["quality"]["missingExpectedSealTypes"]


def test_ndt_rt_report_extracts_inferred_chinese_month_date() -> None:
    result = {
        "fragments": [
            {"text": "射线检测报告", "bbox": [10, 10, 130, 30], "confidence": 0.96, "pageNo": 1},
            {"text": "报告编号 RTBG-2021-001", "bbox": [10, 40, 220, 60], "confidence": 0.96, "pageNo": 1},
            {"text": "工程名称 珠海恒基达鑫项目", "bbox": [10, 70, 240, 90], "confidence": 0.96, "pageNo": 1},
            {"text": "焊口编号 W-001", "bbox": [10, 100, 140, 120], "confidence": 0.96, "pageNo": 1},
            {"text": "评定级别 II", "bbox": [10, 130, 140, 150], "confidence": 0.96, "pageNo": 1},
            {"text": "报告日期 二零年四月", "bbox": [10, 160, 170, 180], "confidence": 0.9, "pageNo": 1},
            {"text": "检测结论 合格", "bbox": [10, 190, 140, 210], "confidence": 0.96, "pageNo": 1},
            {"text": "广东检测有限公司", "bbox": [10, 220, 170, 240], "confidence": 0.96, "pageNo": 1},
        ],
        "fields": [],
    }

    extract_ndt_rt_report_fields(result)
    fields = {item["fieldCode"]: item["fieldValue"] for item in result["fields"]}

    assert fields["report_no"] == "RTBG-2021-001"
    assert fields["detection_method"] == "RT"
    assert fields["detection_date"] == "2021年4月"
    assert fields["evaluation_level"] == "II"
    assert fields["conclusion"] == "合格"


def test_ndt_rt_report_extracts_month_date_from_embedded_report_year() -> None:
    result = {
        "fragments": [
            {"text": "射线检测报告书", "bbox": [10, 10, 130, 30], "confidence": 0.96, "pageNo": 1},
            {"text": "报告编号：2021SHZH-014RTBG-01", "bbox": [10, 40, 260, 60], "confidence": 0.96, "pageNo": 1},
            {"text": "二零年四月", "bbox": [10, 70, 170, 90], "confidence": 0.9, "pageNo": 1},
        ],
        "fields": [],
    }

    extract_ndt_rt_report_fields(result)
    fields = {item["fieldCode"]: item["fieldValue"] for item in result["fields"]}

    assert fields["detection_date"] == "2021年4月"


def test_qualification_certificate_extracts_license_fields_from_labeled_lines() -> None:
    result = {
        "fragments": [
            {"text": "中华人民共和国特种设备生产许可证", "bbox": [10, 10, 220, 30], "confidence": 0.96, "pageNo": 1},
            {"text": "许可证编号：TS2710692-2023", "bbox": [10, 40, 220, 60], "confidence": 0.96, "pageNo": 1},
            {"text": "单位名称：广东钢管制造有限公司", "bbox": [10, 70, 260, 90], "confidence": 0.96, "pageNo": 1},
            {"text": "许可项目：压力管道元件制造 钢管制造", "bbox": [10, 100, 320, 120], "confidence": 0.94, "pageNo": 1},
            {"text": "有效期至：2027年6月21日", "bbox": [10, 130, 220, 150], "confidence": 0.95, "pageNo": 1},
            {"text": "发证机关：国家市场监督管理总局", "bbox": [10, 160, 260, 180], "confidence": 0.95, "pageNo": 1},
            {"text": "发证日期：2023年6月22日", "bbox": [10, 190, 220, 210], "confidence": 0.95, "pageNo": 1},
        ],
        "fields": [],
    }

    extract_qualification_certificate_fields(result)
    fields = {item["fieldCode"]: item for item in result["fields"]}

    assert fields["certificate_no"]["fieldValue"] == "TS2710692-2023"
    assert fields["organization_name"]["fieldValue"] == "广东钢管制造有限公司"
    assert fields["license_scope"]["fieldValue"] == "压力管道元件制造 钢管制造"
    assert fields["valid_until"]["fieldValue"] == "2027年6月21日"
    assert fields["issuer"]["fieldValue"] == "国家市场监督管理总局"
    assert fields["issue_date"]["fieldValue"] == "2023年6月22日"
