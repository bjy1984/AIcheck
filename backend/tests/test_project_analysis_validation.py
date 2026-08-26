from __future__ import annotations

import json

import pytest


def _snapshot() -> dict:
    return {
        "projectAnalysisSnapshotId": "PASNAP-1",
        "projectId": "P-1",
        "nodeIds": [1, 2],
        "nodes": [
            {
                "nodeId": 1,
                "nodeName": "节点一",
                "criteria": "规则一原文",
                "checkMethod": "方法一原文",
                "fileRefs": [
                    {
                        "fileId": "DOC-1",
                        "documentVersionId": "DV-1",
                        "fileName": "一.pdf",
                    }
                ],
            },
            {
                "nodeId": 2,
                "nodeName": "节点二",
                "criteria": "规则二原文",
                "checkMethod": "方法二原文",
                "fileRefs": [
                    {
                        "fileId": "DOC-2",
                        "documentVersionId": "DV-2",
                        "fileName": "二.pdf",
                    }
                ],
            },
        ],
    }


def _payload() -> dict:
    return {
        "project": {
            "projectId": "P-1",
            "projectCode": "p1",
            "projectName": "工程一",
            "includedNodeCount": 2,
            "nodes": _snapshot()["nodes"],
            "fileCorpus": {
                "DOC-1": {
                    "fileId": "DOC-1",
                    "documentVersionId": "DV-1",
                    "fileName": "一.pdf",
                    "fullOcrText": "许可证编号 TS-001\n机构名称 甲公司",
                },
                "DOC-2": {
                    "fileId": "DOC-2",
                    "documentVersionId": "DV-2",
                    "fileName": "二.pdf",
                    "fullOcrText": "报告编号 R-002\n结论 合格",
                },
            },
        }
    }


def _finding(**overrides) -> dict:
    return {
        "findingType": "qualification_match",
        "severity": "low",
        "title": "资质匹配",
        "description": "资质满足要求",
        "confidence": 1.0,
        "suggestedAction": "human_confirm",
        "evidenceRefs": [],
        "ruleRefs": [],
        "kbRefs": [],
        "groundingStatus": "grounded",
        "unsupportedClaims": [],
        "requiresHumanConfirmation": False,
        **overrides,
    }


def test_validator_downgrades_out_of_node_and_non_verbatim_evidence() -> None:
    from libs.project_analysis.validation import validate_project_analysis_output

    model_output = {
        "schemaVersion": "AIAllReviewResult@2.0.0",
        "projectId": "P-1",
        "projectCode": "p1",
        "projectName": "工程一",
        "nodeReviews": [
            {
                "nodeId": 1,
                "nodeName": "节点一",
                "reviewResult": "supported",
                "supportSummary": "满足要求",
                "missingEvidence": [],
                "conflicts": [],
                "risks": [],
                "recommendations": [],
                "findings": [
                    _finding(
                        evidenceRefs=[
                            {
                                "fileId": "DOC-2",
                                "documentVersionId": "DV-2",
                                "fileName": "二.pdf",
                                "pageNo": None,
                                "quotedText": "报告编号 R-002",
                            },
                            {
                                "fileId": "DOC-1",
                                "documentVersionId": "DV-1",
                                "fileName": "一.pdf",
                                "pageNo": None,
                                "quotedText": "许可证编号 TS-001\n机构名称 不存在公司",
                            },
                        ],
                        ruleRefs=[
                            {
                                "source": "configuredRequirements",
                                "text": "必传设计许可证",
                            }
                        ],
                    )
                ],
            },
            {
                "nodeId": 2,
                "nodeName": "节点二",
                "reviewResult": "supported",
                "supportSummary": "报告存在",
                "missingEvidence": [],
                "conflicts": [],
                "risks": [],
                "recommendations": [],
                "findings": [
                    _finding(
                        confidence=0.8,
                        description="报告编号已识别",
                        evidenceRefs=[
                            {
                                "fileId": "DOC-2",
                                "documentVersionId": "DV-2",
                                "fileName": "二.pdf",
                                "pageNo": None,
                                "quotedText": "报告编号 R-002",
                            }
                        ],
                        ruleRefs=[{"source": "criteria", "text": "规则二原文"}],
                        requiresHumanConfirmation=True,
                    )
                ],
            },
        ],
        "projectSummary": {
            "supportedNodeCount": 99,
            "partialNodeCount": 99,
            "insufficientNodeCount": 99,
            "conflictNodeCount": 99,
            "mismatchNodeCount": 99,
            "humanReviewNodeCount": 0,
            "priorityRisks": [],
            "priorityManualActions": [],
        },
        "disclaimer": "以上内容仅作为监检审查提示，不替代最终人工结论。",
    }

    result = validate_project_analysis_output(
        json.dumps(model_output, ensure_ascii=False),
        _snapshot(),
        _payload(),
    )
    invalid = result["nodeReviews"][0]["findings"][0]
    valid = result["nodeReviews"][1]["findings"][0]

    assert invalid["groundingStatus"] == "insufficient_evidence"
    assert invalid["confidence"] == 0.55
    assert invalid["requiresHumanConfirmation"] is True
    assert invalid["suggestedAction"] == "human_confirm"
    assert invalid["evidenceRefs"] == []
    assert {
        "EVIDENCE_FILE_OUTSIDE_NODE",
        "EVIDENCE_QUOTE_NOT_VERBATIM",
        "RULE_REF_SOURCE_INVALID",
    }.issubset({row["code"] for row in invalid["validationFailures"]})
    assert result["nodeReviews"][0]["reviewResult"] == "insufficient_evidence"
    assert valid["groundingStatus"] == "grounded"
    assert valid["evidenceRefs"][0]["fileId"] == "DOC-2"
    assert result["projectSummary"] == {
        "supportedNodeCount": 1,
        "partialNodeCount": 0,
        "insufficientNodeCount": 1,
        "conflictNodeCount": 0,
        "mismatchNodeCount": 0,
        "humanReviewNodeCount": 2,
        "priorityRisks": [],
        "priorityManualActions": [],
    }


@pytest.mark.parametrize(
    "raw_text,error_code",
    [
        ("not-json", "LLM_OUTPUT_INVALID_JSON"),
        (json.dumps([]), "LLM_OUTPUT_INVALID_ENVELOPE"),
        (
            json.dumps(
                {
                    "schemaVersion": "AIAllReviewResult@2.0.0",
                    "projectId": "P-1",
                    "nodeReviews": [{"nodeId": 1}],
                }
            ),
            "PROJECT_ANALYSIS_NODE_SET_MISMATCH",
        ),
    ],
)
def test_validator_rejects_invalid_envelopes(raw_text: str, error_code: str) -> None:
    from libs.project_analysis.validation import (
        ProjectAnalysisOutputError,
        validate_project_analysis_output,
    )

    with pytest.raises(ProjectAnalysisOutputError) as error:
        validate_project_analysis_output(raw_text, _snapshot(), _payload())

    assert error.value.code == error_code
