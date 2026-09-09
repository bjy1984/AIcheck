from copy import deepcopy

import pytest
from test_review_condition_mapping import mapped

from libs.integrations.errors import IntegrationServiceError
from libs.review_orchestrator import execution as ex

pytest_plugins = ["test_review_page_lifecycle"]

def setup_source(lifecycle, monkeypatch):
    state, source = lifecycle
    _, _, rule, mapped_state, request = mapped()
    state.update(mapped_state)
    source.update(nodeId=24, inputDocumentVersionIds=["D"], conditionObjectMapping=request)
    source.pop("inputDocumentPageRanges")
    monkeypatch.setattr(ex, "current_published_rule_for_node", lambda *args, **kwargs: rule)
    return state, source


def test_ai_run_create_reuse_and_replay_preserve_mapping(lifecycle, monkeypatch):
    state, source = setup_source(lifecycle, monkeypatch)
    run = ex.create_review_run_from_ai_run(source, mode="inline")
    assert run["conditionObjectMappingSnapshot"]["selection"] == source["conditionObjectMapping"]["selection"]
    assert ex.create_review_run_from_ai_run(source, mode="inline") is run
    before = deepcopy(run)
    child = ex.clone_review_run_for_replay(run, run_mode="replay")
    assert child["conditionObjectMappingSnapshot"] == run["conditionObjectMappingSnapshot"]
    assert child["inputHash"] == run["inputHash"]
    child["conditionObjectMappingSnapshot"]["selection"]["subject"]["objectId"] = "OTHER"
    assert run == before
    source["conditionObjectMapping"]["selection"]["subject"]["objectId"] = "CHANGED"
    with pytest.raises(ValueError, match="existing_run_mismatch"):
        ex.create_review_run_from_ai_run(source, mode="inline")
    assert len(state["review_runs"]) == 2


def test_changed_mapping_sources_block_replay_before_insertion(lifecycle, monkeypatch):
    state, source = setup_source(lifecycle, monkeypatch)
    run = ex.create_review_run_from_ai_run(source, mode="inline")
    state["ocr_parse_results"][0]["fields"][0]["value"] = 44
    with pytest.raises(IntegrationServiceError, match="REVIEW_INPUT_CHANGED_RECREATE_RUN"):
        ex.clone_review_run_for_replay(run, run_mode="replay")
    assert len(state["review_runs"]) == 1


def test_mapping_cannot_be_silently_dropped_without_workstation(lifecycle, monkeypatch):
    state, source = setup_source(lifecycle, monkeypatch)
    monkeypatch.setenv("AICHECK_WORKSTATIONS_ENABLED", "false")
    with pytest.raises(ValueError, match="requires_workstation"):
        ex.create_review_run_from_ai_run(source, mode="inline")
    assert state["review_runs"] == []
