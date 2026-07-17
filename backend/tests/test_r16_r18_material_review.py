from __future__ import annotations

from apps.ocr_service.profiles import profile_for
from libs.review_orchestrator.r16_facts import build_r16_business_facts
from libs.review_orchestrator.r17_facts import build_r17_business_facts
from libs.review_orchestrator.r18_facts import build_r18_business_facts
from libs.review_tools.r16_tools import (
    evaluate_r16_batch_traceability,
    evaluate_r16_quality_certificate_batch_coverage,
    evaluate_r16_quality_certificate_content,
    evaluate_r16_quality_certificate_design_match,
    evaluate_r16_quality_certificate_form_and_seals,
    evaluate_r16_quality_certificate_results,
    resolve_r16_product_standard_profile,
)
from libs.review_tools.r17_tools import (
    evaluate_r17_acceptance_procedure,
    evaluate_r17_arrival_acceptance_batch_coverage,
    evaluate_r17_nonconformance_control,
    evaluate_r17_sampling_witness_chain,
    resolve_r17_sampling_retest_requirement,
)
from libs.review_tools.r18_tools import (
    classify_r18_material_test_applicability,
    evaluate_r18_material_ndt_report_completeness,
    evaluate_r18_material_report_approval_procedure,
    evaluate_r18_material_retest_report_completeness,
    evaluate_r18_material_test_results_and_traceability,
    resolve_r18_material_test_requirement_profile,
)


def test_r16_complete_quality_certificate_passes_all_deterministic_tools() -> None:
    design_items = [
        {
            "componentItemId": "R16-I-1",
            "manufacturerName": "甲钢管有限公司",
            "productName": "输送流体用无缝钢管",
            "specification": "DN100×6",
            "materialGrade": "20",
            "standardRef": "GB/T 8163-2018",
            "deliveryCondition": "热轧",
            "batchNo": "B-1601",
            "physicalMarkBatchNo": "B-1601",
            "acceptanceLimits": [{"itemCode": "C", "maximum": 0.20}],
            "requiredQuantitativeItems": ["C"],
        }
    ]
    certificates = [
        {
            "certificateId": "QC-1601",
            "manufacturerName": "甲钢管有限公司",
            "productName": "输送流体用无缝钢管",
            "specification": "DN100×6",
            "materialGrade": "20",
            "standardRef": "GB/T8163-2018",
            "deliveryCondition": "热轧",
            "batchNo": "B-1601",
            "documentForm": "原件",
            "manufacturerQualitySealPresent": True,
            "inspectionItems": ["化学成分", "拉伸试验", "水压试验"],
            "testResults": {"C": 0.19},
            "conclusion": "合格",
        }
    ]
    arguments = {"designItems": design_items, "qualityCertificates": certificates}

    outputs = [
        resolve_r16_product_standard_profile(arguments),
        evaluate_r16_quality_certificate_batch_coverage(arguments),
        evaluate_r16_quality_certificate_form_and_seals(arguments),
        evaluate_r16_quality_certificate_design_match(arguments),
        evaluate_r16_quality_certificate_content(arguments),
        evaluate_r16_quality_certificate_results(arguments),
        evaluate_r16_batch_traceability(arguments),
    ]

    assert [item["result"] for item in outputs] == ["passed"] * 7


def test_r16_copy_without_handler_seal_fails_and_unknown_standard_fails_closed() -> None:
    certificate_result = evaluate_r16_quality_certificate_form_and_seals(
        {
            "qualityCertificates": [
                {
                    "certificateId": "QC-COPY",
                    "documentForm": "复印件",
                    "dealerOfficialSealPresent": True,
                    "handlerResponsibleSealPresent": False,
                }
            ]
        }
    )
    standard_result = resolve_r16_product_standard_profile(
        {"designItems": [{"componentItemId": "I-X", "standardRef": "UNKNOWN-STD"}]}
    )

    assert certificate_result["result"] == "failed"
    assert standard_result["result"] == "evidence_insufficient"


