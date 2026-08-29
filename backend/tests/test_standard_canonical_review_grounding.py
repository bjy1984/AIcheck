import json
from typing import Any

from libs.db.repository import repo
from libs.review_grounding import canonical_grounding_metadata
from libs.review_orchestrator import execution
from libs.review_orchestrator.execution import (
    _summarize_node_decision,
    compact_retrieval_trace,
    run_step,
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
