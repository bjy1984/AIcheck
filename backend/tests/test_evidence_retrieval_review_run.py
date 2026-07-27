from __future__ import annotations

import pytest

from libs.db.repository import repo
from libs.review_grounding import build_grounded_review_input
from libs.review_orchestrator import execution


def setup_function() -> None:
    repo.reset()


def _candidate(
    candidate_id: str,
    *,
    document_version_id: str = "DV-FROZEN",
    page_no: int = 3,
    bbox: list[int] | None = None,
    quoted_text: str = "许可证编号 TS-001",
) -> dict:
    return {
        "id": candidate_id,
        "candidateId": candidate_id,
        "evidenceId": candidate_id,
        "documentId": "DOC-001",
        "documentVersionId": document_version_id,
        "pageNo": page_no,
        "bbox": bbox or [10, 20, 100, 40],
        "quotedText": quoted_text,
        "chunkId": f"CHUNK-{candidate_id}",
        "formalEvidenceEligible": True,
        "manualStatus": "pending",
        "manualStatusLabel": "待确认",
        "requiresHumanConfirmation": True,
    }


def _live_result(*candidates: dict, trace_id: str = "RTR-MATERIAL-1") -> dict:
    return {
        "formalCandidates": list(candidates),
        "advisoryCandidates": [],
        "allCandidates": list(candidates),
        "trace": {
            "id": trace_id,
            "retrievalTraceId": trace_id,
            "reviewRunId": "RRUN-MATERIAL-1",
            "queryType": "material_evidence_search",
            "candidateCount": len(candidates),
            "formalCandidateCount": len(candidates),
            "advisoryCandidateCount": 0,
            "candidates": list(candidates),
        },
        "degraded": False,
        "fallbackReason": None,
    }


def _review_run() -> dict:
    return {
        "reviewRunId": "RRUN-MATERIAL-1",
        "projectId": "P-MATERIAL-1",
        "nodeId": 1,
        "inputDocumentVersionIds": ["DV-FROZEN"],
    }


def _context() -> dict:
    return {
        "node": {"name": "设计单位许可资质"},
        "reviewPoints": [
            {
                "reviewContent": "核对设计许可证",
                "evidenceItems": ["许可证编号", "许可范围"],
                "factTargets": [
                    {
                        "targetName": "许可证有效期",
                        "fieldNames": ["有效期至"],
                        "matchTerms": ["有效期"],
                    }
                ],
            }
        ],
        "evidenceLinks": [
            {
                **_candidate("EV-CONFIRMED", quoted_text="人工确认的许可证编号 TS-001"),
                "manualStatus": "confirmed",
                "manualStatusLabel": "已确认",
            }
        ],
    }


def test_review_graph_retrieves_material_evidence_after_ocr_with_frozen_scope(monkeypatch) -> None:
    calls: list[dict] = []
    duplicate = _candidate("EV-CONFIRMED", quoted_text="检索结果不得覆盖人工确认内容")
    new_candidate = _candidate("EVC-LIVE", page_no=4, quoted_text="许可范围 GC1")

    def fake_search(search_repo, **kwargs):
        assert search_repo is repo
        calls.append(kwargs)
        return _live_result(duplicate, new_candidate)

    monkeypatch.setattr(execution, "search_project_evidence", fake_search)
    review_run = _review_run()
    context = _context()

    details = execution.run_step(review_run, "retrieve_material_evidence", context)

    keys = [item["key"] for item in execution.REVIEW_GRAPH_STEPS]
    assert keys.index("retrieve_material_evidence") == keys.index("load_ocr_result") + 1
    assert calls == [
        {
            "project_id": "P-MATERIAL-1",
            "node_id": 1,
            "document_version_ids": ["DV-FROZEN"],
            "query": "设计单位许可资质 核对设计许可证 许可证编号 许可范围 许可证有效期 有效期至 有效期",
            "review_run_id": "RRUN-MATERIAL-1",
        }
    ]
    assert context["materialEvidenceRetrieval"]["retrievalTraceId"] == "RTR-MATERIAL-1"
    assert details == {
        "retrievalTraceId": "RTR-MATERIAL-1",
        "candidateCount": 2,
        "formalCandidateCount": 2,
        "advisoryCandidateCount": 0,
        "evidenceLinkCount": 2,
        "fallbackUsed": False,
        "degraded": False,
        "fallbackReason": None,
    }
    assert [item["id"] for item in context["evidenceLinks"]] == ["EV-CONFIRMED", "EVC-LIVE"]
    assert context["evidenceLinks"][0]["quotedText"] == "人工确认的许可证编号 TS-001"
    assert context["evidenceLinks"][1]["manualStatus"] == "pending"


