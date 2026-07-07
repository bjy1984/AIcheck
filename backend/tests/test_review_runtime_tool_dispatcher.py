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
                "fields": [],
                "tables": [],
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

    certificate = extraction["welderCertificates"][0]
    assert seals["sealCount"] == 1
    assert seals["matchedIssuerSealCount"] == 1
    assert extraction["toolName"] == "extract_welder_certificate"
    assert certificate["fields"]["certificateNo"]["value"] == "510602197603143578"
    assert certificate["fields"]["archiveNo"]["value"] == "TS2100000099937"
    assert certificate["fields"]["issuingAuthority"]["value"] == "沈阳市市场监督管理局"
    assert verification["verificationCount"] == 1
    assert verification["verifications"][0]["matchedIssuerSealCount"] == 1
