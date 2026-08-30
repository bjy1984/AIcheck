import json
from typing import Any

import pytest

from libs.db.repository import repo
from libs.review_grounding import (
    canonical_grounding_metadata,
    merge_canonical_grounding_metadata,
)
from libs.review_orchestrator import execution
from libs.review_orchestrator.clause_digest import retrieved_clause_digest
from libs.review_orchestrator.execution import (
    _summarize_node_decision,
    compact_retrieval_trace,
    run_step,
    validate_review_references,
)

VALID_SOURCE_FINGERPRINT = f"sha256:{'a' * 64}"


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
            "sourceFingerprint": VALID_SOURCE_FINGERPRINT,
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
            "sourceFingerprint": VALID_SOURCE_FINGERPRINT,
            "pageNo": 1,
        }
    ]


def test_review_grounding_records_canonical_versions_and_items() -> None:
    grounded = canonical_grounding_metadata(canonical_review_fixture())

    assert grounded["canonicalRecordIds"] == ["SKR-KF-KB-TEST"]
    assert grounded["canonicalItemIds"] == ["SKI-CLAUSE-ABC"]
    assert grounded["canonicalVersions"] == ["standard-knowledge-canonical@1"]
    assert grounded["canonicalSourceFingerprints"] == [VALID_SOURCE_FINGERPRINT]


def test_legacy_only_cannot_be_the_only_formal_evidence() -> None:
    grounded = canonical_grounding_metadata(legacy_only_review_fixture())

    assert grounded["formalEvidenceReady"] is False
    assert grounded["blockingReasons"] == ["CANONICAL_LEGACY_ONLY_EVIDENCE"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("authority", None),
        ("authority", "supporting"),
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


@pytest.mark.parametrize(
    ("field", "metadata_key", "value"),
    [
        ("canonicalRecordId", "canonicalRecordIds", None),
        ("canonicalRecordId", "canonicalRecordIds", ""),
        ("canonicalRecordId", "canonicalRecordIds", "   "),
        ("canonicalRecordId", "canonicalRecordIds", {}),
        ("canonicalRecordId", "canonicalRecordIds", []),
        ("canonicalRecordId", "canonicalRecordIds", 123),
        ("canonicalRecordId", "canonicalRecordIds", "BAD-RECORD"),
        ("canonicalItemId", "canonicalItemIds", None),
        ("canonicalItemId", "canonicalItemIds", ""),
        ("canonicalItemId", "canonicalItemIds", "   "),
        ("canonicalItemId", "canonicalItemIds", {}),
        ("canonicalItemId", "canonicalItemIds", []),
        ("canonicalItemId", "canonicalItemIds", 123),
        ("canonicalItemId", "canonicalItemIds", "BAD-ITEM"),
        ("canonicalVersion", "canonicalVersions", None),
        ("canonicalVersion", "canonicalVersions", ""),
        ("canonicalVersion", "canonicalVersions", "   "),
        ("canonicalVersion", "canonicalVersions", {}),
        ("canonicalVersion", "canonicalVersions", []),
        ("canonicalVersion", "canonicalVersions", 123),
        ("canonicalVersion", "canonicalVersions", "canonical version@1"),
        ("canonicalVersion", "canonicalVersions", "canonical@@1"),
        ("sourceFingerprint", "canonicalSourceFingerprints", None),
        ("sourceFingerprint", "canonicalSourceFingerprints", ""),
        ("sourceFingerprint", "canonicalSourceFingerprints", "   "),
        ("sourceFingerprint", "canonicalSourceFingerprints", {}),
        ("sourceFingerprint", "canonicalSourceFingerprints", []),
        ("sourceFingerprint", "canonicalSourceFingerprints", 123),
        ("sourceFingerprint", "canonicalSourceFingerprints", "sha256:test"),
        ("sourceFingerprint", "canonicalSourceFingerprints", f"md5:{'a' * 64}"),
    ],
)
def test_malformed_canonical_identity_is_excluded_from_provenance(
    field: str,
    metadata_key: str,
    value: Any,
) -> None:
    item = {**canonical_review_fixture()[0], field: value}

    grounded = canonical_grounding_metadata([item])

    assert grounded["formalEvidenceReady"] is False
    assert grounded[metadata_key] == []


def test_grounding_merge_does_not_reintroduce_malformed_provenance() -> None:
    merged = merge_canonical_grounding_metadata(
        {
            "canonicalRecordIds": [123, "   ", "SKR-VALID"],
            "canonicalItemIds": [{}, "BAD-ITEM", "SKI-VALID"],
            "canonicalVersions": [[], "bad version", "canonical@1"],
            "canonicalSourceFingerprints": [
                "sha256:test",
                VALID_SOURCE_FINGERPRINT,
            ],
        },
        canonical_grounding_metadata([]),
    )

    assert merged["canonicalRecordIds"] == ["SKR-VALID"]
    assert merged["canonicalItemIds"] == ["SKI-VALID"]
    assert merged["canonicalVersions"] == ["canonical@1"]
    assert merged["canonicalSourceFingerprints"] == [VALID_SOURCE_FINGERPRINT]


@pytest.mark.parametrize(
    ("metadata_key", "value"),
    [
        (metadata_key, value)
        for metadata_key in (
            "canonicalRecordIds",
            "canonicalItemIds",
            "canonicalVersions",
            "canonicalSourceFingerprints",
        )
        for value in (123, {"bad": "value"}, None, "   ", "plain-string")
    ],
)
def test_grounding_merge_treats_scalar_provenance_as_empty(
    metadata_key: str,
    value: Any,
) -> None:
    merged = merge_canonical_grounding_metadata(
        {metadata_key: value},
        canonical_grounding_metadata([]),
    )

    assert merged[metadata_key] == []


def test_grounding_merge_preserves_supported_collections_with_sorted_deduplication() -> None:
    merged = merge_canonical_grounding_metadata(
        {
            "canonicalRecordIds": ("SKR-Z", "SKR-A", "SKR-Z"),
            "canonicalItemIds": {"SKI-Z", "SKI-A"},
            "canonicalVersions": ["canonical@2", "canonical@1", "canonical@2"],
            "canonicalSourceFingerprints": (
                f"sha256:{'b' * 64}",
                VALID_SOURCE_FINGERPRINT,
            ),
        },
        canonical_grounding_metadata([]),
    )

    assert merged["canonicalRecordIds"] == ["SKR-A", "SKR-Z"]
    assert merged["canonicalItemIds"] == ["SKI-A", "SKI-Z"]
    assert merged["canonicalVersions"] == ["canonical@1", "canonical@2"]
    assert merged["canonicalSourceFingerprints"] == [
        VALID_SOURCE_FINGERPRINT,
        f"sha256:{'b' * 64}",
    ]


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
        "sourceFingerprint": f"sha256:{'b' * 64}",
    }

    forward = canonical_grounding_metadata([first, second, first])
    reverse = canonical_grounding_metadata([first, second, first][::-1])

    assert forward == reverse
    assert forward["canonicalRecordIds"] == ["SKR-A", "SKR-KF-KB-TEST"]
    assert forward["canonicalItemIds"] == ["SKI-A", "SKI-CLAUSE-ABC"]


