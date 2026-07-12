from libs.review_orchestrator.execution import ALLOWED_AGENT_TOOLS
from libs.review_orchestrator.runtime_tools import dispatch_runtime_tool, runtime_tool_catalog


def sample_state() -> dict:
    return {
        "ocr_parse_results": [
            {
                "documentVersionId": "DV-WELDER-001",
                "parseResultId": "PARSE-WELDER-001",
                "documentType": "welder_certificate",
                "fragments": [
                    {
                        "pageNo": 1,
                        "text": "\n".join(
                            [
                                "姓名 赵俊祥",
                                "证件编号 510602197603143578",
                                "档案编号 TS2100000099937",
                                "发证机关 沈阳市市场监督管理局",
                                "GTAW-FeⅡ-6G-3/159-FefS-02/11/12 2019.07.25 2023.07.24",
                            ]
                        ),
                        "confidence": 0.91,
                    }
                ],
                "fields": [
                    {
                        "fieldCode": "welder_name",
                        "fieldValue": "赵俊祥",
                        "pageNo": 1,
                        "confidence": 0.91,
                    }
                ],
                "tables": [
                    {
                        "tableId": "T-WELDER-1",
                        "businessSchema": "welder_qualified_item_table",
                        "normalizedRows": [{"operationItemCode": "GTAW-FeⅡ-6G-3/57-FefS-02/11/12"}],
                    }
                ],
                "seals": [
                    {
                        "sealId": "SEAL-001",
                        "sealText": "沈阳市市场监督管理局",
                        "sealType": "issuer_seal",
                        "pageNo": 1,
                        "visualConfidence": 0.9,
                        "ocrConfidence": 0.88,
                    }
                ],
            }
        ]
    }


def test_runtime_tool_catalog_exposes_welder_and_seal_tools() -> None:
    names = {item["name"] for item in runtime_tool_catalog()}

    assert "recognize_document_seals" in names
    assert "extract_welder_certificate" in names
    assert "verify_license_or_certificate" in names
    assert "extract_document_fields" in names
    assert "extract_table_records" in names
    assert "locate_evidence_fragment" in names
    assert "recognize_document_seals" in ALLOWED_AGENT_TOOLS
    assert "extract_structured_fields" in ALLOWED_AGENT_TOOLS
    assert "verify_license_or_certificate" in ALLOWED_AGENT_TOOLS


def test_runtime_tool_dispatcher_extracts_welder_certificate_and_seals() -> None:
    state = sample_state()
    args = {"documentVersionIds": ["DV-WELDER-001"], "materialTypeCode": "welder_certificate"}

    seals = dispatch_runtime_tool(
        state,
        "recognize_document_seals",
        {
            "documentVersionIds": ["DV-WELDER-001"],
            "expectedIssuer": "沈阳市市场监督管理局",
        },
    )
    extraction = dispatch_runtime_tool(state, "extract_welder_certificate", args)
    verification = dispatch_runtime_tool(state, "verify_license_or_certificate", args)
    fields = dispatch_runtime_tool(state, "extract_document_fields", args)
    tables = dispatch_runtime_tool(
        state,
        "extract_table_records",
        {"documentVersionIds": ["DV-WELDER-001"], "businessSchemas": ["welder_qualified_item_table"]},
    )
    evidence = dispatch_runtime_tool(
        state,
        "locate_evidence_fragment",
        {"documentVersionIds": ["DV-WELDER-001"], "queryTerms": ["GTAW"], "minConfidence": 0.8},
    )

    certificate = extraction["welderCertificates"][0]
    assert seals["sealCount"] == 1
    assert seals["matchedIssuerSealCount"] == 1
    assert extraction["toolName"] == "extract_welder_certificate"
    assert certificate["fields"]["certificateNo"]["value"] == "510602197603143578"
    assert certificate["fields"]["archiveNo"]["value"] == "TS2100000099937"
    assert certificate["fields"]["issuingAuthority"]["value"] == "沈阳市市场监督管理局"
    assert verification["verificationCount"] == 1
    assert verification["verifications"][0]["matchedIssuerSealCount"] == 1
    assert fields["fieldCount"] == 1
    assert tables["tableCount"] == 1
    assert evidence["evidenceRefCount"] == 1


