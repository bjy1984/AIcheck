from copy import deepcopy

import pytest
from test_r39_facts import evaluate
from test_r39_reference import arguments, fixture, run


def body():
    first = arguments()
    second = deepcopy(first)
    for record in [second["scope"], second["basis"], second["instructionReference"], second["procedureIdentity"]]:
        record["method"] = "RT"
    refs = deepcopy(first["basis"]["evidenceRefs"])
    return {"projectId": "P1", "inventory": {"projectId": "P1", "complete": True, "evidenceRefs": refs,
        "members": [{**pair["scope"], "evidenceRefs": refs} for pair in (first, second)]},
        "referencePairs": [first, second]}


@pytest.mark.parametrize("case,expected", [("pass", "passed"), ("fail", "failed"), ("missing", "evidence_insufficient"),
    ("na", "not_applicable"), ("fail_missing", "failed"), ("partial_na", "passed")])
def test_complete_pair_inventory_four_states(case, expected):
    value = body()
    if case in {"fail", "fail_missing"}:
        value["referencePairs"][0]["procedureIdentity"]["procedureVersion"] = "A"
    if case in {"missing", "fail_missing"}:
        value["referencePairs"].pop()
    if case in {"na", "partial_na"}:
        value["referencePairs"][0]["basis"]["applicable"] = False
    if case == "na":
        value["referencePairs"][1]["basis"]["applicable"] = False
    before = deepcopy(value)
    result = run(value)
    assert result["result"] == expected
    assert result["facts"]["wholeRuleAcceptance"] == "not_evaluated"
    assert result["facts"]["coverage"]["requiredCount"] == 2
    assert len(result["facts"]["coverage"]["missingPairs"]) == (1 if "missing" in case else 0)
    assert value == before


@pytest.mark.parametrize("case", ["missing_inventory", "partial_inventory", "no_refs", "duplicate_member", "other_project",
    "duplicate_pair", "unlisted_pair", "nested", "bad_scope", "missing_revision"])
def test_inventory_never_hides_unknown_or_ambiguous_pairs(case):
    value = body()
    if case == "missing_inventory": value["inventory"] = None
    elif case == "partial_inventory": value["inventory"]["complete"] = False
    elif case == "no_refs": value["inventory"]["members"][0]["evidenceRefs"] = []
    elif case == "duplicate_member": value["inventory"]["members"] *= 2
    elif case == "other_project": value["inventory"]["members"][0]["projectId"] = "OTHER"
    elif case == "duplicate_pair": value["referencePairs"].append(deepcopy(value["referencePairs"][0]))
    elif case == "unlisted_pair": value["referencePairs"][0]["scope"]["method"] = "MT"
    elif case == "nested": value["referencePairs"][0]["inventory"] = {}
    elif case == "bad_scope": value["referencePairs"][0]["scope"] = []
    else: value["referencePairs"][0]["procedureIdentity"].pop("procedureVersion")
    assert run(value)["result"] == "evidence_insufficient"
    assert not run(value)["facts"]["coverage"]["complete"]


def test_known_difference_survives_invalid_other_pair_without_row_order_dependency():
    value = body()
    value["referencePairs"][0]["procedureIdentity"]["procedureVersion"] = "A"
    value["referencePairs"][1] = {"scope": []}
    forward = run(value)
    value["referencePairs"].reverse()
    reverse = run(value)
    for key in ("result", "facts", "evidenceRefs"):
        assert reverse[key] == forward[key]
    assert forward["result"] == "failed"
    assert len(forward["facts"]["coverage"]["missingPairs"]) == 1


def inventory_fixture():
    state, review = fixture()
    source = state["ocr_parse_results"][0]
    source["tables"].extend([
        {"tableId": "inventory", "businessSchema": "ndt_reference_inventory", "pageNo": 2,
         "structureConfidence": .95, "contentMarkdown": "Synthetic reference source",
         "normalizedRows": [{"projectId": "P1", "complete": True}]},
        {"tableId": "members", "businessSchema": "ndt_reference_members", "pageNo": 2,
         "structureConfidence": .95, "contentMarkdown": "Synthetic reference source",
         "normalizedRows": [{**arguments()["scope"]}]}])
    return state, review


@pytest.mark.parametrize("case,expected", [("pass", "passed"), ("missing", "evidence_insufficient"),
    ("low_confidence", "evidence_insufficient"), ("duplicate", "evidence_insufficient"), ("fail", "failed")])
