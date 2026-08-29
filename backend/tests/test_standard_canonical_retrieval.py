from __future__ import annotations

from typing import Any

from libs.knowledge_retrieval import (
    canonical_clause_candidates,
    knowledge_clause_candidates,
    retrieve_knowledge_clauses,
)


def retrieval_state_with_canonical_conflict() -> dict[str, Any]:
    return {
        "standard_knowledge_records": [
            {
                "id": "SKR-KF-KB-TEST",
                "knowledgeFileId": "KF-KB-TEST",
                "kbVersion": "inspection_kb@test",
                "canonicalVersion": "standard-knowledge-canonical@1",
                "sourceFingerprint": "sha256:test",
                "clauses": [
                    {
                        "id": "SKI-CLAUSE-1",
                        "text": "发布日期 2015-04-02",
                        "authority": "current",
                        "pageNo": 1,
                        "sources": [
                            {"sourceId": "PARSE-NEW", "sourceType": "new_mineru"}
                        ],
                    }
                ],
                "tables": [],
                "equations": [],
            }
        ],
        "knowledge_files": [
            {
                "id": "KF-KB-TEST",
                "sourceType": "standard",
                "documentVersionId": "KDV-TEST-V1",
            }
        ],
        "knowledge_clauses": [
            {
                "id": "KC-OLD",
                "fileId": "KF-KB-TEST",
                "text": "发布日期 2014-01-01",
            }
        ],
        "knowledge_sources": [],
    }


def retrieval_state_with_legacy_only_clause() -> dict[str, Any]:
    state = retrieval_state_with_canonical_conflict()
    state["standard_knowledge_records"][0]["clauses"] = [
        {
            "id": "SKI-CLAUSE-OLD",
            "text": "备案号 61188-2018",
            "authority": "legacy_only",
            "pageNo": 1,
            "sources": [{"sourceId": "PARSE-OLD", "sourceType": "legacy_ocr"}],
        }
    ]
    return state


def retrieval_state_with_canonical_and_old_chunks() -> dict[str, Any]:
    state = retrieval_state_with_canonical_conflict()
    state["knowledge_chunks"] = [
        {
            "id": "CHK-OLD",
            "fileId": "KF-KB-TEST",
            "text": "发布日期 2014-01-01",
        }
    ]
    return state


def test_canonical_current_value_is_retrieved_and_old_conflict_is_not() -> None:
    state = retrieval_state_with_canonical_conflict()

    candidates = canonical_clause_candidates(state)
    texts = [item["text"] for item in candidates]

    assert "2015-04-02" in "\n".join(texts)
    assert "2014-01-01" not in "\n".join(texts)


def test_legacy_only_information_is_retrievable_with_lower_weight() -> None:
    state = retrieval_state_with_legacy_only_clause()

    item = next(
        candidate
        for candidate in canonical_clause_candidates(state)
        if candidate["authority"] == "legacy_only"
    )

    assert item["retrievalWeightTier"] == "legacy_supplemental"
    assert item["formalEvidenceEligible"] is False


def test_legacy_only_candidate_ranks_below_equally_relevant_current_candidate() -> None:
    state = retrieval_state_with_canonical_conflict()
    state["standard_knowledge_records"][0]["clauses"] = [
        {
            "id": "SKI-CLAUSE-LEGACY",
            "text": "压力要求 2.5 MPa",
            "authority": "legacy_only",
            "pageNo": 1,
            "sources": [{"sourceId": "PARSE-OLD", "sourceType": "legacy_ocr"}],
        },
        {
            "id": "SKI-CLAUSE-CURRENT",
            "text": "压力要求 2.5 MPa",
            "authority": "current",
            "pageNo": 1,
            "sources": [{"sourceId": "PARSE-NEW", "sourceType": "new_mineru"}],
        },
    ]

    result = retrieve_knowledge_clauses(state, query="压力要求 2.5 MPa", top_k=2)

    assert [item["canonicalItemId"] for item in result["clauses"]] == [
        "SKI-CLAUSE-CURRENT",
        "SKI-CLAUSE-LEGACY",
    ]
    assert result["clauses"][0]["score"] > result["clauses"][1]["score"]


def test_standard_candidates_are_not_duplicated_when_canonical_exists() -> None:
    state = retrieval_state_with_canonical_and_old_chunks()

    candidates = knowledge_clause_candidates(state)
    ids = [item["canonicalItemId"] for item in candidates if item.get("canonicalItemId")]

    assert len(ids) == len(set(ids))
    assert "2014-01-01" not in "\n".join(item["text"] for item in candidates)


def test_project_file_candidates_remain_when_standard_candidates_are_replaced() -> None:
    state = retrieval_state_with_canonical_and_old_chunks()
    state["knowledge_files"].append(
        {
            "id": "KF-PROJECT-TEST",
            "sourceType": "project",
            "documentVersionId": "PDV-TEST-V1",
        }
    )
    state["knowledge_chunks"].append(
        {
            "id": "CHK-PROJECT",
            "fileId": "KF-PROJECT-TEST",
            "text": "项目设计压力 2.5 MPa",
        }
    )

    texts = [item["text"] for item in knowledge_clause_candidates(state)]

    assert "发布日期 2015-04-02" in texts
    assert "项目设计压力 2.5 MPa" in texts


def test_kb_version_filters_by_knowledge_source_version() -> None:
    state = retrieval_state_with_canonical_conflict()

    assert canonical_clause_candidates(state, kb_version="inspection_kb@test")
    assert not canonical_clause_candidates(
        state, kb_version="standard-knowledge-canonical@1"
    )


def test_canonical_projection_keeps_provenance_and_safe_structure() -> None:
    state = retrieval_state_with_canonical_conflict()
    record = state["standard_knowledge_records"][0]
    record["tables"] = [
        {
            "id": "SKI-TABLE-1",
            "text": "表 1 要求",
            "authority": "current",
            "pageNo": 2,
            "columnNames": ["项目", "要求"],
            "normalizedRows": [{"项目": "压力", "要求": "2.5 MPa"}],
            "headerReliable": True,
            "tableHtml": "<script>alert('unsafe')</script>",
            "sources": [{"sourceId": "TABLE-NEW", "sourceType": "new_mineru"}],
        }
    ]
    record["equations"] = [
        {
            "id": "SKI-EQUATION-1",
            "text": "p = F / A",
            "latex": r"p=\frac{F}{A}",
            "authority": "current",
            "locatorIds": ["SCL-EQ-1"],
            "sources": [{"sourceId": "EQ-NEW", "sourceType": "new_mineru"}],
        }
    ]

    candidates = canonical_clause_candidates(state)
    by_id = {item["canonicalItemId"]: item for item in candidates}
    table = by_id["SKI-TABLE-1"]
    equation = by_id["SKI-EQUATION-1"]

    assert table["canonicalRecordId"] == "SKR-KF-KB-TEST"
    assert table["canonicalVersion"] == "standard-knowledge-canonical@1"
    assert table["sourceFingerprint"] == "sha256:test"
    assert table["sourceIds"] == ["TABLE-NEW"]
    assert table["tableColumns"] == ["项目", "要求"]
    assert table["tableRows"] == [{"项目": "压力", "要求": "2.5 MPa"}]
    assert "tableHtml" not in table
    assert equation["latex"] == r"p=\frac{F}{A}"
    assert equation["formalEvidenceEligible"] is True
