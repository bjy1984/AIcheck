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


def test_old_evidence_link_for_replaced_standard_clause_is_not_reintroduced() -> None:
    state = retrieval_state_with_canonical_conflict()
    state["evidence_links"] = [
        {
            "id": "EL-OLD",
            "objectType": "knowledgeClause",
            "objectId": "KC-OLD",
            "quotedText": "发布日期 2014-01-01",
        }
    ]

    texts = "\n".join(item["text"] for item in knowledge_clause_candidates(state))

    assert "2015-04-02" in texts
    assert "2014-01-01" not in texts


def test_disabled_standard_evidence_link_cannot_bypass_file_or_source_policy() -> None:
    for disable_source in (False, True):
        state = retrieval_state_with_canonical_conflict()
        state["evidence_links"] = [
            {
                "id": "EL-OLD-DISABLED",
                "objectType": "knowledgeClause",
                "objectId": "KC-OLD",
                "quotedText": "发布日期 2014-01-01",
            }
        ]
        if disable_source:
            state["knowledge_files"][0]["sourceId"] = "KS-DISABLED"
            state["knowledge_sources"] = [
                {
                    "id": "KS-DISABLED",
                    "sourceType": "standard",
                    "status": "disabled",
                }
            ]
        else:
            state["knowledge_files"][0]["indexEnabled"] = False

        assert knowledge_clause_candidates(state) == []


def test_empty_or_malformed_canonical_record_keeps_old_fallback_searchable() -> None:
    for clauses in ([], [{"text": "没有稳定标识的异常条款"}]):
        state = retrieval_state_with_canonical_conflict()
        state["standard_knowledge_records"][0]["clauses"] = clauses

        candidates = knowledge_clause_candidates(state)

        assert [item["clauseId"] for item in candidates] == ["KC-OLD"]


def test_version_filtered_canonical_record_keeps_old_fallback_searchable() -> None:
    state = retrieval_state_with_canonical_conflict()

    candidates = knowledge_clause_candidates(state, kb_version="inspection_kb@other")

    assert [item["clauseId"] for item in candidates] == ["KC-OLD"]


def test_single_match_legacy_only_candidate_remains_searchable() -> None:
    state = retrieval_state_with_legacy_only_clause()

    result = retrieve_knowledge_clauses(state, query="61188-2018", top_k=1)

    assert result["clauses"][0]["canonicalItemId"] == "SKI-CLAUSE-OLD"
    assert result["clauses"][0]["score"] > 0
    assert result["clauses"][0]["retrievalMode"] != "clause_fallback"
    assert "61188-2018" in result["clauses"][0]["text"]


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


def test_project_file_canonical_record_is_rejected_without_suppressing_chunk() -> None:
    state = retrieval_state_with_canonical_conflict()
    state["knowledge_files"] = [
        {
            "id": "KF-KB-TEST",
            "sourceType": "project",
            "sourceId": "KS-PROJECT-FILE",
            "contextType": "project_material",
            "documentVersionId": "KDV-TEST-V1",
        }
    ]
    state["knowledge_clauses"] = []
    state["knowledge_chunks"] = [
        {
            "id": "CHK-PROJECT-ONLY",
            "fileId": "KF-KB-TEST",
            "text": "项目文件厚度要求 12 mm",
            "contextType": "project_material",
        }
    ]

    candidates = knowledge_clause_candidates(state)

    assert canonical_clause_candidates(state) == []
    assert [item["clauseId"] for item in candidates] == ["CHK-PROJECT-ONLY"]
    assert candidates[0]["text"] == "项目文件厚度要求 12 mm"


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
            "cells": [{"row": 0, "column": 0, "text": "项目"}],
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
    assert table["tableCells"] == [{"row": 0, "column": 0, "text": "项目"}]
    assert "tableHtml" not in table
    assert equation["latex"] == r"p=\frac{F}{A}"
    assert equation["formalEvidenceEligible"] is True

    trace_table = next(
        item
        for item in retrieve_knowledge_clauses(state, query="表 1 要求", top_k=3)[
            "trace"
        ]["selectedClauses"]
        if item["canonicalItemId"] == "SKI-TABLE-1"
    )
    assert trace_table["tableCells"] == [
        {"row": 0, "column": 0, "text": "项目"}
    ]
    assert "tableHtml" not in trace_table