def test_r17_acceptance_and_sampling_witness_chain_pass_and_optional_retest_is_not_applicable() -> None:
    design_items = [
        {
            "componentItemId": "R17-I-1",
            "productName": "无缝钢管",
            "specification": "DN100×6",
            "batchNo": "B-1701",
            "requiresSamplingRetest": True,
        }
    ]
    acceptance_records = [
        {
            "recordId": "AR-1701",
            "productName": "无缝钢管",
            "specification": "DN100×6",
            "batchNo": "B-1701",
            "procedureApproved": True,
            "completedSteps": ["质量证明核验", "身份标识核验", "外观检查", "尺寸检查", "结论记录"],
            "signatureRoles": ["验收人员", "接收人员"],
            "conclusion": "合格",
        }
    ]
    witness_records = [
        {"recordId": "WR-1701", "batchNo": "B-1701", "sampleNo": "S-1701", "witnessRoles": ["监检人员"]}
    ]
    retest_reports = [{"reportId": "RR-1701", "batchNo": "B-1701", "sampleNo": "S-1701"}]
    arguments = {
        "designItems": design_items,
        "acceptanceRecords": acceptance_records,
        "witnessRecords": witness_records,
        "samplingRetestReports": retest_reports,
    }

    assert evaluate_r17_arrival_acceptance_batch_coverage(arguments)["result"] == "passed"
    assert evaluate_r17_acceptance_procedure(arguments)["result"] == "passed"
    assert resolve_r17_sampling_retest_requirement(arguments)["result"] == "passed"
    assert evaluate_r17_sampling_witness_chain(arguments)["result"] == "passed"
    assert evaluate_r17_nonconformance_control(arguments)["result"] == "not_applicable"

    optional = {"designItems": [{**design_items[0], "requiresSamplingRetest": False}], "samplingRetestReports": []}
    assert resolve_r17_sampling_retest_requirement(optional)["result"] == "not_applicable"
    assert evaluate_r17_sampling_witness_chain(optional)["result"] == "not_applicable"


def test_r18_conditional_retest_and_material_ndt_pass_complete_reports() -> None:
    design_items = [
        {
            "componentItemId": "R18-I-1",
            "productName": "不锈钢无缝钢管",
            "specification": "DN80×5",
            "batchNo": "B-1801",
            "standardRef": "GB/T 14976-2025",
            "requiresMaterialRetest": True,
            "requiresMaterialNdt": True,
            "requiredRetestItems": ["chemical_composition"],
            "requiredMaterialNdtMethods": ["UT"],
            "acceptanceLimits": [{"reportKind": "retest", "itemCode": "C", "maximum": 0.08}],
        }
    ]
    retest_reports = [
        {
            "reportId": "RR-1801",
            "recordKind": "material_retest",
            "productName": "不锈钢无缝钢管",
            "specification": "DN80×5",
            "batchNo": "B-1801",
            "sampleNo": "S-1801",
            "testItems": ["chemical_composition"],
            "testResults": {"C": 0.06},
            "procedureApproved": True,
            "signatureRoles": ["试验员", "审核", "批准"],
            "conclusion": "合格",
        }
    ]
    ndt_reports = [
        {
            "reportId": "NR-1801",
            "recordKind": "material_ndt",
            "productName": "不锈钢无缝钢管",
            "specification": "DN80×5",
            "batchNo": "B-1801",
            "methods": ["UT"],
            "procedureApproved": True,
            "signatureRoles": ["检测员", "审核", "批准"],
            "conclusion": "合格",
        }
    ]
    arguments = {"designItems": design_items, "retestReports": retest_reports, "materialNdtReports": ndt_reports}

    outputs = [
        classify_r18_material_test_applicability(arguments),
        resolve_r18_material_test_requirement_profile(arguments),
        evaluate_r18_material_retest_report_completeness(arguments),
        evaluate_r18_material_ndt_report_completeness(arguments),
        evaluate_r18_material_report_approval_procedure(arguments),
        evaluate_r18_material_test_results_and_traceability(arguments),
    ]
    assert [item["result"] for item in outputs] == ["passed"] * 6

    not_applicable = {"designItems": [{**design_items[0], "requiresMaterialRetest": False, "requiresMaterialNdt": False}], "retestReports": [], "materialNdtReports": []}
    assert classify_r18_material_test_applicability(not_applicable)["result"] == "not_applicable"
    assert evaluate_r18_material_report_approval_procedure(not_applicable)["result"] == "not_applicable"