def test_inventory_sources_flow_through_real_builder_and_tool(case, expected):
    state, review = inventory_fixture()
    if case == "missing":
        member = deepcopy(state["ocr_parse_results"][0]["tables"][-1]["normalizedRows"][0])
        member["method"] = "RT"
        state["ocr_parse_results"][0]["tables"][-1]["normalizedRows"].append(member)
    elif case == "low_confidence": state["ocr_parse_results"][0]["tables"][-2]["structureConfidence"] = .1
    elif case == "duplicate": state["ocr_parse_results"][2]["tables"][0]["normalizedRows"] *= 2
    elif case == "fail": state["ocr_parse_results"][2]["tables"][0]["normalizedRows"][0]["procedureVersion"] = "A"
    before = deepcopy(state)
    _, output = evaluate(state, review, "evaluate_r39_procedure_reference")
    assert output["result"] == expected, output
    assert state == before
    if case == "pass":
        assert output["facts"]["coverage"]["complete"] is True
        assert output["evidenceRefs"]


def test_unlisted_extra_pair_cannot_leave_coverage_marked_complete():
    value = body()
    extra = deepcopy(value["referencePairs"][0])
    extra["scope"]["method"] = "MT"
    value["referencePairs"].append(extra)
    result = run(value)
    assert result["result"] == "evidence_insufficient"
    assert not result["facts"]["coverage"]["complete"]


def test_two_sourced_pairs_are_both_compared():
    state, review = inventory_fixture()
    for parse in state["ocr_parse_results"]:
        for table in parse["tables"]:
            if table["businessSchema"] in {"ndt_reference_members", "ndt_reference_context", "ndt_reference_basis", "ndt_instruction_reference", "ndt_procedure_identity"}:
                extra = deepcopy(table["normalizedRows"][0])
                extra["method"] = "RT"
                table["normalizedRows"].append(extra)
    _, output = evaluate(state, review, "evaluate_r39_procedure_reference")
    assert output["result"] == "passed", output
    assert output["facts"]["coverage"]["requiredCount"] == 2
    assert output["facts"]["coverage"]["comparedCount"] == 2
    assert output["facts"]["coverage"]["complete"]


def test_compiled_node_plan_consumes_inventory_and_keeps_full_rule_gate():
    from test_r39_node_plan import execute

    state, review = inventory_fixture()
    output = execute(state, review)
    tool = next(item for item in output["atomicResults"][0]["toolResults"]
                if item["toolName"] == "evaluate_r39_procedure_reference")
    assert tool["facts"]["coverage"]["complete"] is True
    assert tool["facts"]["scope"] == "declared_complete_reference_pair_inventory"
    assert output["result"] == "evidence_insufficient"


@pytest.mark.parametrize("case", ["duplicate", "missing", "unlisted", "malformed"])
@pytest.mark.parametrize("known_failure", [False, True])
def test_builder_preserves_independent_pairs_when_other_rows_are_invalid(case, known_failure):
    state, review = inventory_fixture()
    for parse in state["ocr_parse_results"]:
        for table in parse["tables"]:
            if table["businessSchema"] in {"ndt_reference_members", "ndt_reference_context", "ndt_reference_basis", "ndt_instruction_reference", "ndt_procedure_identity"}:
                extra = deepcopy(table["normalizedRows"][0])
                extra["method"] = "RT"
                table["normalizedRows"].append(extra)
    identities = state["ocr_parse_results"][2]["tables"][0]["normalizedRows"]
    if known_failure:
        identities[0]["procedureVersion"] = "A"
    if case == "duplicate":
        identities.append(deepcopy(identities[1]))
    elif case == "missing":
        identities.pop()
    elif case == "unlisted":
        identities[1]["method"] = "MT"
    else:
        identities[1].pop("method")
    before = deepcopy(state)
    _, forward = evaluate(state, review, "evaluate_r39_procedure_reference")
    assert forward["result"] == ("failed" if known_failure else "evidence_insufficient"), forward
    assert forward["facts"]["coverage"]["comparedCount"] == 1
    assert forward["facts"]["coverage"]["missingPairs"][0]["method"] == "RT"
    assert not forward["facts"]["coverage"]["complete"]
    assert state == before
    if known_failure:
        from test_r39_node_plan import execute
        assert execute(state, review)["result"] == "failed"
    for parse in state["ocr_parse_results"]:
        for table in parse["tables"]:
            table["normalizedRows"].reverse()
    _, reverse = evaluate(state, review, "evaluate_r39_procedure_reference")
    assert reverse["result"] == forward["result"]
    assert reverse["facts"]["coverage"] == forward["facts"]["coverage"]
    a, b = forward["facts"]["pairResults"][0], reverse["facts"]["pairResults"][0]
    assert a["pairScope"] == b["pairScope"]
    assert a["checks"] == b["checks"]
    # Source row positions legitimately change; every citation must now point
    # at the corresponding UT record in the rearranged source, not the old row.
    for ref in b["evidenceRefs"]:
        table = next(table for parse in state["ocr_parse_results"]
                     if parse["documentVersionId"] == ref["documentVersionId"]
                     for table in parse["tables"] if table["tableId"] == ref["tableId"])
        assert table["normalizedRows"][ref["rowIndex"]]["method"] == "UT"
