from __future__ import annotations

import json

import pytest

from libs.db.repository import repo
from libs.integrations.errors import IntegrationServiceError
from libs.review_grounding import apply_grounding_guardrails, build_grounded_review_input
from libs.review_orchestrator.execution import (
    generate_finding_drafts,
    human_decision_for_review_run,
    normalize_llm_findings,
)
from libs.review_orchestrator.readiness import build_review_orchestration_scorecard_v2


def setup_function() -> None:
    repo.reset()


def finding_draft(*, draft_id: str = "FND-DRAFT-001", description: str = "原始 AI 审查发现。") -> dict:
    return {
        "id": draft_id,
        "reviewRunId": "RRUN-P0-001",
        "projectId": "P-2026-HDCP-001",
        "nodeId": 24,
        "findingType": "ai_review_suggestion",
        "severity": "medium",
        "title": "AI 审查草稿",
        "description": description,
        "evidenceRefs": [
            {
                "evidenceLinkId": "EV-001",
                "documentVersionId": "DV-001",
                "pageNo": 1,
                "bbox": [10, 20, 100, 40],
            }
        ],
        "ruleRefs": [{"ruleCode": "RULE-001", "ruleSetVersion": "ruleset-v1"}],
        "kbRefs": [
            {
                "retrievalTraceId": "RTR-001",
                "clauseIds": ["CLAUSE-001"],
                "kbVersion": "inspection_kb@1.0.0",
            }
        ],
        "confidence": 0.82,
        "suggestedAction": "human_confirm",
        "groundingStatus": "grounded",
        "unsupportedClaims": [],
        "requiresHumanConfirmation": True,
        "status": "pending_human_review",
    }


def review_run() -> dict:
    record = {
        "id": "RRUN-P0-001",
        "reviewRunId": "RRUN-P0-001",
        "aiRunId": "AIRUN-P0-001",
        "projectId": "P-2026-HDCP-001",
        "nodeId": 24,
        "agentId": "compliance_review_agent",
        "agentVersion": "1.0.0",
        "promptVersion": "review_prompt@1.0.0",
        "modelAlias": "review-chat",
        "ruleSetVersion": "ruleset-v1",
        "kbVersion": "inspection_kb@1.0.0",
        "status": "waiting_human_review",
        "findingDrafts": [finding_draft()],
        "evidenceLinks": [
            {
                "id": "EV-001",
                "documentVersionId": "DV-001",
                "pageNo": 1,
                "bbox": [10, 20, 100, 40],
                "text": "原始 AI 审查发现，人工修正后的审查发现。",
            }
        ],
    }
    repo.state["review_runs"].insert(0, record)
    repo.state["rule_check_results"].append(
        {"id": "RULE-RESULT-001", "reviewRunId": record["reviewRunId"], "ruleCode": "RULE-001"}
    )
    repo.state["retrieval_traces"].append(
        {
            "id": "RTR-001",
            "retrievalTraceId": "RTR-001",
            "reviewRunId": record["reviewRunId"],
            "selectedClauses": [{"clauseId": "CLAUSE-001"}],
        }
    )
    return record


def llm_context() -> dict:
    return {
        "groundingInput": {
            "groundingStatus": "grounded",
            "groundingPolicy": "evidence_only",
            "documentVersionIds": ["DV-001", "DV-002"],
            "evidenceLinks": [
                {"id": "EV-001", "documentVersionId": "DV-001", "pageNo": 1, "bbox": [1, 2, 30, 40]},
                {"id": "EV-002", "documentVersionId": "DV-002", "pageNo": 2, "bbox": [5, 6, 50, 60]},
            ],
            "evidenceTextCorpus": ["字段 A 待核对", "字段 B 待核对"],
        }
    }