def reference_validation_fixture(
    selected_clauses: list[dict[str, Any]],
    cited_clause_ids: list[str] | None,
    *,
    formal_review: bool = True,
) -> dict[str, Any]:
    kb_ref: dict[str, Any] = {
        "retrievalTraceId": "RTR-1",
        "kbVersion": "inspection_kb@1",
    }
    if cited_clause_ids is not None:
        kb_ref["clauseIds"] = cited_clause_ids
    return validate_review_references(
        [
            {
                "ruleRefs": [{"ruleCode": "RULE-1", "ruleSetVersion": "rules@1"}],
                "kbRefs": [kb_ref],
            }
        ],
        [{"ruleCode": "RULE-1"}],
        [{"retrievalTraceId": "RTR-1", "selectedClauses": selected_clauses}],
        formal_review=formal_review,
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


@pytest.mark.parametrize("clause_ids", [None, []])
def test_formal_reference_gate_requires_nonempty_clause_citation(
    clause_ids: list[str] | None,
) -> None:
    selected = [
        {**legacy_only_review_fixture()[0], "clauseId": "CLAUSE-LEGACY"}
    ]

    validation = reference_validation_fixture(selected, clause_ids)

    assert validation["passed"] is False
    assert validation["failures"] == [
        {
            "code": "CANONICAL_CLAUSE_CITATION_REQUIRED",
            "index": 0,
            "refIndex": 0,
            "retrievalTraceId": "RTR-1",
        }
    ]


def test_nonformal_reference_gate_preserves_empty_clause_citation_semantics() -> None:
    selected = [
        {**legacy_only_review_fixture()[0], "clauseId": "CLAUSE-LEGACY"}
    ]

    validation = reference_validation_fixture(
        selected,
        [],
        formal_review=False,
    )

    assert validation["passed"] is True
    assert validation["failures"] == []


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
    assert result["canonicalSourceFingerprints"] == [VALID_SOURCE_FINGERPRINT]
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


@pytest.mark.parametrize(
    "scalar_provenance",
    [123, {"bad": "value"}, None, "   ", "plain-string"],
)
def test_retrieve_step_ignores_scalar_existing_provenance(
    monkeypatch: Any,
    scalar_provenance: Any,
) -> None:
    clauses = canonical_review_fixture()
    monkeypatch.setattr(
        execution,
        "retrieve_knowledge_clauses",
        lambda *args, **kwargs: {
            "clauses": clauses,
            "trace": {
                "id": "RTR-CANONICAL",
                "retrievalTraceId": "RTR-CANONICAL",
                "selectedClauses": [
                    {**clauses[0], "clauseId": "CLAUSE-CURRENT"}
                ],
            },
        },
    )
    context: dict[str, Any] = {
        "node": {"name": "标准审查"},
        "groundingInput": {
            "summary": {
                "canonicalRecordIds": scalar_provenance,
                "canonicalItemIds": scalar_provenance,
                "canonicalVersions": scalar_provenance,
                "canonicalSourceFingerprints": scalar_provenance,
            }
        },
    }

    run_step(
        {
            "reviewRunId": "RRUN-CANONICAL",
            "businessPackId": "engineering_inspection_v1",
            "nodeId": 24,
            "kbVersion": "inspection_kb@1.0.0",
        },
        "retrieve_knowledge",
        context,
    )

    assert context["groundingInput"]["canonicalRecordIds"] == [
        "SKR-KF-KB-TEST"
    ]
    assert context["groundingInput"]["canonicalItemIds"] == ["SKI-CLAUSE-ABC"]
    assert context["groundingInput"]["canonicalVersions"] == [
        "standard-knowledge-canonical@1"
    ]
    assert context["groundingInput"]["canonicalSourceFingerprints"] == [
        VALID_SOURCE_FINGERPRINT
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