def test_merge_material_evidence_deduplicates_live_candidates_by_locator() -> None:
    existing = [
        {
            **_candidate("EV-CONFIRMED", quoted_text="同一段定位文字"),
            "manualStatus": "confirmed",
            "manualStatusLabel": "已确认",
        }
    ]
    live = [_candidate("EVC-OTHER-ID", quoted_text="同一段定位文字")]

    merged = execution.merge_material_evidence(existing, live)

    assert merged == existing


def test_merge_material_evidence_deduplicates_existing_links_and_prefers_confirmed() -> None:
    pending = _candidate("EV-SAME", quoted_text="待确认版本")
    confirmed = {
        **_candidate("EV-SAME", quoted_text="人工确认版本"),
        "manualStatus": "confirmed",
        "manualStatusLabel": "已确认",
    }

    merged = execution.merge_material_evidence([pending, confirmed], [])

    assert merged == [confirmed]


def test_merge_material_evidence_recognizes_evidence_ref_id() -> None:
    confirmed = {
        **_candidate("IGNORED"),
        "id": None,
        "candidateId": None,
        "evidenceId": None,
        "evidenceRefId": "EV-REF-1",
        "manualStatus": "confirmed",
        "manualStatusLabel": "已确认",
    }
    live = [_candidate("EV-REF-1", page_no=9, quoted_text="不得追加的重复证据")]

    merged = execution.merge_material_evidence([confirmed], live)

    assert merged == [confirmed]


def test_merge_material_evidence_reindexes_after_confirmed_replaces_pending() -> None:
    pending = _candidate("EV-SAME", page_no=2, quoted_text="待确认旧定位")
    confirmed = {
        **_candidate("EV-SAME", page_no=5, quoted_text="人工确认新定位"),
        "manualStatus": "confirmed",
        "manualStatusLabel": "已确认",
    }
    live_same_locator = _candidate("EVC-OTHER", page_no=5, quoted_text="人工确认新定位")

    merged = execution.merge_material_evidence(
        [pending, confirmed],
        [live_same_locator],
    )

    assert merged == [confirmed]


def test_material_evidence_merge_updates_grounding_input(monkeypatch) -> None:
    new_candidate = _candidate("EVC-LIVE", page_no=4, quoted_text="许可范围 GC1")
    monkeypatch.setattr(
        execution,
        "search_project_evidence",
        lambda search_repo, **kwargs: _live_result(new_candidate),
    )
    context = _context()
    context["groundingInput"] = {
        "documentVersionIds": ["DV-FROZEN"],
        "evidenceLinks": repo.clone(context["evidenceLinks"]),
        "evidenceTextCorpus": ["人工确认的许可证编号 TS-001"],
        "summary": {"evidenceLinkCount": 1},
    }

    execution.run_step(_review_run(), "retrieve_material_evidence", context)

    assert [item["id"] for item in context["groundingInput"]["evidenceLinks"]] == [
        "EV-CONFIRMED",
        "EVC-LIVE",
    ]
    assert context["groundingInput"]["evidenceTextCorpus"] == [
        "人工确认的许可证编号 TS-001",
        "许可范围 GC1",
    ]
    assert context["groundingInput"]["summary"]["evidenceLinkCount"] == 2