def llm_finding(*, evidence_link_id: str, document_version_id: str, page_no: int) -> dict:
    return {
        "findingType": "ai_review_suggestion",
        "severity": "medium",
        "title": "材料需人工复核",
        "description": "请核对对应字段和原件。",
        "evidenceRefs": [
            {
                "evidenceLinkId": evidence_link_id,
                "documentVersionId": document_version_id,
                "pageNo": page_no,
                "bbox": [1, 2, 30, 40],
            }
        ],
        "ruleRefs": [{"ruleCode": f"RULE-{page_no}", "ruleSetVersion": "ruleset-v1"}],
        "kbRefs": [{"retrievalTraceId": f"RTR-{page_no}", "clauseIds": [f"CLAUSE-{page_no}"]}],
        "confidence": 0.8,
        "suggestedAction": "human_confirm",
        "groundingStatus": "grounded",
        "unsupportedClaims": [],
    }


def test_human_edit_persists_corrected_findings_instead_of_original_draft() -> None:
    run = review_run()

    result = human_decision_for_review_run(
        run["reviewRunId"],
        "edit",
        {
            "comment": "人工修正 finding 表述。",
            "correctedOutput": [{"description": "人工修正后的审查发现。"}],
        },
    )

    assert result["status"] == "edited_by_human"
    persisted = next(item for item in repo.state["review_findings"] if item["reviewRunId"] == run["reviewRunId"])
    assert persisted["description"] == "人工修正后的审查发现。"
    assert persisted["sourceDraftId"] == "FND-DRAFT-001"
    assert persisted["humanEdited"] is True
    assert result["feedback"]["correctedOutput"][0]["description"] == "人工修正后的审查发现。"


def test_invalid_human_edit_fails_before_mutating_review_run() -> None:
    run = review_run()
    findings_before = len(repo.state["review_findings"])
    feedback_before = len(repo.state["ai_feedback"])

    result = human_decision_for_review_run(
        run["reviewRunId"],
        "edit",
        {"comment": "缺少合法修正结果。", "correctedOutput": []},
    )

    assert result["status"] == "invalid_corrected_output"
    assert run["status"] == "waiting_human_review"
    assert len(repo.state["review_findings"]) == findings_before
    assert len(repo.state["ai_feedback"]) == feedback_before


@pytest.mark.parametrize(
    ("content", "reason"),
    [
        ("", "LLM_OUTPUT_EMPTY"),
        ("not-json", "LLM_OUTPUT_INVALID_JSON"),
        (json.dumps([]), "LLM_OUTPUT_INVALID_ENVELOPE"),
        (json.dumps({"findings": []}), "LLM_OUTPUT_EMPTY_FINDINGS"),
        (json.dumps({"findings": ["bad-item"]}), "LLM_OUTPUT_INVALID_FINDING"),
    ],
)
def test_llm_finding_output_fails_closed_for_invalid_payloads(content: str, reason: str) -> None:
    with pytest.raises(IntegrationServiceError) as error:
        normalize_llm_findings({"reviewRunId": "RRUN-P0-001"}, llm_context(), content)

    assert error.value.reason == reason


def test_generate_finding_drafts_rejects_truncated_provider_output(monkeypatch) -> None:
    class FakeClient:
        def chat_sync(self, messages, **kwargs):
            return {
                "id": "chat-truncated",
                "model": "review-chat",
                "choices": [
                    {
                        "finish_reason": "length",
                        "message": {"content": json.dumps({"findings": [llm_finding(evidence_link_id="EV-001", document_version_id="DV-001", page_no=1)]})},
                    }
                ],
                "usage": {"prompt_tokens": 100, "completion_tokens": 1600, "total_tokens": 1700},
            }

    monkeypatch.setattr("libs.review_orchestrator.execution.review_llm_execution_mode", lambda: "litellm")
    monkeypatch.setattr("libs.review_orchestrator.execution.build_review_messages", lambda review_run, context: [])
    monkeypatch.setattr("libs.review_orchestrator.execution.build_review_prompt_shape", lambda review_run, context: {})
    monkeypatch.setattr("libs.review_orchestrator.execution.qwen_runtime_public_config", dict)
    monkeypatch.setattr("libs.review_orchestrator.execution.qwen_runtime_client", lambda: FakeClient())

    with pytest.raises(IntegrationServiceError) as error:
        generate_finding_drafts({"reviewRunId": "RRUN-P0-001", "modelAlias": "review-chat"}, llm_context())

    assert error.value.reason == "LLM_OUTPUT_TRUNCATED"


