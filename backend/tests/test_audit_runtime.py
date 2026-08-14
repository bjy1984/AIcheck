from __future__ import annotations

from pathlib import Path

from libs.audit_runtime import (
    audit_runtime_config,
    audit_runtime_for_run,
    audit_runtime_public_config,
)
from libs.review_grounding import apply_grounding_guardrails, grounding_prompt_block
from libs.review_orchestrator.execution import validate_review_evidence_refs

CONFIG_TEXT = """
schemaVersion: aicheck-audit-runtime@1
modeEnv: AICHECK_AUDIT_INPUT_MODE
defaultMode: ocr_llm
modes:
  ocr_llm:
    label: OCR + LLM
    useOcrEvidence: true
    requireEvidenceRefs: true
    groundingPolicy: evidence_only
    evidenceValidationMode: strict
  pure_llm:
    label: Pure LLM
    useOcrEvidence: false
    requireEvidenceRefs: false
    groundingPolicy: llm_only_human_review
    evidenceValidationMode: advisory
aliases:
  llm: pure_llm
  with_ocr: ocr_llm
"""


def write_config(tmp_path: Path) -> Path:
    path = tmp_path / "audit_runtime.yaml"
    path.write_text(CONFIG_TEXT, encoding="utf-8")
    return path


def test_audit_runtime_defaults_to_ocr_llm(tmp_path) -> None:
    config = audit_runtime_config(write_config(tmp_path), env={})

    assert config["mode"] == "ocr_llm"
    assert config["useOcrEvidence"] is True
    assert config["requireEvidenceRefs"] is True


def test_audit_runtime_supports_pure_llm_alias(tmp_path) -> None:
    config = audit_runtime_config(write_config(tmp_path), env={"AICHECK_AUDIT_INPUT_MODE": "llm"})
    public = audit_runtime_public_config(env={"AICHECK_AUDIT_INPUT_MODE": "pure_llm"})
    run_config = audit_runtime_for_run({"auditInputMode": "pure_llm"})

    assert config["mode"] == "pure_llm"
    assert public["groundingPolicy"] == "llm_only_human_review"
    assert run_config["requireEvidenceRefs"] is False


def test_pure_llm_evidence_validation_is_advisory(tmp_path) -> None:
    runtime = audit_runtime_config(write_config(tmp_path), env={"AICHECK_AUDIT_INPUT_MODE": "pure_llm"})

    result = validate_review_evidence_refs(
        [{"id": "FND-1", "evidenceRefs": []}],
        [],
        audit_runtime=runtime,
    )

    assert result["passed"] is True
    assert result["metrics"]["evidenceValidationMode"] == "advisory"
    assert any(item["code"] == "PURE_LLM_REVIEW_ADVISORY_ONLY" for item in result["warnings"])


def test_pure_llm_guardrails_keep_advisory_text_without_evidence_refs() -> None:
    grounding = {
        "groundingPolicy": "llm_only_human_review",
        "groundingStatus": "insufficient_evidence",
        "evidenceLinks": [],
        "documentVersionIds": [],
        "evidenceTextCorpus": [],
    }

    block = grounding_prompt_block(grounding)
    guarded = apply_grounding_guardrails(
        [
            {
                "id": "FND-1",
                "title": "建议复核资料完整性",
                "description": "建议人工复核资料目录、签章和证书有效期。",
                "confidence": 0.88,
                "suggestedAction": "human_confirm",
                "evidenceRefs": [{"evidenceLinkId": "EV-1"}],
            }
        ],
        grounding,
    )

    assert block["strictGroundingPolicy"] == "llm_only_human_review"
    assert guarded[0]["title"] == "建议复核资料完整性"
    assert guarded[0]["sourceMethod"] == "pure_llm_review"
    assert guarded[0]["confidence"] == 0.55
    assert guarded[0]["evidenceRefs"] == []
