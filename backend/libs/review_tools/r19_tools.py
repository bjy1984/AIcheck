from __future__ import annotations

from typing import Any

from libs.review_orchestrator.r19_agent import validate_r19_semantic_submission


def validate_r19_semantic_judgment(arguments: dict[str, Any]) -> dict[str, Any]:
    """Validate an LLM-authored R19 judgment without replacing its business result."""

    judgment = arguments.get("judgment")
    known_ids = {
        str(item)
        for item in arguments.get("knownEvidenceRefIds") or []
        if str(item).strip()
    }
    if not isinstance(judgment, dict):
        return {
            "status": "succeeded",
            "result": "evidence_insufficient",
            "reasonCodes": ["R19_SEMANTIC_JUDGMENT_MISSING"],
            "errors": ["judgment_must_be_object"],
            "validatedJudgment": None,
        }
    expected_id = str(arguments.get("atomicCheckId") or judgment.get("atomicCheckId") or "")
    expected_ids = {f"AC-R19-{index:02d}" for index in range(1, 9)}
    if expected_id not in expected_ids:
        return {
            "status": "succeeded",
            "result": "evidence_insufficient",
            "reasonCodes": ["R19_ATOMIC_CHECK_ID_INVALID"],
            "errors": ["atomicCheckId_must_be_registered_r19_atomic_check"],
            "validatedJudgment": None,
        }
    synthetic = []
    for index in range(1, 9):
        atomic_id = f"AC-R19-{index:02d}"
        if atomic_id == expected_id:
            synthetic.append(judgment)
            continue
        synthetic.append(
            {
                "atomicCheckId": atomic_id,
                "result": "evidence_insufficient",
                "explanation": "schema validation placeholder",
                "clauseRefs": ["schema-validation-only"],
                "missingFacts": ["not_submitted_in_this_single-judgment_validation"],
                "confidence": 0.0,
            }
        )
    validation = validate_r19_semantic_submission(
        {"atomicJudgments": synthetic},
        known_evidence_ref_ids=known_ids,
        evidence_index=arguments.get("evidenceIndex") if isinstance(arguments.get("evidenceIndex"), dict) else None,
    )
    expected = next(
        (
            item
            for item in validation.get("atomicJudgments") or []
            if item.get("atomicCheckId") == expected_id
        ),
        None,
    )
    relevant_errors = [
        item
        for item in validation.get("errors") or []
        if item.startswith(f"judgment_{int(expected_id[-2:])}_")
        or item == "every_r19_atomic_check_requires_one_judgment"
    ]
    return {
        "status": "succeeded",
        "result": "passed" if expected and not relevant_errors else "evidence_insufficient",
        "reasonCodes": [] if expected and not relevant_errors else ["R19_SEMANTIC_JUDGMENT_INVALID"],
        "errors": relevant_errors,
        "validatedJudgment": expected,
        "businessResult": (expected or {}).get("result"),
        "validatorVersion": "r19-semantic-judgment-v1",
    }
