"""Synthetic sources exercise real bindings; they are not business acceptance."""

import json
from copy import deepcopy

import pytest
from test_r35_facts import fixture as r35_fixture
from test_r36_facts import fixture as r36_fixture
from test_r37_node_plan import fixture as r37_fixture
from test_r37_node_plan import table

from libs.business_pack import load_business_pack
from libs.review_document_scope import freeze_document_scope
from scripts import replay_review_acceptance as replay
from scripts.review_acceptance_gate import canonical_input_hash

PACK = "engineering_inspection_v1"


def make_fixture(source=r37_fixture, expected="passed"):
    state, run = source()
    run["documentScopeSnapshot"] = freeze_document_scope(run, state)
    frozen = {
        "state": state,
        "reviewRun": run,
        "inputDocumentVersionIds": deepcopy(run["inputDocumentVersionIds"]),
    }
    return {
        "ruleId": f"R{run['nodeId']:02d}",
        "expectedResult": expected,
        "frozenInput": frozen,
        "fixtureInputSha256": canonical_input_hash(frozen),
    }


def execute(fixture, pack=None):
    return replay.replay_fixture(
        fixture, pack or load_business_pack(PACK), binding_sha256="b" * 64, code_sha256="c" * 64
    )


@pytest.mark.parametrize(
    "case,expected",
    [
        ("compliant", "passed"),
        ("noncompliant", "failed"),
        ("insufficient", "evidence_insufficient"),
        ("not_applicable", "not_applicable"),
    ],
)
def test_r37_replay_runs_real_frozen_source_pipeline(case, expected):
    def source():
        state, run = r37_fixture()
        if case == "noncompliant":
            table(state, "ndt_reinspection_reports")["normalizedRows"][0]["status"] = "unqualified"
        elif case == "insufficient":
            table(state, "ndt_nonconformance_notices")["normalizedRows"] = []
        elif case == "not_applicable":
            table(state, "ndt_nonconformance_context")["normalizedRows"][0]["required"] = False
            table(state, "ndt_nonconformance_inventory")["normalizedRows"][0]["caseCount"] = 0
            table(state, "ndt_progressive_inventory")["normalizedRows"][0]["eventCount"] = 0
            for schema in (
                "ndt_nonconformance_cases",
                "ndt_progressive_events",
                "ndt_progressive_reports",
                "ndt_defect_dispositions",
                "ndt_reinspection_reports",
                "ndt_defect_closure_links",
            ):
                table(state, schema)["normalizedRows"] = []
        return state, run

    fixture = make_fixture(source, expected)
    before = deepcopy(fixture)
    first, second = execute(fixture), execute(fixture)
    assert first["result"] == expected
    assert first["matchesExpected"] is True
    assert first["businessAcceptance"] == "not_reviewed"
    assert len(first["atomicResults"]) == 3
    assert all(row["toolResults"] for row in first["atomicResults"])
    assert replay.semantic_result(first) == replay.semantic_result(second)
    assert fixture == before


@pytest.mark.parametrize("source", [r35_fixture, r36_fixture])
def test_other_registered_ndt_builders_execute_actual_bindings(source):
    fixture = make_fixture(source)
    output = execute(fixture)
    assert output["atomicResults"]
    assert output["ruleId"] == fixture["ruleId"]
    assert all(row["toolResults"] for row in output["atomicResults"])


def test_rehashed_source_change_still_fails_frozen_scope():
    fixture = make_fixture()
    fixture["frozenInput"]["state"]["ocr_parse_results"][0]["tables"][0]["normalizedRows"] = []
    fixture["fixtureInputSha256"] = canonical_input_hash(fixture["frozenInput"])
    with pytest.raises(ValueError, match="sources_changed"):
        execute(fixture)


@pytest.mark.parametrize(
    "mutation,error",
    [
        (lambda f: f.update(fixtureInputSha256="wrong"), "fixture_hash_mismatch"),
        (lambda f: f.update(ruleId="R36"), "rule_node_mismatch"),
        (lambda f: f["frozenInput"].update(inputDocumentVersionIds=[]), "document_scope_mismatch"),
        (
            lambda f: f["frozenInput"]["reviewRun"].pop("documentScopeSnapshot"),
            "frozen_scope_required",
        ),
        (lambda f: f["frozenInput"]["reviewRun"].update(nodeId=34), "fact_builder_not_supported"),
    ],
)
def test_invalid_replay_inputs_rejected(mutation, error):
    fixture = make_fixture()
    mutation(fixture)
    if error != "fixture_hash_mismatch":
        fixture["fixtureInputSha256"] = canonical_input_hash(fixture["frozenInput"])
    with pytest.raises((TypeError, ValueError), match=error):
        execute(fixture)


def test_external_tool_refused_before_any_dispatch(monkeypatch):
    pack = deepcopy(load_business_pack(PACK))
    next(item for item in pack["atomicCheckToolBindings"] if item["sourceRuleId"] == "R37")[
        "tools"
    ].append("lookup_standard_status")

    def unexpected(*args, **kwargs):
        pytest.fail("Tool execution occurred before offline preflight")

    monkeypatch.setattr(replay, "dispatch_runtime_tool", unexpected)
    with pytest.raises(ValueError, match="nonlocal_or_unsupported_tools"):
        execute(make_fixture(), pack)


def test_export_retains_mismatch_and_refuses_overwrite(tmp_path):
    fixture = make_fixture(expected="failed")
    path = tmp_path / "source.json"
    path.write_text(json.dumps(fixture))
    target = tmp_path / "run"
    report = replay.export_replay(path, target)
    assert report["matchesExpected"] is False
    assert report["businessAcceptance"] == "not_reviewed"
    assert (target / "fixture.json").read_bytes() == path.read_bytes()
    output = json.loads((target / "output.json").read_bytes())
    assert output["result"] == "passed"  # expected label cannot force observed outcome
    before = (target / "output.json").read_bytes()
    with pytest.raises(FileExistsError):
        replay.export_replay(path, target)
    assert (target / "output.json").read_bytes() == before