def test_formal_grounding_does_not_auto_promote_default_evidence_refs() -> None:
    grounding = llm_context()["groundingInput"] | {"reviewMode": "formal"}
    draft = llm_finding(evidence_link_id="", document_version_id="", page_no=1)
    draft["evidenceRefs"] = []

    guarded = apply_grounding_guardrails([draft], grounding)

    assert guarded[0]["evidenceRefs"] == []
    assert "suggestedEvidenceRefs" not in guarded[0]
    assert guarded[0]["groundingStatus"] == "insufficient_evidence"
    assert "EVIDENCE_REFS_MISSING" in {item["code"] for item in guarded[0]["evidenceValidationFailures"]}


def test_advisory_grounding_exposes_default_refs_as_suggestions_only() -> None:
    grounding = llm_context()["groundingInput"] | {"reviewMode": "gap_precheck", "advisoryOnly": True}
    draft = llm_finding(evidence_link_id="", document_version_id="", page_no=1)
    draft["evidenceRefs"] = []

    guarded = apply_grounding_guardrails([draft], grounding)

    assert guarded[0]["evidenceRefs"] == []
    assert [item["evidenceLinkId"] for item in guarded[0]["suggestedEvidenceRefs"]] == ["EV-001", "EV-002"]


def test_grounding_reports_cross_document_invalid_position_and_unsupported_claim() -> None:
    grounding = llm_context()["groundingInput"] | {"reviewMode": "formal"}
    draft = llm_finding(evidence_link_id="EV-001", document_version_id="DV-002", page_no=0)
    draft["title"] = "许可证 ABC-9999 已确认有效"
    draft["evidenceRefs"][0]["bbox"] = [10, 10, 5, 5]

    guarded = apply_grounding_guardrails([draft], grounding)

    codes = {item["code"] for item in guarded[0]["evidenceValidationFailures"]}
    assert "EVIDENCE_REF_CROSS_DOCUMENT" in codes
    assert "UNSUPPORTED_CLAIM" in codes
    assert guarded[0]["groundingStatus"] == "insufficient_evidence"


def test_grounding_reports_invalid_page_bbox_and_exact_missing_input_version() -> None:
    grounding = llm_context()["groundingInput"] | {"reviewMode": "formal"}
    draft = llm_finding(evidence_link_id="", document_version_id="DV-001", page_no=0)
    draft["evidenceRefs"][0]["bbox"] = [1, 2, 1, 4]

    guarded = apply_grounding_guardrails([draft], grounding)
    codes = {item["code"] for item in guarded[0]["evidenceValidationFailures"]}

    assert {"EVIDENCE_REF_PAGE_INVALID", "EVIDENCE_REF_BBOX_INVALID", "EVIDENCE_REF_POSITION_INVALID"} <= codes

    built = build_grounded_review_input(
        {
            "extracted_fields": [
                {
                    "id": "FIELD-1",
                    "documentVersionId": "DV-001",
                    "fieldName": "许可证",
                    "fieldValue": "ABC-001",
                    "pageNo": 1,
                    "bbox": [1, 2, 30, 40],
                    "confidence": 0.99,
                }
            ],
            "ocr_parse_results": [],
            "evidence_links": [
                {
                    "id": "EV-001",
                    "documentVersionId": "DV-001",
                    "quotedText": "许可证 ABC-001",
                    "pageNo": 1,
                    "bbox": [1, 2, 30, 40],
                }
            ],
        },
        {"DV-001", "DV-002"},
    )
    version_issue = next(item for item in built["blockingIssues"] if item["code"] == "OCR_GROUNDING_DOCUMENT_VERSION_MISSING")
    assert version_issue["documentVersionIds"] == ["DV-002"]
    assert built["groundingStatus"] == "insufficient_evidence"


