from copy import deepcopy

from apps.ocr_service.service import apply_profile_postprocessing, enrich_parse_result
from libs.business_pack import load_business_pack
from libs.ocr.profiles import profile_for, validate_profiles


def source(*lines):
    return {"fields": [], "tables": [], "fragments": [
        {"text": line, "pageNo": index + 1, "bbox": [10, 20, 180, 40], "confidence": .94,
         "sourceEngine": "synthetic_ocr", "coordinateSystem": "pixel"} for index, line in enumerate(lines)]}


def test_profile_routes_explicit_material_type_and_preserves_shadow_policy():
    profile = profile_for(document_type="ndt_procedure")
    assert profile["profileId"] == "ndt_procedure_v1"
    assert profile_for("ndt_procedure")["profileId"] == "ndt_procedure_v1"
    assert profile["structuredExtraction"]["mode"] == "shadow"
    assert not validate_profiles()
    pack = load_business_pack("engineering_inspection_v1")
    material = next(item for item in pack["materialTypes"] if item["code"] == "ndt_procedure")
    assert material["ocrProfileId"] == profile["profileId"]
    assert "referenced_procedure_revision" in material["ocrFieldMappings"]


def test_real_postprocessing_keeps_own_and_referenced_document_revisions_separate():
    result = source("文件编号：PT-INST-01", "版次：B", "引用规程编号：PT-PROC-01", "引用规程版本：A",
                    "检测方法：PT", "乳化剂施加方法：喷洒", "执行标准：NB/T 47013.5-2015")
    original_fragments = deepcopy(result["fragments"])
    apply_profile_postprocessing(result, profile_for("ndt_procedure_v1"))
    fields = {item["fieldCode"]: item for item in result["fields"]}
    assert fields["procedure_no"]["fieldValue"] == "PT-INST-01"
    assert fields["procedure_revision"]["fieldValue"] == "B"
    assert fields["referenced_procedure_revision"]["fieldValue"] == "A"
    assert fields["emulsifier_application"]["fieldValue"] == "喷洒"
    assert fields["referenced_procedure_no"]["pageNo"] == 3
    assert fields["referenced_procedure_no"]["bbox"] == [10, 20, 180, 40]
    assert fields["referenced_procedure_no"]["confidence"] == .94
    assert result["fragments"] == original_fragments
    assert result["tables"] == []  # Raw extraction cannot manufacture business identities or decisions.


def test_no_cross_page_guessing_and_no_reference_number_as_own_number():
    result = source("文件编号：", "PT-UNLABELED", "引用规程编号：PT-PROC-01", "未找到应用记录")
    apply_profile_postprocessing(result, profile_for("ndt_procedure_v1"))
    fields = {item["fieldCode"]: item["fieldValue"] for item in result["fields"]}
    assert "procedure_no" not in fields
    assert "application_status" not in fields
    assert fields["referenced_procedure_no"] == "PT-PROC-01"


def test_conflicting_labels_are_not_resolved_by_first_occurrence():
    for lines in (("文件版本：A", "版次：B"), ("版次：B", "文件版本：A")):
        result = source(*lines)
        apply_profile_postprocessing(result, profile_for("ndt_procedure_v1"))
        assert not any(item["fieldCode"] == "procedure_revision" for item in result["fields"])
        assert any(item["code"] == "NDT_PROCEDURE_LABEL_CONFLICT" for item in result["diagnostics"])


def test_existing_ocr_field_is_not_silently_replaced():
    result = source("版次：B")
    existing = {"fieldCode": "procedure_revision", "fieldValue": "A", "confidence": .6}
    result["fields"] = [deepcopy(existing)]
    apply_profile_postprocessing(result, profile_for("ndt_procedure_v1"))
    assert result["fields"][0]["fieldValue"] == "A"
    assert result["fields"][0]["confidence"] == .6
    assert "field_value_conflict" in result["fields"][0]["qualityFlags"]


def test_enrichment_retains_profile_and_actual_document_version():
    result = source("文件编号：PT-01", "版次：A", "检测方法：PT", "执行标准：NB/T 47013.5-2015")
    before = deepcopy(result)
    output = enrich_parse_result(result, profile=profile_for("ndt_procedure_v1"), document_version_id="FIXED-V1",
                                 business_pack_id="engineering_inspection_v1", model_manifest={})
    assert output["profileId"] == "ndt_procedure_v1"
    assert output["documentVersionId"] == "FIXED-V1"
    assert any(item["fieldCode"] == "procedure_no" for item in output["fields"])
    assert result == before
