import json
from copy import deepcopy

import pytest

from libs.review_document_scope import freeze_document_scope
from libs.review_evidence import (
    attach_review_evidence_package_to_ai_run,
    build_review_evidence_package,
)
from libs.review_orchestrator.node_fact_overrides import apply_node_fact_corrections


def test_page_scope_reaches_snapshot_manifest_shards_and_persistence():
    state = {"documents": [{"id": "D", "projectId": "P", "currentVersionId": "V"}],
             "versions": [{"id": "V", "documentId": "D"}],
             "ocr_parse_results": [{"id": "OCR", "documentVersionId": "V", "status": "success",
                                    "fragments": [{"pageNo": 1, "text": "OUTSIDE"},
                                                  {"pageNo": 2, "text": "SELECTED", "bbox": [0, 0, 10, 10]}],
                                    "tables": [{"pageNo": 2, "endPage": 3, "contentMarkdown": "CROSS-PAGE"}]}],
             "extracted_fields": [{"documentVersionId": "V", "pageNo": 3, "fieldValue": "OUTSIDE"}],
             "evidence_links": [{"id": "E", "documentVersionId": "V", "quotedText": "UNKNOWN-PAGE"}]}
    original = deepcopy(state)
    common = {"rule_version": "r", "clause_package_version": "c", "prompt_version": "p", "strategy_version": "s",
              "document_version_ids": ["V"]}
    package = build_review_evidence_package(state, "P", 16, document_page_ranges={"V": {"start": 2, "end": 2}}, **common)
    text = json.dumps(package)
    assert "SELECTED" in text
    assert all(marker not in text for marker in ["OUTSIDE", "CROSS-PAGE", "UNKNOWN-PAGE"])
    assert package["snapshot"]["documentPageRanges"] == {"V": {"start": 2, "end": 2}}
    assert package["manifest"]["documentPageRanges"] == package["snapshot"]["documentPageRanges"]
    other = build_review_evidence_package(state, "P", 16, document_page_ranges={"V": {"start": 2, "end": 3}}, **common)
    assert other["snapshot"]["snapshotHash"] != package["snapshot"]["snapshotHash"]
    assert state == original
    run = {"id": "AI", "projectId": "P", "nodeId": 16, "inputDocumentVersionIds": ["V"],
           "inputDocumentPageRanges": {"V": {"start": 2, "end": 2}}}
    persisted = attach_review_evidence_package_to_ai_run(state, run, clause_package_snapshot=None)
    assert run["inputDocumentVersionIds"] == ["V"]
    assert persisted["snapshot"]["documentPageRanges"] == run["inputDocumentPageRanges"]
    assert "OUTSIDE" not in json.dumps(state["evidence_shards"])


def test_empty_page_selection_does_not_fall_back_to_unbounded_artifacts():
    state = {"documents": [{"id": "D", "projectId": "P", "currentVersionId": "V"}],
             "versions": [{"id": "V", "documentId": "D"}],
             "ocr_parse_results": [{"documentVersionId": "V", "fragments": [{"pageNo": 1, "text": "OUTSIDE"}]}]}
    package = build_review_evidence_package(state, "P", 16, rule_version="r", clause_package_version="c",
        prompt_version="p", strategy_version="s", document_version_ids=["V"],
        document_page_ranges={"V": {"start": 2, "end": 2}})
    assert package["manifest"]["artifacts"] == []
    assert not package["coverage"]["coveragePassed"]


@pytest.mark.parametrize("version,page,expected", [("V", 2, 9), ("V", 1, 3), ("V", None, 3), ("OTHER", 2, 3)])
def test_node_fact_correction_cannot_restore_outside_scope_values(version, page, expected):
    run = {"projectId": "P", "nodeId": 16, "inputDocumentVersionIds": ["V"],
           "inputDocumentPageRanges": {"V": {"start": 2, "end": 2}}}
    state = {"fact_corrections": [{"projectId": "P", "nodeId": 16, "documentVersionId": version,
                                  "pageNo": page, "factPath": "material.thickness", "correctedValue": 9,
                                  "status": "active"}]}
    run["documentScopeSnapshot"] = freeze_document_scope(run, state)
    facts = {"material": {"thickness": 3}}
    apply_node_fact_corrections(state, "P", 16, facts, review_run=run)
    assert facts["material"]["thickness"] == expected
    if version == "V":
        state["fact_corrections"][0]["correctedValue"] = 10
        with pytest.raises(ValueError, match="sources_changed"):
            apply_node_fact_corrections(state, "P", 16, facts, review_run=run)
