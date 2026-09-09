from copy import deepcopy

import pytest
from test_r39_facts import evaluate
from test_r39_reference_inventory import inventory_fixture


def fixture():
    state, review = inventory_fixture()
    for parse in state["ocr_parse_results"]:
        for table in parse["tables"]:
            if table["businessSchema"] in {"ndt_reference_members", "ndt_reference_context", "ndt_reference_basis",
                                          "ndt_instruction_reference", "ndt_procedure_identity"}:
                extra = deepcopy(table["normalizedRows"][0])
                extra["method"] = "RT"
                table["normalizedRows"].append(extra)
    return state, review


@pytest.mark.parametrize("change", [{"confidence": .74}, {"confidence": None}, {"confidence": True},
                                   {"confidence": float("inf")}, {"conflicted": True}, {"conflicted": "false"}])
@pytest.mark.parametrize("known_failure", [False, True])
def test_unreliable_pair_cannot_erase_independent_finding(change, known_failure):
    state, review = fixture()
    rows = state["ocr_parse_results"][2]["tables"][0]["normalizedRows"]
    rows[1].update(change)
    if known_failure:
        rows[0]["procedureVersion"] = "A"
    before = deepcopy(state)
    facts, output = evaluate(state, review, "evaluate_r39_procedure_reference")
    assert output["result"] == ("failed" if known_failure else "evidence_insufficient")
    coverage = output["facts"]["coverage"]
    assert coverage["comparedCount"] == 1
    assert not coverage["complete"]
    assert coverage["missingPairs"][0]["method"] == "RT"
    assert facts["r39"]["sourceValidation"]["procedureReference"]["result"] == "evidence_insufficient"
    assert state == before
    if known_failure:
        from test_r39_node_plan import execute

        node = execute(state, review)
        reference = next(tool for item in node["atomicResults"] for tool in item["toolResults"]
                         if tool["toolName"] == "evaluate_r39_procedure_reference")
        assert reference["result"] == "failed"
        # The node-wide grounding gate remains authoritative; isolating a pair
        # must not bypass that gate or suppress its unresolved-source warning.
        gate = next(item for item in node["atomicResults"] if item.get("resultRole") == "evidence_gate")
        assert node["result"] == ("failed" if gate["result"] == "passed" else "evidence_insufficient")
    rows.reverse()
    _, reversed_output = evaluate(state, review, "evaluate_r39_procedure_reference")
    assert reversed_output["result"] == output["result"]
    assert reversed_output["facts"]["coverage"] == coverage


@pytest.mark.parametrize("schema", ["ndt_reference_inventory", "ndt_reference_members"])
def test_untrustworthy_shared_inventory_still_blocks_every_pair(schema):
    state, review = fixture()
    table = next(table for parse in state["ocr_parse_results"] for table in parse["tables"]
                 if table["businessSchema"] == schema)
    table["normalizedRows"][0]["confidence"] = .1
    state["ocr_parse_results"][2]["tables"][0]["normalizedRows"][0]["procedureVersion"] = "A"
    facts, output = evaluate(state, review, "evaluate_r39_procedure_reference")
    assert "procedureReference" not in facts["r39"]
    assert output["result"] == "evidence_insufficient"


def test_unreliable_failure_is_not_reported_as_known_failure():
    state, review = fixture()
    rows = state["ocr_parse_results"][2]["tables"][0]["normalizedRows"]
    rows[1].update(confidence=.1, procedureVersion="A")
    _, output = evaluate(state, review, "evaluate_r39_procedure_reference")
    assert output["result"] == "evidence_insufficient"
    assert output["facts"]["coverage"]["comparedCount"] == 1