def test_structured_only_table_and_equation_build_safe_searchable_text() -> None:
    state = retrieval_state_with_canonical_conflict()
    record = state["standard_knowledge_records"][0]
    record["clauses"] = []
    record["tables"] = [
        {
            "id": "SKI-TABLE-STRUCTURED-ONLY",
            "caption": "表 2 设计参数",
            "columnNames": ["项目", "要求"],
            "normalizedRows": [{"项目": "厚度", "要求": "12 mm"}],
            "cells": [{"row": 0, "column": 0, "text": "厚度"}],
            "authority": "current",
            "sources": [{"sourceId": "TABLE-ONLY", "sourceType": "new_mineru"}],
        }
    ]
    record["equations"] = [
        {
            "id": "SKI-EQUATION-STRUCTURED-ONLY",
            "latex": r"p=\frac{F}{A}",
            "authority": "current",
            "sources": [{"sourceId": "EQ-ONLY", "sourceType": "new_mineru"}],
        }
    ]

    candidates = canonical_clause_candidates(state)
    by_id = {item["canonicalItemId"]: item for item in candidates}
    table = by_id["SKI-TABLE-STRUCTURED-ONLY"]
    equation = by_id["SKI-EQUATION-STRUCTURED-ONLY"]

    assert "表 2 设计参数" in table["text"]
    assert "12 mm" in table["text"]
    assert table["tableRows"] == [{"项目": "厚度", "要求": "12 mm"}]
    assert table["tableCells"] == [{"row": 0, "column": 0, "text": "厚度"}]
    assert equation["text"] == r"p=\frac{F}{A}"
    assert equation["latex"] == r"p=\frac{F}{A}"

    table_trace = retrieve_knowledge_clauses(state, query="12 mm", top_k=2)["trace"]
    selected_table = next(
        item
        for item in table_trace["selectedClauses"]
        if item["canonicalItemId"] == "SKI-TABLE-STRUCTURED-ONLY"
    )
    assert selected_table["tableRows"] == [
        {"项目": "厚度", "要求": "12 mm"}
    ]
    assert selected_table["tableCells"] == [
        {"row": 0, "column": 0, "text": "厚度"}
    ]
    assert "tableHtml" not in selected_table


def test_canonical_relations_are_projected_as_stable_retrieval_candidates() -> None:
    state = retrieval_state_with_canonical_conflict()
    record = state["standard_knowledge_records"][0]
    record["normativeReferences"] = [
        {
            "id": "SKI-REFERENCE-1",
            "sourceStandardCode": "NB/T 47013.10-2015",
            "sourceClauseNo": "4.2",
            "targetStandardCode": "GB/T 9445-2015",
            "targetClauseNo": "6.1",
            "text": "GB/T 9445-2015 6.1",
            "authority": "current",
            "sources": [
                {"sourceId": "REF-NEW", "sourceType": "standard_reference"}
            ],
        }
    ]
    record["replacementRelations"] = [
        {
            "id": "SKI-REPLACEMENT-1",
            "sourceStandardCode": "NB/T 47013.10-2015",
            "targetStandardCode": "NB/T 47013.10-2026",
            "purpose": "replacedBy",
            "text": "replacedBy:NB/T 47013.10-2026",
            "authority": "current",
            "sources": [
                {"sourceId": "CATALOG-NEW", "sourceType": "standard_catalog"}
            ],
        }
    ]
    record["businessRelations"] = [
        {
            "id": "SKI-BUSINESS-1",
            "targetStandardCode": "NB/T 47013.10-2015",
            "targetClauseNo": "4.2",
            "purpose": "RULE-24",
            "text": "RULE-24|NB/T 47013.10-2015|4.2",
            "nodeIds": [24],
            "materialTypes": ["ndt_report"],
            "authority": "current",
            "sources": [
                {"sourceId": "RULE-24", "sourceType": "business_rule"}
            ],
        }
    ]

    candidates = canonical_clause_candidates(state)
    relations = {
        item["canonicalItemId"]: item
        for item in candidates
        if item["canonicalItemId"].startswith(
            ("SKI-REFERENCE", "SKI-REPLACEMENT", "SKI-BUSINESS")
        )
    }

    assert set(relations) == {
        "SKI-REFERENCE-1",
        "SKI-REPLACEMENT-1",
        "SKI-BUSINESS-1",
    }
    assert all(item["text"] for item in relations.values())
    assert relations["SKI-REFERENCE-1"]["sourceIds"] == ["REF-NEW"]
    assert relations["SKI-BUSINESS-1"]["scope"]["nodeIds"] == [24]
    assert relations["SKI-BUSINESS-1"]["scope"]["materialTypes"] == [
        "ndt_report"
    ]


