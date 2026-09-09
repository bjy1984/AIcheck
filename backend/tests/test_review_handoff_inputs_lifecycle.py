from copy import deepcopy

import pytest

from libs.integrations.errors import IntegrationServiceError
from libs.review_orchestrator import execution as ex

pytest_plugins = ["test_review_page_lifecycle", "test_review_handoff_inputs"]


def prepare(lifecycle, inputs):
    state, ai_run = lifecycle
    incoming, _, selection = inputs
    state.update(deepcopy(incoming))
    state["review_runs"] = state["review_runs"][:2]
    ai_run.update(nodeId=35, projectId="P", tenantId="T", inputDocumentVersionIds=["V"], handoffSelection=deepcopy(selection))
    ai_run.pop("inputDocumentPageRanges", None)
    return state, ai_run


def test_new_run_prompt_and_replay_use_frozen_verified_handoff(lifecycle, inputs):
    _state, ai_run = prepare(lifecycle, inputs)
    run = ex.create_review_run_from_ai_run(ai_run, mode="inline")
    assert run["handoffInputsSnapshot"]["items"][0]["sourceRunId"] == "SOURCE"
    assert ex.create_review_run_from_ai_run(ai_run, mode="inline") is run
    parts = ex.build_review_prompt_parts(run, {})
    assert parts["userPayload"]["verifiedHandoffs"][0]["subject"]["objectId"] == "W1"
    before = deepcopy(run)
    child = ex.clone_review_run_for_replay(run, run_mode="replay")
    assert child["handoffInputsSnapshot"] == run["handoffInputsSnapshot"]
    assert child["inputHash"] == run["inputHash"]
    child["handoffInputsSnapshot"]["items"][0]["draft"]["payload"]["observation"] = "CHANGED"
    assert run == before
    ai_run["handoffSelection"]["subject"]["objectId"] = "OTHER"
    with pytest.raises(ValueError):
        ex.create_review_run_from_ai_run(ai_run, mode="inline")


def test_changed_upstream_prevents_prompt_and_replay_before_insertion(lifecycle, inputs):
    state, ai_run = prepare(lifecycle, inputs)
    run = ex.create_review_run_from_ai_run(ai_run, mode="inline")
    state["review_runs"][1]["outputHash"] = "CHANGED"
    before = len(state["review_runs"])
    with pytest.raises(ValueError):
        ex.build_review_prompt_parts(run, {})
    with pytest.raises(IntegrationServiceError, match="REVIEW_INPUT_CHANGED_RECREATE_RUN"):
        ex.clone_review_run_for_replay(run, run_mode="replay")
    assert len(state["review_runs"]) == before


def test_disabled_workstations_cannot_silently_drop_handoff_inputs(lifecycle, inputs, monkeypatch):
    state, ai_run = prepare(lifecycle, inputs)
    monkeypatch.setenv("AICHECK_WORKSTATIONS_ENABLED", "false")
    with pytest.raises(ValueError, match="requires_workstation"):
        ex.create_review_run_from_ai_run(ai_run, mode="inline")
    assert len(state["review_runs"]) == 2
