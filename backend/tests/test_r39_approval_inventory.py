from copy import deepcopy

import pytest
from test_r39_approval import arguments, run
from test_r39_facts import evaluate
from test_r39_facts import fixture as single_fixture


def body():
    first = arguments()
    second = deepcopy(first)
    for record in [second["scope"], second["requirements"], second["signatureInventory"], *second["signatureInventory"]["signatures"]]:
        record.update(documentVersionId="DV2", approvalCycleId="CYCLE2")
        for ref in record.get("evidenceRefs", []):
            if ref["documentVersionId"] == "DV1": ref["documentVersionId"] = "DV2"
    refs = deepcopy(first["requirements"]["evidenceRefs"])
    return {"projectId": "P1", "inventory": {"projectId": "P1", "complete": True, "evidenceRefs": refs,
        "members": [{**item["scope"], "evidenceRefs": deepcopy(refs)} for item in (first, second)]}, "approvalCycles": [first, second]}


def make_optional(cycle):
    for step in cycle["requirements"]["steps"]:
        step.update(required=False, after=[], distinctFrom=[])


@pytest.mark.parametrize("case,expected", [("pass", "passed"), ("fail", "failed"), ("missing", "evidence_insufficient"),
    ("na", "not_applicable"), ("partial_na", "passed"), ("failure_and_missing", "failed")])
def test_all_approval_cycles_four_states(case, expected):
    value = body()
    if case in {"fail", "failure_and_missing"}: value["approvalCycles"][0]["signatureInventory"]["signatures"][0]["approved"] = False
    if case in {"missing", "failure_and_missing"}: value["approvalCycles"].pop()
    if case in {"na", "partial_na"}: make_optional(value["approvalCycles"][0])
    if case == "na": make_optional(value["approvalCycles"][1])
    before = deepcopy(value)
    output = run(value)
    assert output["result"] == expected, output
    assert output["facts"]["coverage"]["requiredCount"] == 2
    assert output["facts"]["wholeRuleAcceptance"] == "not_evaluated"
    assert value == before
    value["approvalCycles"].reverse()
    reversed_output = run(value)
    for key in ("result", "facts", "evidenceRefs"):
        assert reversed_output[key] == output[key]


@pytest.mark.parametrize("case", ["no_inventory", "incomplete", "no_refs", "duplicate_member", "other_project",
    "duplicate_cycle", "unlisted", "nested", "old_signatures", "missing_signatures"])
def test_old_or_ambiguous_approvals_cannot_pass(case):
    value = body()
    if case == "no_inventory": value["inventory"] = None
    elif case == "incomplete": value["inventory"]["complete"] = False
    elif case == "no_refs": value["inventory"]["members"][0]["evidenceRefs"] = []
    elif case == "duplicate_member": value["inventory"]["members"] *= 2
    elif case == "other_project": value["inventory"]["members"][0]["projectId"] = "OTHER"
    elif case == "duplicate_cycle": value["approvalCycles"].append(deepcopy(value["approvalCycles"][0]))
    elif case == "unlisted": value["approvalCycles"][1]["scope"]["approvalCycleId"] = "OTHER"
    elif case == "nested": value["approvalCycles"][1]["inventory"] = {}
    elif case == "old_signatures": value["approvalCycles"][1]["signatureInventory"]["signatures"] = deepcopy(value["approvalCycles"][0]["signatureInventory"]["signatures"])
    else: value["approvalCycles"][1]["signatureInventory"]["signatures"] = []
    output = run(value)
    assert output["result"] == "evidence_insufficient"
    assert not output["facts"]["coverage"]["complete"]