def test_material_evidence_merge_recomputes_grounding_status(monkeypatch) -> None:
    grounding_input = build_grounded_review_input(
        {
            "extracted_fields": [
                {
                    "id": "FIELD-1",
                    "documentVersionId": "DV-FROZEN",
                    "fieldName": "许可证编号",
                    "fieldValue": "TS-001",
                    "pageNo": 3,
                    "bbox": [10, 20, 100, 40],
                    "confidence": 0.99,
                }
            ],
            "ocr_parse_results": [],
            "evidence_links": [],
        },
        {"DV-FROZEN"},
    )
    assert [item["code"] for item in grounding_input["blockingIssues"]] == [
        "OCR_GROUNDING_EVIDENCE_LINK_MISSING"
    ]
    monkeypatch.setattr(
        execution,
        "search_project_evidence",
        lambda search_repo, **kwargs: _live_result(_candidate("EVC-LIVE")),
    )
    context = _context()
    context["evidenceLinks"] = []
    context["groundingInput"] = grounding_input

    execution.run_step(_review_run(), "retrieve_material_evidence", context)

    assert context["groundingInput"]["groundingStatus"] == "grounded"
    assert context["groundingInput"]["blockingIssues"] == []
    assert context["groundingInput"]["summary"]["blockingIssueCount"] == 0
    assert context["groundingInput"]["summary"]["groundingStatus"] == "grounded"
    assert context["groundingInput"]["reviewWarnings"] == []


def test_legacy_precomputed_evidence_remains_grounded_when_live_retrieval_is_empty(monkeypatch) -> None:
    grounding_input = build_grounded_review_input(
        {
            "extracted_fields": [
                {
                    "id": "FIELD-1",
                    "documentVersionId": "DV-FROZEN",
                    "fieldName": "许可证编号",
                    "fieldValue": "TS-001",
                    "pageNo": 3,
                    "bbox": [10, 20, 100, 40],
                    "confidence": 0.99,
                }
            ],
            "ocr_parse_results": [],
            "evidence_links": [
                {
                    "id": "EV-LEGACY",
                    "documentId": "DOC-001",
                    "documentVersionId": "DV-FROZEN",
                    "pageNo": 3,
                    "bbox": [10, 20, 100, 40],
                    "quotedText": "许可证编号 TS-001",
                    "confidence": 0.99,
                }
            ],
        },
        {"DV-FROZEN"},
    )
    assert grounding_input["groundingStatus"] == "grounded"
    assert "formalEvidenceEligible" not in grounding_input["evidenceLinks"][0]
    monkeypatch.setattr(
        execution,
        "search_project_evidence",
        lambda search_repo, **kwargs: _live_result(),
    )
    context = _context()
    context["evidenceLinks"] = repo.clone(grounding_input["evidenceLinks"])
    context["groundingInput"] = grounding_input

    execution.run_step(_review_run(), "retrieve_material_evidence", context)

    assert context["groundingInput"]["groundingStatus"] == "grounded"
    assert context["groundingInput"]["blockingIssues"] == []
    assert context["groundingInput"]["evidenceLinks"] == grounding_input["evidenceLinks"]