def test_legacy_grounding_keeps_opt_in_default_ref_promotion_for_compatibility() -> None:
    grounding = llm_context()["groundingInput"] | {"allowLegacyEvidenceRefPromotion": True}
    draft = llm_finding(evidence_link_id="", document_version_id="", page_no=1)
    draft["evidenceRefs"] = []

    guarded = apply_grounding_guardrails([draft], grounding)

    assert guarded[0]["evidenceRefs"][0]["evidenceLinkId"] == "EV-001"


def test_scorecard_v2_uses_approved_weights_and_mandatory_gates() -> None:
    finding = finding_draft()
    run = {
        "workflowEngine": "temporal",
        "workflowType": "ReviewRunWorkflow",
        "workflowId": "review-run-RRUN-P0-001",
        "graphRunner": "langgraph",
        "graphExecution": {"checkpointer": "postgres"},
        "inputHash": "in",
        "outputHash": "out",
        "inputDocumentVersionIds": ["DV-001"],
        "qualityGate": {"passed": True},
        "findingDrafts": [finding],
        "status": "waiting_human_review",
        "sensitivePayloadPolicy": {"rawTextStorage": "postgres_minio_with_fde_grants"},
        "forbiddenTools": ["approve_review", "issue_formal_correction", "change_project_status", "delete_document"],
    }
    nodes = [
        {"nodeKey": key, "status": "succeeded"}
        for key in [
            "load_context",
            "load_ocr_result",
            "run_rule_engine",
            "retrieve_knowledge",
            "build_prompt",
            "llm_generate_findings",
            "schema_validation",
            "evidence_validation",
            "reference_validation",
            "critic_review",
            "quality_gate",
            "persist_drafts",
        ]
    ]
    graph = {
        "nodes": nodes,
        "artifactSummary": {"ruleCheckResults": 1, "retrievalTraces": 1, "validationFailures": 0},
    }
    temporal = {"historyPolicy": "ids_hashes_versions_only", "payloadCodecRequired": True}

    card = build_review_orchestration_scorecard_v2(review_run=run, graph_view=graph, temporal_history=temporal)

    assert card["weights"] == {
        "detection": 30,
        "evidence": 25,
        "retrieval": 15,
        "execution_provenance": 20,
        "backend_release": 10,
    }
    assert card["score"] == 100
    assert card["ok"] is True

    run["findingDrafts"][0]["evidenceRefs"] = []
    card = build_review_orchestration_scorecard_v2(review_run=run, graph_view=graph, temporal_history=temporal)
    assert card["score"] >= 85
    assert card["ok"] is False
    assert next(gate for gate in card["mandatoryGates"] if gate["name"] == "exact_input_evidence_refs")["passed"] is False


def test_llm_finding_output_preserves_claim_specific_references() -> None:
    content = json.dumps(
        {
            "findings": [
                llm_finding(evidence_link_id="EV-001", document_version_id="DV-001", page_no=1),
                llm_finding(evidence_link_id="EV-002", document_version_id="DV-002", page_no=2),
            ]
        },
        ensure_ascii=False,
    )

    drafts = normalize_llm_findings({"reviewRunId": "RRUN-P0-001"}, llm_context(), content)

    assert drafts[0]["evidenceRefs"][0]["evidenceLinkId"] == "EV-001"
    assert drafts[1]["evidenceRefs"][0]["evidenceLinkId"] == "EV-002"
    assert drafts[0]["ruleRefs"][0]["ruleCode"] == "RULE-1"
    assert drafts[1]["kbRefs"][0]["retrievalTraceId"] == "RTR-2"