def test_canonical_candidate_uses_file_record_scope_and_ranking_metadata() -> None:
    state = retrieval_state_with_canonical_conflict()
    file = state["knowledge_files"][0]
    file.update(
        {
            "sourceId": "KS-STANDARD-TEST",
            "fileName": "NB_T 47013.10-2015.pdf",
            "sourceRelativePath": "rules/standards/NB_T 47013.10-2015.pdf",
            "contextType": "standard_reference",
            "sourceMethod": "remote_ocr",
            "projectId": "P-TEST",
            "nodeId": 24,
            "businessPackId": "engineering_inspection_v1",
            "materialTypes": ["ndt_report"],
        }
    )
    record = state["standard_knowledge_records"][0]
    record["identity"] = {"standardCode": {"value": "NB/T 47013.10-2015"}}
    record["clauses"][0]["nodeIds"] = [24]
    record["clauses"][0]["materialTypes"] = ["ndt_report"]

    item = canonical_clause_candidates(state)[0]

    assert item["kbDocId"] == "KS-STANDARD-TEST"
    assert item["title"] == "NB_T 47013.10-2015.pdf"
    assert item["sourceRelativePath"] == "rules/standards/NB_T 47013.10-2015.pdf"
    assert item["contextType"] == "standard_reference"
    assert item["sourceMethod"] == "remote_ocr"
    assert item["scope"] == {
        "projectId": "P-TEST",
        "nodeId": 24,
        "nodeIds": [24],
        "businessPackId": "engineering_inspection_v1",
        "materialTypes": ["ndt_report"],
        "contextType": "standard_reference",
        "sourceMethod": "remote_ocr",
    }
    assert "NB/T 47013.10-2015" in item["tags"]
    assert "ndt_report" in item["tags"]


def test_disabled_or_context_only_canonical_file_does_not_bypass_retrieval_policy() -> None:
    disabled = retrieval_state_with_canonical_conflict()
    disabled["knowledge_files"][0]["indexEnabled"] = False

    assert knowledge_clause_candidates(disabled) == []

    context_only = retrieval_state_with_canonical_conflict()
    context_only["knowledge_clauses"] = []
    context_only["knowledge_files"][0]["contextType"] = "business_rule_context"
    context_only["standard_knowledge_records"][0]["contextType"] = "context_only"
    context_only["standard_knowledge_records"][0]["clauses"][0][
        "text"
    ] = "这是一段超过四十个字并且只用于业务规则上下文的辅助说明，不能在无关查询时作为默认检索候选返回。"

    result = retrieve_knowledge_clauses(context_only, query="unrelated")

    assert result["clauses"] == []


def test_canonical_node_scope_affects_retrieval_ranking() -> None:
    state = retrieval_state_with_canonical_conflict()
    state["standard_knowledge_records"][0]["clauses"] = [
        {
            "id": "SKI-NODE-25",
            "text": "检测报告审查要求",
            "authority": "current",
            "nodeIds": [25],
            "sources": [{"sourceId": "PARSE-25", "sourceType": "new_mineru"}],
        },
        {
            "id": "SKI-NODE-24",
            "text": "检测报告审查要求",
            "authority": "current",
            "nodeIds": [24],
            "sources": [{"sourceId": "PARSE-24", "sourceType": "new_mineru"}],
        },
    ]

    result = retrieve_knowledge_clauses(
        state, query="检测报告审查要求", node_id=24, top_k=2
    )

    assert result["clauses"][0]["canonicalItemId"] == "SKI-NODE-24"


def test_pageindex_and_dense_matches_use_all_canonical_candidate_identities() -> None:
    state = retrieval_state_with_canonical_conflict()
    item = state["standard_knowledge_records"][0]["clauses"][0]
    item["sources"] = [
        {"sourceId": "SOURCE-CHUNK-1", "sourceType": "new_mineru"}
    ]
    state["knowledge_page_index_nodes"] = [
        {
            "id": "PIN-CANONICAL",
            "nodeId": "PIN-CANONICAL",
            "title": "附录发布日期说明",
            "summary": "正文和附录跨章节发布日期",
            "linkedClauseIds": ["SOURCE-CHUNK-1"],
        }
    ]

    page_result = retrieve_knowledge_clauses(
        state, query="请结合正文和附录跨章节说明发布日期", top_k=1
    )
    dense_result = retrieve_knowledge_clauses(
        state,
        query="发布日期",
        dense_chunk_ids=["SOURCE-CHUNK-1"],
        top_k=1,
    )

    assert page_result["clauses"][0]["retrievalMode"] == "pageindex_tree_local"
    assert page_result["trace"]["selectedClauses"][0]["pageIndexNodeIds"] == [
        "PIN-CANONICAL"
    ]
    assert dense_result["clauses"][0]["retrievalMode"] == "hybrid_dense_local"