def test_material_evidence_merge_preserves_risk_beyond_truncated_fields(monkeypatch) -> None:
    fields = [
        {
            "id": f"FIELD-{index}",
            "documentVersionId": "DV-FROZEN",
            "fieldName": "许可证编号",
            "fieldValue": f"TS-{index:03d}",
            "pageNo": 3,
            "bbox": [10, 20, 100, 40],
            "confidence": 0.99,
        }
        for index in range(1, 81)
    ]
    fields.append(
        {
            "id": "FIELD-81",
            "documentVersionId": "DV-FROZEN",
            "fieldName": "许可证有效期",
            "fieldValue": "无法确认",
            "pageNo": 4,
            "bbox": None,
            "confidence": 0.5,
        }
    )
    grounding_input = build_grounded_review_input(
        {
            "extracted_fields": fields,
            "ocr_parse_results": [],
            "evidence_links": [],
        },
        {"DV-FROZEN"},
    )
    assert len(grounding_input["fields"]) == 80
    monkeypatch.setattr(
        execution,
        "search_project_evidence",
        lambda search_repo, **kwargs: _live_result(_candidate("EVC-LIVE")),
    )
    context = _context()
    context["evidenceLinks"] = []
    context["groundingInput"] = grounding_input

    execution.run_step(_review_run(), "retrieve_material_evidence", context)

    issue_codes = {item["code"] for item in context["groundingInput"]["blockingIssues"]}
    assert issue_codes == {
        "OCR_GROUNDING_LOW_CONFIDENCE",
        "OCR_GROUNDING_POSITION_MISSING",
    }
    assert context["groundingInput"]["groundingStatus"] == "insufficient_evidence"
    assert context["groundingInput"]["summary"]["lowConfidenceEvidenceCount"] == 1
    assert context["groundingInput"]["summary"]["missingPositionEvidenceCount"] == 1


@pytest.mark.parametrize(
    "candidate",
    [
        {**_candidate("EVC-ADVISORY"), "formalEvidenceEligible": False},
        {**_candidate("EVC-NO-BBOX"), "bbox": None},
    ],
    ids=["advisory", "missing-bbox"],
)
def test_non_formal_live_evidence_does_not_promote_grounding(monkeypatch, candidate) -> None:
    grounding_input = build_grounded_review_input(
        {
            "extracted_fields": [
                {
                    "id": "FIELD-1",
                    "documentVersionId": "DV-FROZEN",
                    "fieldName": "许可证编号",
                    "fieldValue": "TS-001",
                    "pageNo": 3,
                    "bbox": [10, 20, 100, 40],
                    "confidence": 0.99,
                }
            ],
            "ocr_parse_results": [],
            "evidence_links": [],
        },
        {"DV-FROZEN"},
    )
    monkeypatch.setattr(
        execution,
        "search_project_evidence",
        lambda search_repo, **kwargs: _live_result(candidate),
    )
    context = _context()
    context["evidenceLinks"] = []
    context["groundingInput"] = grounding_input

    execution.run_step(_review_run(), "retrieve_material_evidence", context)

    assert context["groundingInput"]["groundingStatus"] == "insufficient_evidence"
    assert [item["code"] for item in context["groundingInput"]["blockingIssues"]] == [
        "OCR_GROUNDING_EVIDENCE_LINK_MISSING"
    ]
    assert context["groundingInput"]["summary"]["blockingIssueCount"] == 1


def test_pure_llm_material_evidence_step_skips_ocr_retrieval(monkeypatch) -> None:
    def forbidden_search(search_repo, **kwargs):
        raise AssertionError("pure LLM mode must not retrieve OCR material evidence")

    monkeypatch.setattr(execution, "search_project_evidence", forbidden_search)
    review_run = {**_review_run(), "auditInputMode": "pure_llm"}
    context: dict = {}
    execution.run_step(review_run, "load_ocr_result", context)
    original_grounding = repo.clone(context["groundingInput"])

    details = execution.run_step(review_run, "retrieve_material_evidence", context)

    assert context["groundingInput"] == original_grounding
    assert context["evidenceLinks"] == []
    assert context["materialEvidenceRetrieval"] == {
        "retrievalTraceId": None,
        "formalCandidates": [],
        "advisoryCandidates": [],
        "allCandidates": [],
        "degraded": False,
        "fallbackUsed": False,
        "skipped": True,
        "skipReason": "ocr_evidence_disabled",
    }
    assert details == {
        "retrievalTraceId": None,
        "candidateCount": 0,
        "formalCandidateCount": 0,
        "advisoryCandidateCount": 0,
        "evidenceLinkCount": 0,
        "fallbackUsed": False,
        "degraded": False,
        "skipped": True,
        "skipReason": "ocr_evidence_disabled",
        "auditInputMode": "pure_llm",
    }


