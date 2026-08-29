import json
from typing import Any

import pytest

from libs.db.repository import repo
from libs.review_grounding import canonical_grounding_metadata
from libs.review_orchestrator import execution
from libs.review_orchestrator.clause_digest import retrieved_clause_digest
from libs.review_orchestrator.execution import (
    _summarize_node_decision,
    compact_retrieval_trace,
    run_step,
    validate_review_references,
)


def setup_function() -> None:
    repo.reset()


def canonical_review_fixture() -> list[dict[str, Any]]:
    return [
        {
            "id": "CLAUSE-CURRENT",
            "text": "当前条款",
            "authority": "current",
            "canonicalRecordId": "SKR-KF-KB-TEST",
            "canonicalItemId": "SKI-CLAUSE-ABC",
            "canonicalVersion": "standard-knowledge-canonical@1",
            "sourceFingerprint": "sha256:test",
            "pageNo": 7,
        }
    ]


def legacy_only_review_fixture() -> list[dict[str, Any]]:
    return [
        {
            "id": "CLAUSE-LEGACY",
            "text": "旧独有补充",
            "authority": "legacy_only",
            "canonicalRecordId": "SKR-KF-KB-TEST",
            "canonicalItemId": "SKI-CLAUSE-OLD",
            "canonicalVersion": "standard-knowledge-canonical@1",
            "sourceFingerprint": "sha256:test",
            "pageNo": 1,
        }
    ]


def test_review_grounding_records_canonical_versions_and_items() -> None:
    grounded = canonical_grounding_metadata(canonical_review_fixture())

    assert grounded["canonicalRecordIds"] == ["SKR-KF-KB-TEST"]
    assert grounded["canonicalItemIds"] == ["SKI-CLAUSE-ABC"]
    assert grounded["canonicalVersions"] == ["standard-knowledge-canonical@1"]
    assert grounded["canonicalSourceFingerprints"] == ["sha256:test"]


def test_legacy_only_cannot_be_the_only_formal_evidence() -> None:
    grounded = canonical_grounding_metadata(legacy_only_review_fixture())

    assert grounded["formalEvidenceReady"] is False
    assert grounded["blockingReasons"] == ["CANONICAL_LEGACY_ONLY_EVIDENCE"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("authority", None),
        ("authority", "supporting"),
        ("canonicalRecordId", None),
        ("canonicalItemId", None),
        ("canonicalVersion", None),
        ("sourceFingerprint", None),
        ("formalEvidenceEligible", False),
    ],
)
def test_malformed_or_ineligible_canonical_item_is_not_formally_ready(
    field: str,
    value: Any,
) -> None:
    item = {
        **canonical_review_fixture()[0],
        "formalEvidenceEligible": True,
        field: value,
    }

    grounded = canonical_grounding_metadata([item])

    assert grounded["formalEvidenceReady"] is False
    assert grounded["blockingReasons"] == []


def test_legacy_canonical_with_usable_noncanonical_evidence_is_formally_ready() -> None:
    grounded = canonical_grounding_metadata(
        [
            *legacy_only_review_fixture(),
            {
                "id": "CLAUSE-NONCANONICAL",
                "authority": "current",
                "formalEvidenceEligible": True,
            },
        ]
    )

    assert grounded["formalEvidenceReady"] is True
    assert grounded["blockingReasons"] == []


def test_noncanonical_only_readiness_is_unchanged() -> None:
    grounded = canonical_grounding_metadata(
        [{"id": "CLAUSE-NONCANONICAL", "formalEvidenceEligible": True}]
    )

    assert grounded["canonicalRecordIds"] == []
    assert grounded["formalEvidenceReady"] is True
    assert grounded["blockingReasons"] == []