def test_trace_preserves_canonical_provenance_and_formal_eligibility() -> None:
    state = retrieval_state_with_canonical_conflict()
    item = state["standard_knowledge_records"][0]["clauses"][0]
    item["bbox"] = [10, 20, 300, 80]

    selected = retrieve_knowledge_clauses(state, query="发布日期", top_k=1)[
        "trace"
    ]["selectedClauses"][0]

    assert selected["canonicalRecordId"] == "SKR-KF-KB-TEST"
    assert selected["canonicalItemId"] == "SKI-CLAUSE-1"
    assert selected["canonicalVersion"] == "standard-knowledge-canonical@1"
    assert selected["sourceFingerprint"] == "sha256:test"
    assert selected["authority"] == "current"
    assert selected["sourceIds"] == ["PARSE-NEW"]
    assert selected["formalEvidenceEligible"] is True


def test_quarantined_canonical_metadata_cannot_be_selected_as_fallback() -> None:
    state = retrieval_state_with_canonical_conflict()
    state["knowledge_clauses"] = []
    state["standard_knowledge_records"][0]["clauses"] = [
        {
            "id": "SKI-CLAUSE-NOISE",
            "text": "https://example.com",
            "authority": "current",
            "sources": [{"sourceId": "PARSE-NEW", "sourceType": "new_mineru"}],
        }
    ]

    assert canonical_clause_candidates(state) == []
    assert retrieve_knowledge_clauses(state, query="unrelated")["clauses"] == []

    state["standard_knowledge_records"][0]["clauses"] = [
        {
            "id": "SKI-CLAUSE-PUBLISHER",
            "text": "中国标准出版社出版发行信息",
            "authority": "current",
            "sources": [{"sourceId": "PARSE-NEW", "sourceType": "new_mineru"}],
        }
    ]

    metadata = canonical_clause_candidates(state)
    assert metadata[0]["evidenceUsable"] is False
    assert retrieve_knowledge_clauses(state, query="unrelated")["clauses"] == []


def test_formal_evidence_requires_locator_or_page_with_valid_bbox() -> None:
    state = retrieval_state_with_canonical_conflict()
    state["standard_knowledge_records"][0]["clauses"] = [
        {
            "id": "SKI-PAGE-ONLY",
            "text": "仅有页码的当前条款",
            "authority": "current",
            "pageNo": 3,
            "sources": [{"sourceId": "PARSE-NEW", "sourceType": "new_mineru"}],
        },
        {
            "id": "SKI-PAGE-BBOX",
            "text": "页码与合法坐标完整的当前条款",
            "authority": "current",
            "pageNo": 3,
            "bbox": [10, 20, 300, 80],
            "sources": [{"sourceId": "PARSE-NEW", "sourceType": "new_mineru"}],
        },
        {
            "id": "SKI-INVALID-BBOX",
            "text": "页码与非法坐标的当前条款",
            "authority": "current",
            "pageNo": 3,
            "bbox": [10, 20, 10, 80],
            "sources": [{"sourceId": "PARSE-NEW", "sourceType": "new_mineru"}],
        },
        {
            "id": "SKI-LOCATOR",
            "text": "带定位标识的当前条款",
            "authority": "current",
            "locatorIds": ["LOCATOR-1"],
            "sources": [{"sourceId": "PARSE-NEW", "sourceType": "new_mineru"}],
        },
    ]

    by_id = {
        item["canonicalItemId"]: item for item in canonical_clause_candidates(state)
    }

    assert by_id["SKI-PAGE-ONLY"]["formalEvidenceEligible"] is False
    assert by_id["SKI-PAGE-BBOX"]["formalEvidenceEligible"] is True
    assert by_id["SKI-INVALID-BBOX"]["formalEvidenceEligible"] is False
    assert by_id["SKI-LOCATOR"]["formalEvidenceEligible"] is True


def test_canonical_candidate_identity_is_repeatable_and_never_uses_uuid_fallback() -> None:
    state = retrieval_state_with_canonical_conflict()
    state["standard_knowledge_records"].append(
        {
            "knowledgeFileId": "KF-MALFORMED",
            "kbVersion": "inspection_kb@test",
            "clauses": [{"text": "缺失记录与项目稳定标识"}],
        }
    )

    first = canonical_clause_candidates(state)
    second = canonical_clause_candidates(state)

    assert first == second
    assert [item["canonicalItemId"] for item in first] == ["SKI-CLAUSE-1"]