def fixture():
    state, review = single_fixture()
    state["versions"].append({"id": "DV2", "documentId": "DOC1", "tenantId": "T1"})
    review["inputDocumentVersionIds"].append("DV2")
    new_tables = []
    for parse in state["ocr_parse_results"]:
        additions = []
        for table in parse["tables"]:
            if table["businessSchema"] in {"ndt_approval_context", "ndt_approval_requirements", "ndt_approval_steps", "ndt_signature_inventory", "ndt_approval_signatures"}:
                extra = deepcopy(table)
                for row in extra["normalizedRows"]:
                    row.update(reviewedDocumentVersionId="DV2", approvalCycleId="CYCLE2")
                if parse["documentVersionId"] == "DV1": new_tables.append(extra)
                else: additions.append(extra)
        parse["tables"].extend(additions)
    state["ocr_parse_results"].append({"documentVersionId": "DV2", "tenantId": "T1", "tables": new_tables})
    value = body()
    for schema, records in (("ndt_approval_cycle_inventory", [{"projectId": "P1", "complete": True}]),
                            ("ndt_approval_cycle_members", value["inventory"]["members"])):
        rows = deepcopy(records)
        for row in rows:
            if "documentVersionId" in row: row["reviewedDocumentVersionId"] = row.pop("documentVersionId")
        state["ocr_parse_results"][0]["tables"].append({"tableId": schema, "businessSchema": schema,
            "pageNo": 2, "structureConfidence": .95, "contentMarkdown": "Synthetic approval inventory", "normalizedRows": rows})
    return state, review


@pytest.mark.parametrize("case", ["pass", "duplicate", "missing", "wrong_cycle", "low_confidence", "old_source"])
@pytest.mark.parametrize("known_failure", [False, True])
def test_scoped_sources_flow_through_node_without_erasing_other_cycles(case, known_failure):
    state, review = fixture()
    if known_failure:
        next(table for table in state["ocr_parse_results"][1]["tables"] if table["businessSchema"] == "ndt_approval_signatures")["normalizedRows"][0]["approved"] = False
    tables = state["ocr_parse_results"][2]["tables"]
    context = next(table for table in tables if table["businessSchema"] == "ndt_approval_context")
    signatures = next(table for table in tables if table["businessSchema"] == "ndt_approval_signatures")
    if case == "duplicate": context["normalizedRows"] *= 2
    elif case == "missing": tables.remove(context)
    elif case == "wrong_cycle": signatures["normalizedRows"][0]["approvalCycleId"] = "OTHER"
    elif case == "low_confidence": signatures["structureConfidence"] = .1
    elif case == "old_source":
        tables.remove(signatures)
        state["ocr_parse_results"][1]["tables"].append(signatures)
    before = deepcopy(state)
    _, output = evaluate(state, review, "evaluate_r39_approval_chain")
    assert output["result"] == ("failed" if known_failure else "passed" if case == "pass" else "evidence_insufficient"), output
    assert output["facts"]["coverage"]["complete"] is (case == "pass")
    assert state == before
    from test_r39_node_plan import execute

    node = execute(state, review)
    tool = next(tool for item in node["atomicResults"] for tool in item["toolResults"] if tool["toolName"] == "evaluate_r39_approval_chain")
    assert tool["result"] == output["result"]
    if not known_failure: assert node["result"] == "evidence_insufficient"


@pytest.mark.parametrize("schema", ["ndt_approval_cycle_inventory", "ndt_approval_cycle_members"])
def test_shared_inventory_gate_blocks_all_cycles(schema):
    state, review = fixture()
    table = next(table for parse in state["ocr_parse_results"] for table in parse["tables"] if table["businessSchema"] == schema)
    table["structureConfidence"] = .1
    facts, output = evaluate(state, review, "evaluate_r39_approval_chain")
    assert "approvalChain" not in facts["r39"]
    assert output["result"] == "evidence_insufficient"


def test_separate_approval_register_can_record_the_explicit_reviewed_revision():
    state, review = fixture()
    tables = state["ocr_parse_results"][2]["tables"]
    signatures = next(table for table in tables if table["businessSchema"] == "ndt_approval_signatures")
    tables.remove(signatures)
    state["ocr_parse_results"][0]["tables"].append(signatures)
    assert evaluate(state, review, "evaluate_r39_approval_chain")[1]["result"] == "passed"