def test_material_evidence_retrieval_failure_falls_back_without_blocking(monkeypatch) -> None:
    def unavailable_search(search_repo, **kwargs):
        raise RuntimeError("vector service unavailable")

    monkeypatch.setattr(execution, "search_project_evidence", unavailable_search)
    review_run = _review_run()
    context = _context()
    precomputed_evidence = repo.clone(context["evidenceLinks"])

    details = execution.run_step(review_run, "retrieve_material_evidence", context)

    assert context["evidenceLinks"] == precomputed_evidence
    assert context["materialEvidenceRetrieval"] == {
        "retrievalTraceId": None,
        "formalCandidates": [],
        "advisoryCandidates": [],
        "allCandidates": [],
        "degraded": True,
        "fallbackUsed": True,
        "fallbackReason": "material_evidence_retrieval_failed",
        "errorType": "RuntimeError",
    }
    assert details == {
        "retrievalTraceId": None,
        "candidateCount": 0,
        "formalCandidateCount": 0,
        "advisoryCandidateCount": 0,
        "evidenceLinkCount": 1,
        "fallbackUsed": True,
        "degraded": True,
        "fallbackReason": "material_evidence_retrieval_failed",
    }


def test_graph_view_associates_material_trace_with_material_retrieval_node() -> None:
    review_run = _review_run()
    repo.state["review_runs"].append(review_run)
    repo.state["review_graph_nodes"].extend(
        [
            {
                "id": "RGN-MATERIAL",
                "reviewRunId": review_run["reviewRunId"],
                "nodeKey": "retrieve_material_evidence",
                "sequence": 3,
                "status": "succeeded",
            },
            {
                "id": "RGN-KNOWLEDGE",
                "reviewRunId": review_run["reviewRunId"],
                "nodeKey": "retrieve_knowledge",
                "sequence": 5,
                "status": "succeeded",
            },
        ]
    )
    repo.state["retrieval_traces"].extend(
        [
            _live_result(_candidate("EVC-LIVE"))["trace"],
            {
                "id": "RTR-KNOWLEDGE-1",
                "retrievalTraceId": "RTR-KNOWLEDGE-1",
                "reviewRunId": review_run["reviewRunId"],
                "queryType": "review_basis_search",
                "selectedClauses": [{"clauseId": "CLAUSE-1"}],
            },
        ]
    )

    graph = execution.graph_view_for_review_run(review_run["reviewRunId"])

    nodes = {item["nodeKey"]: item for item in graph["nodes"]}
    assert nodes["retrieve_material_evidence"]["artifactCounts"]["retrievalTraces"] == 1
    assert nodes["retrieve_material_evidence"]["retrievalTraces"] == [
        {
            "retrievalTraceId": "RTR-MATERIAL-1",
            "queryType": "material_evidence_search",
            "selectedRoute": None,
            "routerVersion": None,
            "selectedClauseCount": 0,
            "selectedClauseIds": [],
            "pageIndexNodeCount": 0,
            "pageIndexLinkedClauseIds": [],
            "candidateCount": 1,
            "formalCandidateCount": 1,
            "advisoryCandidateCount": 0,
            "degraded": False,
            "fallbackReason": None,
        }
    ]
    assert nodes["retrieve_knowledge"]["artifactCounts"]["retrievalTraces"] == 1
    assert graph["artifactSummary"]["materialEvidenceRetrievalTraces"] == 1
    assert graph["artifacts"]["materialEvidenceRetrievalTraces"] == nodes["retrieve_material_evidence"]["retrievalTraces"]