def test_canonical_metadata_is_deduplicated_and_deterministically_ordered() -> None:
    first = canonical_review_fixture()[0]
    second = {
        **first,
        "canonicalRecordId": "SKR-A",
        "canonicalItemId": "SKI-A",
        "canonicalVersion": "canonical@0",
        "sourceFingerprint": "sha256:a",
    }

    forward = canonical_grounding_metadata([first, second, first])
    reverse = canonical_grounding_metadata([first, second, first][::-1])

    assert forward == reverse
    assert forward["canonicalRecordIds"] == ["SKR-A", "SKR-KF-KB-TEST"]
    assert forward["canonicalItemIds"] == ["SKI-A", "SKI-CLAUSE-ABC"]


def reference_validation_fixture(
    selected_clauses: list[dict[str, Any]],
    cited_clause_ids: list[str],
) -> dict[str, Any]:
    return validate_review_references(
        [
            {
                "ruleRefs": [{"ruleCode": "RULE-1", "ruleSetVersion": "rules@1"}],
                "kbRefs": [
                    {
                        "retrievalTraceId": "RTR-1",
                        "clauseIds": cited_clause_ids,
                        "kbVersion": "inspection_kb@1",
                    }
                ],
            }
        ],
        [{"ruleCode": "RULE-1"}],
        [{"retrievalTraceId": "RTR-1", "selectedClauses": selected_clauses}],
    )


def test_formal_reference_gate_rejects_legacy_citation_from_mixed_trace() -> None:
    selected = [
        {**canonical_review_fixture()[0], "clauseId": "CLAUSE-CURRENT"},
        {**legacy_only_review_fixture()[0], "clauseId": "CLAUSE-LEGACY"},
    ]

    validation = reference_validation_fixture(selected, ["CLAUSE-LEGACY"])

    assert validation["passed"] is False
    assert validation["failures"] == [
        {
            "code": "CANONICAL_LEGACY_ONLY_EVIDENCE",
            "index": 0,
            "clauseIds": ["CLAUSE-LEGACY"],
        }
    ]


def test_formal_reference_gate_accepts_current_canonical_citation() -> None:
    selected = [
        {**canonical_review_fixture()[0], "clauseId": "CLAUSE-CURRENT"},
        {**legacy_only_review_fixture()[0], "clauseId": "CLAUSE-LEGACY"},
    ]

    validation = reference_validation_fixture(selected, ["CLAUSE-CURRENT"])

    assert validation["passed"] is True
    assert validation["failures"] == []


def test_formal_reference_gate_accepts_usable_noncanonical_citation_basis() -> None:
    selected = [
        {**legacy_only_review_fixture()[0], "clauseId": "CLAUSE-LEGACY"},
        {
            "clauseId": "CLAUSE-NONCANONICAL",
            "formalEvidenceEligible": True,
        },
    ]

    validation = reference_validation_fixture(
        selected,
        ["CLAUSE-LEGACY", "CLAUSE-NONCANONICAL"],
    )

    assert validation["passed"] is True
    assert validation["failures"] == []


def test_reference_failure_deduplicates_and_sorts_cited_clause_ids() -> None:
    selected = [
        {**legacy_only_review_fixture()[0], "clauseId": "CLAUSE-Z"},
        {
            **legacy_only_review_fixture()[0],
            "clauseId": "CLAUSE-A",
            "canonicalItemId": "SKI-CLAUSE-A",
        },
    ]

    validation = reference_validation_fixture(
        selected,
        ["CLAUSE-Z", "CLAUSE-A", "CLAUSE-Z"],
    )

    assert validation["failures"][0]["clauseIds"] == ["CLAUSE-A", "CLAUSE-Z"]


def test_reference_gate_rejects_clause_when_selected_trace_catalog_is_empty() -> None:
    validation = reference_validation_fixture([], ["CLAUSE-NOT-SELECTED"])

    assert any(
        failure["code"] == "KB_CLAUSE_NOT_IN_TRACE"
        for failure in validation["failures"]
    )


def test_prompt_clause_catalog_includes_compact_formal_authority() -> None:
    clause = {
        **canonical_review_fixture()[0],
        "clauseId": "CLAUSE-CURRENT",
        "formalEvidenceEligible": True,
    }

    digest = retrieved_clause_digest([clause])

    assert digest[0]["canonicalItemId"] == "SKI-CLAUSE-ABC"
    assert digest[0]["authority"] == "current"
    assert digest[0]["formalEvidenceEligible"] is True