def test_r16_r18_fact_builders_route_dedicated_document_types() -> None:
    state = {
        "versions": [
            {"id": "V-MAT", "documentId": "D-MAT", "fileName": "材料表.pdf"},
            {"id": "V-QC", "documentId": "D-QC", "fileName": "质量证明书.pdf"},
            {"id": "V-AR", "documentId": "D-AR", "fileName": "到货验收记录.pdf"},
            {"id": "V-WR", "documentId": "D-WR", "fileName": "抽样见证记录.pdf"},
            {"id": "V-RR", "documentId": "D-RR", "fileName": "材料复验报告.pdf"},
            {"id": "V-NR", "documentId": "D-NR", "fileName": "材料无损检测报告.pdf"},
        ],
        "documents": [],
        "ocr_parse_results": [
            {
                "documentId": "D-MAT", "documentVersionId": "V-MAT", "profileId": "comprehensive_material_list_v1", "documentType": "comprehensive_material_list",
                "tables": [{"normalizedRows": [{"productName": "无缝钢管", "specification": "DN100×6", "materialGrade": "20", "standardRef": "GB/T 8163-2018", "batchNo": "B-1", "requiresSamplingRetest": True, "requiresMaterialRetest": True, "requiresMaterialNdt": True}]}], "fields": [], "fragments": [],
            },
            {
                **_parse("D-QC", "V-QC", "quality_certificate_v1", "quality_certificate", [_field("certificate_no", "QC-1"), _field("product_name", "无缝钢管"), _field("batch_no", "B-1"), _field("manufacturer_quality_seal", True)]),
                "seals": [{"sealText": "某某安装公司公章"}],
            },
            _parse("D-AR", "V-AR", "acceptance_witness_record_v1", "acceptance_witness_record", [_field("record_no", "AR-1"), _field("product_name", "无缝钢管"), _field("batch_no", "B-1")]),
            _parse("D-WR", "V-WR", "sampling_witness_record_v1", "sampling_witness_record", [_field("record_no", "WR-1"), _field("product_name", "无缝钢管"), _field("batch_no", "B-1"), _field("sample_no", "S-1")]),
            _parse("D-RR", "V-RR", "material_retest_report_v1", "material_retest_report", [_field("report_no", "RR-1"), _field("product_name", "无缝钢管"), _field("batch_no", "B-1")]),
            _parse("D-NR", "V-NR", "material_ndt_report_v1", "material_ndt_report", [_field("report_no", "NR-1"), _field("product_name", "无缝钢管"), _field("batch_no", "B-1")]),
        ],
    }
    review_run = {"inputDocumentVersionIds": [item["id"] for item in state["versions"]]}

    r16 = build_r16_business_facts(state, review_run)["r16"]
    r17 = build_r17_business_facts(state, review_run)["r17"]
    r18 = build_r18_business_facts(state, review_run)["r18"]

    assert r16["qualityCertificates"][0]["certificateNo"] == "QC-1"
    assert r16["qualityCertificates"][0]["manufacturerQualitySealPresent"] is True
    assert r16["qualityCertificates"][0]["dealerOfficialSealPresent"] is False
    assert r17["acceptanceRecords"][0]["recordNo"] == "AR-1"
    assert r17["witnessRecords"][0]["recordNo"] == "WR-1"
    assert r17["samplingRetestReports"][0]["reportNo"] == "RR-1"
    assert r18["retestReports"][0]["reportNo"] == "RR-1"
    assert r18["materialNdtReports"][0]["reportNo"] == "NR-1"


def test_new_material_ocr_profiles_are_explicit_and_not_welding_ndt() -> None:
    acceptance = profile_for("acceptance_witness_record")
    sampling_witness = profile_for("sampling_witness_record")
    material_ndt = profile_for("material_ndt_report")

    assert acceptance["profileId"] == "acceptance_witness_record_v1"
    assert "completed_steps" in acceptance["structuredExtraction"]["fields"]
    assert sampling_witness["profileId"] == "sampling_witness_record_v1"
    assert sampling_witness["documentType"] == "sampling_witness_record"
    assert "sample_no" in sampling_witness["requiredFields"]
    assert material_ndt["profileId"] == "material_ndt_report_v1"
    assert material_ndt["documentType"] == "material_ndt_report"
    assert "weld_no" not in material_ndt["structuredExtraction"]["fields"]


def _field(code: str, value: object) -> dict:
    return {"fieldCode": code, "fieldValue": value, "pageNo": 1, "bbox": [10, 10, 100, 30], "confidence": 0.96}


def _parse(document_id: str, version_id: str, profile_id: str, document_type: str, fields: list[dict]) -> dict:
    return {"documentId": document_id, "documentVersionId": version_id, "profileId": profile_id, "documentType": document_type, "tables": [], "fields": fields, "fragments": []}
