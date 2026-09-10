"""The exporter must copy the run's own result, never decide one."""

import json

import pytest
from test_r37_node_plan import fixture as r37_fixture

from libs.review_document_scope import freeze_document_scope
from scripts import export_review_acceptance_fixture as exporter
from scripts.review_acceptance_gate import canonical_input_hash

RUN_ID = "RRUN-EXPORTTEST"


def state_with_run(result="passed", run_id=RUN_ID):
    state, run = r37_fixture()
    run["reviewRunId"] = run_id
    run["documentScopeSnapshot"] = freeze_document_scope(run, state)
    state["review_runs"] = [run]
    state["rule_check_results"] = [
        {"id": "RCHK-1", "reviewRunId": run_id, "ruleCode": "R37", "result": result}
    ]
    return state


def test_fixture_freezes_the_recorded_result_and_hashes_its_own_input():
    state = state_with_run()
    fixture = exporter.build_fixture(state, RUN_ID)
    assert fixture["ruleId"] == "R37"
    assert fixture["expectedResult"] == "passed"
    assert fixture["fixtureInputSha256"] == canonical_input_hash(fixture["frozenInput"])
    assert fixture["frozenInput"]["reviewRun"]["documentScopeSnapshot"]


@pytest.mark.parametrize("result", ["failed", "evidence_insufficient", "not_applicable"])
def test_every_recorded_verdict_is_carried_through_unchanged(result):
    fixture = exporter.build_fixture(state_with_run(result), RUN_ID)
    assert fixture["expectedResult"] == result


@pytest.mark.parametrize(
    "result,reason",
    [
        ("execution_error", "export_run_result_not_an_acceptance_scenario"),
        ("human_review_required", "export_run_result_not_an_acceptance_scenario"),
    ],
)
def test_non_business_outcomes_are_refused_not_coerced(result, reason):
    with pytest.raises(ValueError, match=reason):
        exporter.build_fixture(state_with_run(result), RUN_ID)


def test_a_run_without_a_recorded_result_cannot_be_exported():
    state = state_with_run()
    state["rule_check_results"] = []
    with pytest.raises(ValueError, match="export_run_has_no_recorded_result"):
        exporter.build_fixture(state, RUN_ID)


def test_disagreeing_rule_results_have_no_single_scenario_to_freeze():
    state = state_with_run()
    state["rule_check_results"].append(
        {"id": "RCHK-2", "reviewRunId": RUN_ID, "ruleCode": "R37", "result": "failed"}
    )
    with pytest.raises(ValueError, match="export_run_results_conflict"):
        exporter.build_fixture(state, RUN_ID)


def test_scope_is_never_re_frozen_from_todays_documents():
    state = state_with_run()
    del state["review_runs"][0]["documentScopeSnapshot"]
    with pytest.raises(ValueError, match="export_run_has_no_frozen_document_scope"):
        exporter.build_fixture(state, RUN_ID)


def test_export_replays_the_real_pipeline_and_records_the_agreement(tmp_path):
    report = exporter.export_run(state_with_run(), RUN_ID, tmp_path / "out")
    assert report["matchesExpected"] is True
    assert report["businessAcceptance"] == "not_reviewed"
    output = json.loads((tmp_path / "out" / "output.json").read_text())
    assert output["result"] == "passed"
    assert output["atomicResults"]
    provenance = json.loads((tmp_path / "out" / "provenance.json").read_text())
    assert provenance["reviewRunId"] == RUN_ID
    assert provenance["scenario"] == "compliant"
    assert provenance["replayReproducedRecordedResult"] is True
    # Human sign-off is not something this script can produce.
    assert "reviewer" not in provenance


def test_a_recorded_result_the_replay_cannot_reproduce_is_reported_not_hidden(tmp_path):
    report = exporter.export_run(state_with_run("failed"), RUN_ID, tmp_path / "out")
    assert report["matchesExpected"] is False
    provenance = json.loads((tmp_path / "out" / "provenance.json").read_text())
    assert provenance["replayReproducedRecordedResult"] is False
    assert provenance["recordedResult"] == "failed"
    assert json.loads((tmp_path / "out" / "output.json").read_text())["result"] == "passed"