def test_retrieve_step_persists_canonical_grounding_without_clause_text(
    monkeypatch: Any,
) -> None:
    clauses = canonical_review_fixture()
    trace_clause = {**clauses[0], "clauseId": clauses[0]["id"]}
    monkeypatch.setattr(
        execution,
        "retrieve_knowledge_clauses",
        lambda *args, **kwargs: {
            "clauses": clauses,
            "trace": {
                "id": "RTR-CANONICAL",
                "retrievalTraceId": "RTR-CANONICAL",
                "selectedClauses": [trace_clause],
            },
        },
    )
    context: dict[str, Any] = {
        "node": {"name": "标准审查"},
        "groundingInput": {"summary": {}},
    }

    result = run_step(
        {
            "reviewRunId": "RRUN-CANONICAL",
            "businessPackId": "engineering_inspection_v1",
            "nodeId": 24,
            "kbVersion": "inspection_kb@1.0.0",
        },
        "retrieve_knowledge",
        context,
    )

    persisted = repo.state["retrieval_traces"][-1]
    assert persisted["canonicalItemIds"] == ["SKI-CLAUSE-ABC"]
    assert context["groundingInput"]["canonicalVersions"] == ["standard-knowledge-canonical@1"]
    assert context["groundingInput"]["summary"]["formalEvidenceReady"] is True
    assert result["canonicalSourceFingerprints"] == ["sha256:test"]
    assert "当前条款" not in json.dumps(result, ensure_ascii=False)


def test_retrieve_step_preserves_existing_noncanonical_formal_readiness(
    monkeypatch: Any,
) -> None:
    clauses = legacy_only_review_fixture()
    monkeypatch.setattr(
        execution,
        "retrieve_knowledge_clauses",
        lambda *args, **kwargs: {
            "clauses": clauses,
            "trace": {
                "id": "RTR-LEGACY",
                "retrievalTraceId": "RTR-LEGACY",
                "selectedClauses": [
                    {**clauses[0], "clauseId": "CLAUSE-LEGACY"}
                ],
            },
        },
    )
    context: dict[str, Any] = {
        "node": {"name": "标准审查"},
        "groundingInput": {
            "groundingStatus": "grounded",
            "blockingReasons": ["EXISTING_NONCANONICAL_WARNING"],
            "summary": {"groundingStatus": "grounded"},
        },
    }

    run_step(
        {
            "reviewRunId": "RRUN-LEGACY",
            "businessPackId": "engineering_inspection_v1",
            "nodeId": 24,
            "kbVersion": "inspection_kb@1.0.0",
        },
        "retrieve_knowledge",
        context,
    )

    assert context["groundingInput"]["formalEvidenceReady"] is True
    assert context["groundingInput"]["blockingReasons"] == [
        "EXISTING_NONCANONICAL_WARNING"
    ]


def test_review_input_summary_aggregates_canonical_metadata_without_clause_text() -> None:
    raw_trace = {
        "retrievalTraceId": "RTR-CANONICAL",
        "selectedClauses": [{**canonical_review_fixture()[0], "clauseId": "CLAUSE-CURRENT"}],
    }
    compact_trace = compact_retrieval_trace(raw_trace)

    summary = _summarize_node_decision(
        {"reviewRunId": "RRUN-CANONICAL"},
        {
            "nodeKey": "retrieve_knowledge",
            "sequence": 4,
            "status": "succeeded",
        },
        tool_calls=[],
        rule_results=[],
        retrieval_traces=[compact_trace],
        finding_drafts=[],
    )

    assert compact_trace["canonicalRecordIds"] == ["SKR-KF-KB-TEST"]
    assert summary["inputSummary"]["canonicalItemIds"] == ["SKI-CLAUSE-ABC"]
    assert summary["inputSummary"]["legacySupplementalCount"] == 0
    assert "当前条款" not in json.dumps(summary, ensure_ascii=False)