def test_r01_design_license_pilot_tools() -> None:
    scope = dispatch_runtime_tool(
        {},
        "check_design_license_scope",
        {"licenseScopes": ["GC1", "GCD"], "requiredPipelineGrades": ["GC2", "GCD"]},
    )
    dates = dispatch_runtime_tool(
        {},
        "check_date_covers",
        {
            "validFrom": "2025-01-01",
            "validUntil": "2027-12-31",
            "periodStart": "2026-03-01",
            "periodEnd": "2026-10-31",
        },
    )
    names = dispatch_runtime_tool(
        {},
        "check_all_equal",
        {
            "normalizer": "organization_name",
            "values": [
                {"source": "license", "value": "华东设计有限公司"},
                {"source": "drawing", "value": "华东设计有限公司"},
            ],
        },
    )

    assert scope["result"] == "passed"
    assert dates["result"] == "passed"
    assert names["result"] == "passed"
    assert scope["outputSchema"] == "deterministic-tool-result-v1"


def test_r12_welder_qualification_coverage_pilot_tool() -> None:
    decoded = dispatch_runtime_tool(
        {},
        "decode_welder_qualification",
        {"qualificationCodes": ["GTAW-FeⅡ-6G-3/57-FefS-02/11/12"]},
    )
    coverage = dispatch_runtime_tool(
        {},
        "check_welder_work_coverage",
        {
            "qualificationCodes": ["GTAW-FeⅡ-6G-3/57-FefS-02/11/12"],
            "workItems": [
                {
                    "weldingMethod": "GTAW",
                    "materialCategory": "FeII",
                    "position": "6G",
                    "thickness": 4.5,
                    "diameter": 89,
                }
            ],
        },
    )
    uncovered = dispatch_runtime_tool(
        {},
        "check_welder_work_coverage",
        {
            "qualificationCodes": ["GTAW-FeⅡ-6G-3/57-FefS-02/11/12"],
            "workItems": [
                {
                    "weldingMethod": "SMAW",
                    "materialCategory": "FeII",
                    "position": "6G",
                    "thickness": 4.5,
                    "diameter": 89,
                }
            ],
        },
    )

    assert decoded["result"] == "passed"
    assert decoded["facts"]["decodedItems"][0]["materialCategory"] == "FEII"
    assert coverage["result"] == "passed"
    assert uncovered["result"] == "failed"


def test_r48_to_r50_pressure_test_pilot_tools() -> None:
    gauges = dispatch_runtime_tool(
        {},
        "check_pressure_gauge_requirements",
        {
            "maxTestPressure": 15,
            "testDate": "2026-06-15",
            "medium": "clean_water",
            "mediumTemperature": 20,
            "ambientTemperature": 25,
            "gauges": [
                {"gaugeId": "PG-1", "validUntil": "2026-12-31", "accuracyClass": 1.6, "rangeMax": 25, "dialDiameter": 150, "atHighestPoint": True},
                {"gaugeId": "PG-2", "validUntil": "2026-11-30", "accuracyClass": 1.0, "rangeMax": 30, "dialDiameter": 150, "atHighestPoint": False},
            ],
        },
    )
    parameters = dispatch_runtime_tool(
        {},
        "check_pressure_test_parameters",
        {
            "method": "liquid",
            "designPressure": 10,
            "testPressure": 15,
            "holdMinutes": 10,
            "testResult": "passed",
            "allowableStressAtTestTemperature": 100,
            "allowableStressAtDesignTemperature": 100,
            "maximumAllowableTestPressure": 18,
        },
    )
    report = dispatch_runtime_tool(
        {},
        "check_pressure_test_report_consistency",
        {
            "report": {
                "standardRef": "TSG D7006-2020",
                "method": "liquid",
                "testPressure": 15,
                "holdMinutes": 10,
                "testResult": "passed",
            },
            "observed": {
                "method": "liquid",
                "testPressure": 15,
                "holdMinutes": 10,
                "testResult": "passed",
            },
        },
    )

    assert gauges["result"] == "passed"
    assert parameters["result"] == "passed"
    assert report["result"] == "passed"


def test_evidence_grounding_gate_requires_locator_and_confidence() -> None:
    passed = dispatch_runtime_tool(
        {},
        "validate_evidence_grounding",
        {
            "facts": [{"factId": "F-1", "confidence": 0.91, "evidenceRefIds": ["E-1"]}],
            "evidenceRefs": [{"evidenceRefId": "E-1", "pageNo": 1, "quotedText": "有效期至 2027-12-31"}],
        },
    )
    failed = dispatch_runtime_tool(
        {},
        "validate_evidence_grounding",
        {
            "facts": [{"factId": "F-1", "confidence": 0.5, "evidenceRefIds": []}],
            "evidenceRefs": [],
        },
    )

    assert passed["result"] == "passed"
    assert passed["outputSchema"] == "evidence-gate-result-v1"
    assert failed["result"] == "evidence_insufficient"
