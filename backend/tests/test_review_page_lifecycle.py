from copy import deepcopy
from types import SimpleNamespace

import pytest

from libs.business_pack import load_business_pack
from libs.integrations.errors import IntegrationServiceError
from libs.review_document_scope import validate_document_scope
from libs.review_orchestrator import execution as ex


@pytest.fixture
def lifecycle(monkeypatch):
    pack = load_business_pack("engineering_inspection_v1")
    state = {"review_runs": [], "ocr_parse_results": []}
    repo = SimpleNamespace(state=state, clone=deepcopy,
                           require_project=lambda _: {"businessPackSnapshot": pack},
                           find_one=lambda _, value, **kwargs: next(
                               (row for row in state["review_runs"] if row["reviewRunId"] == value), None))
    monkeypatch.setattr(ex, "repo", repo)
    for name in ("ensure_review_state", "seed_graph_nodes", "append_review_event",
                 "bind_evidence_package_to_review_run", "freeze_review_run_clause_snapshot", "flush_state_records"):
        monkeypatch.setattr(ex, name, lambda *args, **kwargs: None)
    monkeypatch.setattr(ex, "review_run_state_records", lambda _: {})
    monkeypatch.setattr(ex, "current_published_rule_for_node", lambda *args, **kwargs: None)
    monkeypatch.setenv("AICHECK_WORKSTATIONS_ENABLED", "true")
    return state, {"id": "AI-TEST", "projectId": "P", "nodeId": 16, "tenantId": "T",
                   "businessPackId": pack["id"], "inputDocumentVersionIds": ["V"],
                   "inputDocumentPageRanges": {"V": {"start": 2, "end": 4}}}


def test_creation_detaches_ranges_and_hash_distinguishes_page_selection(lifecycle):
    state, source = lifecycle
    alternative = deepcopy(source)
    alternative["inputDocumentPageRanges"]["V"]["end"] = 5
    run = ex.create_review_run_from_ai_run(source, mode="inline")
    other = ex.create_review_run_from_ai_run(alternative, mode="inline")
    assert run["inputHash"] != other["inputHash"]
    assert run["documentScopeSnapshot"]["documentPageRanges"] == {"V": {"start": 2, "end": 4}}
    source["inputDocumentPageRanges"]["V"]["end"] = 9
    assert run["inputDocumentPageRanges"]["V"]["end"] == 4
    validate_document_scope(run)
    assert len(state["review_runs"]) == 2


def test_reusing_existing_run_rejects_changed_range(lifecycle):
    state, source = lifecycle
    run = ex.create_review_run_from_ai_run(source, mode="inline")
    assert ex.create_review_run_from_ai_run(source, mode="inline") is run
    source["inputDocumentPageRanges"]["V"]["start"] = 3
    with pytest.raises(ValueError, match="existing_run_mismatch"):
        ex.create_review_run_from_ai_run(source, mode="inline")
    assert len(state["review_runs"]) == 1


def test_replay_preserves_scope_and_does_not_mutate_parent(lifecycle):
    _, source = lifecycle
    parent = ex.create_review_run_from_ai_run(source, mode="inline")
    before = deepcopy(parent)
    child = ex.clone_review_run_for_replay(parent, run_mode="replay", reason="offline test")
    assert child["documentScopeSnapshot"] == parent["documentScopeSnapshot"]
    assert child["inputHash"] == parent["inputHash"]
    validate_document_scope(child)
    child["inputDocumentPageRanges"]["V"]["end"] = 6
    assert parent == before


def test_replay_changed_sources_is_rejected_before_child_insert(lifecycle):
    state, source = lifecycle
    parent = ex.create_review_run_from_ai_run(source, mode="inline")
    state["extracted_fields"] = [{"documentVersionId": "V", "pageNo": 2, "fieldValue": "NEW"}]
    with pytest.raises(IntegrationServiceError, match="REVIEW_INPUT_CHANGED_RECREATE_RUN"):
        ex.clone_review_run_for_replay(parent, run_mode="replay")
    assert len(state["review_runs"]) == 1


def test_non_workstation_creation_cannot_drop_ranges(lifecycle, monkeypatch):
    state, source = lifecycle
    monkeypatch.setenv("AICHECK_WORKSTATIONS_ENABLED", "false")
    with pytest.raises(ValueError, match="requires_workstation"):
        ex.create_review_run_from_ai_run(source, mode="inline")
    assert state["review_runs"] == []
