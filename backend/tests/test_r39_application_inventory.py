from copy import deepcopy

import pytest
from test_r39_facts import evaluate
from test_r39_facts import fixture as single_fixture
from test_r39_tools import arguments, run


def body():
    first = arguments()
    second = deepcopy(first)
    for record in (second["scope"], second["basis"], second["application"], second["validation"]):
        record.update(objectId="W2", eventId="EVENT2")
    refs = deepcopy(first["basis"]["evidenceRefs"])
    return {"projectId": "P1", "inventory": {"projectId": "P1", "complete": True, "evidenceRefs": refs,
        "members": [{**item["scope"], "evidenceRefs": deepcopy(refs)} for item in (first, second)]}, "applications": [first, second]}


@pytest.mark.parametrize("case,expected", [("pass", "passed"), ("fail", "failed"), ("missing", "evidence_insufficient"),
    ("na", "not_applicable"), ("partial_na", "passed"), ("failure_and_missing", "failed")])
def test_all_application_events_four_states(case, expected):
    value = body()
    if case in {"fail", "failure_and_missing"}: value["applications"][0]["validation"]["performed"] = False
    if case in {"missing", "failure_and_missing"}: value["applications"].pop()
    if case in {"na", "partial_na"}: value["applications"][0]["application"]["firstUse"] = False
    if case == "na": value["applications"][1]["application"]["firstUse"] = False
    before = deepcopy(value)
    output = run(value)
    assert output["result"] == expected
    assert output["facts"]["coverage"]["requiredCount"] == 2
    assert output["facts"]["validationEffectiveness"] == "not_evaluated"
    assert value == before
    value["applications"].reverse()
    reversed_output = run(value)
    for key in ("result", "facts", "evidenceRefs"):
        assert reversed_output[key] == output[key]


@pytest.mark.parametrize("case", ["no_inventory", "not_complete", "no_refs", "duplicate_member", "other_project",
    "duplicate_event", "unlisted", "nested", "reused_validation", "missing_validation"])
def test_missing_or_cross_event_evidence_cannot_pass(case):
    value = body()
    if case == "no_inventory": value["inventory"] = None
    elif case == "not_complete": value["inventory"]["complete"] = False
    elif case == "no_refs": value["inventory"]["members"][0]["evidenceRefs"] = []
    elif case == "duplicate_member": value["inventory"]["members"] *= 2
    elif case == "other_project": value["inventory"]["members"][0]["projectId"] = "OTHER"
    elif case == "duplicate_event": value["applications"].append(deepcopy(value["applications"][0]))
    elif case == "unlisted": value["applications"][1]["scope"]["eventId"] = "OTHER"
    elif case == "nested": value["applications"][1]["inventory"] = {}
    elif case == "reused_validation": value["applications"][1]["validation"] = deepcopy(value["applications"][0]["validation"])
    else: value["applications"][1].pop("validation")
    output = run(value)
    assert output["result"] == "evidence_insufficient"
    assert not output["facts"]["coverage"]["complete"]


def fixture():
    state, review = single_fixture()
    for parse in state["ocr_parse_results"]:
        for table in parse["tables"]:
            if table["businessSchema"] in {"ndt_instruction_application", "ndt_first_use_basis", "ndt_first_use_validation"}:
                extra = deepcopy(table["normalizedRows"][0])
                extra.update(objectId="W2", eventId="EVENT2")
                table["normalizedRows"].append(extra)
    value = body()
    for schema, records in (("ndt_application_inventory", [{"projectId": "P1", "complete": True}]),
                            ("ndt_application_members", value["inventory"]["members"])):
        state["ocr_parse_results"][0]["tables"].append({"tableId": schema, "businessSchema": schema,
            "pageNo": 2, "structureConfidence": .95, "contentMarkdown": "Synthetic application inventory",
            "normalizedRows": deepcopy(records)})
    return state, review


@pytest.mark.parametrize("case", ["pass", "duplicate", "missing", "unknown_event", "low_confidence", "unknown_identity"])
@pytest.mark.parametrize("known_failure", [False, True])
def test_source_to_node_keeps_independent_events(case, known_failure):
    state, review = fixture()
    table = next(table for parse in state["ocr_parse_results"] for table in parse["tables"]
                 if table["businessSchema"] == "ndt_first_use_validation")
    rows = table["normalizedRows"]
    if known_failure: rows[0]["performed"] = False
    if case == "duplicate": rows.append(deepcopy(rows[1]))
    elif case == "missing": rows.pop()
    elif case == "unknown_event": rows[1]["eventId"] = "OTHER"
    elif case == "low_confidence": rows[1]["confidence"] = .1
    elif case == "unknown_identity": rows[1].pop("objectId")
    before = deepcopy(state)
    _, output = evaluate(state, review, "evaluate_r39_first_use_validation")
    assert output["result"] == ("failed" if known_failure else "passed" if case == "pass" else "evidence_insufficient"), output
    assert output["facts"]["coverage"]["requiredCount"] == 2
    assert output["facts"]["coverage"]["complete"] is (case == "pass")
    assert state == before
    from test_r39_node_plan import execute

    node = execute(state, review)
    tool = next(tool for item in node["atomicResults"] for tool in item["toolResults"]
                if tool["toolName"] == "evaluate_r39_first_use_validation")
    assert tool["result"] == output["result"]
    if not known_failure: assert node["result"] == "evidence_insufficient"


@pytest.mark.parametrize("schema", ["ndt_application_inventory", "ndt_application_members"])
def test_shared_inventory_low_confidence_blocks_all_events(schema):
    state, review = fixture()
    table = next(table for parse in state["ocr_parse_results"] for table in parse["tables"] if table["businessSchema"] == schema)
    table["structureConfidence"] = .1
    facts, output = evaluate(state, review, "evaluate_r39_first_use_validation")
    assert "firstUseValidation" not in facts["r39"]
    assert output["result"] == "evidence_insufficient"
