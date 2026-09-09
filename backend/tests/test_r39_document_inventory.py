from copy import deepcopy

import pytest
from test_r39_content import arguments, run
from test_r39_content_facts import fixture as single_fixture
from test_r39_facts import evaluate


def bodies():
    instruction, procedure = arguments(), arguments("procedure")
    records = [procedure["scope"], procedure["basis"], procedure["contentInventory"], *procedure["contentInventory"]["fields"]]
    for record in records:
        record.update(documentId="PROC1", documentVersionId="PV1")
        for ref in record.get("evidenceRefs", []):
            if ref["documentVersionId"] == "DV1": ref["documentVersionId"] = "PV1"
    return [instruction, procedure]


def body():
    documents = bodies()
    refs = deepcopy(documents[0]["basis"]["evidenceRefs"])
    return {"projectId": "P1", "inventory": {"projectId": "P1", "complete": True, "evidenceRefs": refs,
        "members": [{**document["scope"], "evidenceRefs": deepcopy(refs)} for document in documents]}, "documents": documents}


@pytest.mark.parametrize("case,expected", [("pass", "passed"), ("fail", "failed"), ("missing", "evidence_insufficient"),
    ("na", "not_applicable"), ("partial_na", "passed"), ("fail_missing", "failed")])
def test_all_documents_four_states(case, expected):
    value = body()
    if case in {"fail", "fail_missing"}:
        value["documents"][0]["contentInventory"]["fields"][0].update(presence="absent", value=None)
    if case in {"missing", "fail_missing"}: value["documents"].pop()
    if case in {"na", "partial_na"}: value["documents"][0]["basis"]["applicable"] = False
    if case == "na": value["documents"][1]["basis"]["applicable"] = False
    before = deepcopy(value)
    output = run(value)
    assert output["result"] == expected
    assert output["facts"]["coverage"]["requiredCount"] == 2
    assert output["facts"]["wholeRuleAcceptance"] == "not_evaluated"
    assert value == before
    value["documents"].reverse()
    reversed_output = run(value)
    for key in ("result", "facts", "evidenceRefs", "checks"):
        assert reversed_output[key] == output[key]


@pytest.mark.parametrize("case", ["no_inventory", "incomplete", "no_refs", "duplicate_member", "wrong_project",
    "duplicate_document", "unlisted", "nested", "wrong_kind", "missing_fields"])
def test_incomplete_or_ambiguous_inventory_cannot_pass(case):
    value = body()
    if case == "no_inventory": value["inventory"] = None
    elif case == "incomplete": value["inventory"]["complete"] = False
    elif case == "no_refs": value["inventory"]["members"][0]["evidenceRefs"] = []
    elif case == "duplicate_member": value["inventory"]["members"] *= 2
    elif case == "wrong_project": value["inventory"]["projectId"] = "OTHER"
    elif case == "duplicate_document": value["documents"].append(deepcopy(value["documents"][0]))
    elif case == "unlisted": value["documents"][0]["scope"]["documentId"] = "OTHER"
    elif case == "nested": value["documents"][0]["inventory"] = {}
    elif case == "wrong_kind": value["inventory"]["members"][0]["documentKind"] = "unknown"
    else: value["documents"][0]["contentInventory"]["fields"] = []
    output = run(value)
    assert output["result"] == "evidence_insufficient"
    assert not output["facts"]["coverage"]["complete"]


def fixture():
    state, review = single_fixture()
    documents = bodies()
    procedure = documents[1]
    state["documents"].append({"id": "PROC1", "projectId": "P1", "tenantId": "T1"})
    state["versions"].append({"id": "PV1", "documentId": "PROC1", "tenantId": "T1"})
    state["ocr_parse_results"].append({"documentVersionId": "PV1", "tenantId": "T1", "tables": []})
    review["inputDocumentVersionIds"].append("PV1")

    def table(schema, records):
        rows = deepcopy(records)
        for row in rows:
            if "documentVersionId" in row: row["reviewedDocumentVersionId"] = row.pop("documentVersionId")
        return {"businessSchema": schema, "tableId": schema, "pageNo": 2, "structureConfidence": .95,
                "contentMarkdown": "Synthetic document inventory source", "normalizedRows": rows}

    state["ocr_parse_results"][0]["tables"].extend([
        table("ndt_content_document_inventory", [{"projectId": "P1", "complete": True}]),
        table("ndt_content_document_members", [document["scope"] for document in documents]),
        table("ndt_content_basis", [procedure["basis"]])])
    state["ocr_parse_results"][2]["tables"].extend([
        table("ndt_content_context", [procedure["scope"]]),
        table("ndt_content_inventory", [procedure["contentInventory"]]),
        table("ndt_content_fields", procedure["contentInventory"]["fields"])])
    return state, review


@pytest.mark.parametrize("case", ["pass", "duplicate", "missing", "unlisted", "low_confidence", "wrong_source_version"])
@pytest.mark.parametrize("known_failure", [False, True])
def test_real_builder_keeps_each_document_scoped_and_independent(case, known_failure):
    state, review = fixture()
    if known_failure:
        state["ocr_parse_results"][1]["tables"][-1]["normalizedRows"][0].update(presence="absent", value=None)
    tables = state["ocr_parse_results"][2]["tables"]
    if case == "duplicate": tables[0]["normalizedRows"] *= 2
    elif case == "missing": tables.pop(0)
    elif case == "unlisted": tables[0]["normalizedRows"][0]["documentId"] = "OTHER"
    elif case == "low_confidence": tables[2]["normalizedRows"][0]["confidence"] = .2
    elif case == "wrong_source_version": state["ocr_parse_results"][0]["tables"].append(tables.pop())
    before = deepcopy(state)
    facts, output = evaluate(state, review, "evaluate_r39_document_content")
    assert output["result"] == ("failed" if known_failure else "passed" if case == "pass" else "evidence_insufficient"), output
    assert output["facts"]["coverage"]["requiredCount"] == 2
    assert output["facts"]["coverage"]["complete"] is (case == "pass")
    if case in {"duplicate", "missing", "unlisted", "low_confidence"}:
        assert output["facts"]["coverage"]["missingDocuments"][0]["documentId"] == "PROC1"
    assert facts["r39"]["sourceRecords"]
    assert state == before
    from test_r39_node_plan import execute

    node = execute(state, review)
    tool = next(tool for item in node["atomicResults"] for tool in item["toolResults"] if tool["toolName"] == "evaluate_r39_document_content")
    assert tool["result"] == output["result"]
    if not known_failure: assert node["result"] == "evidence_insufficient"


@pytest.mark.parametrize("schema", ["ndt_content_document_inventory", "ndt_content_document_members"])
def test_shared_inventory_source_failure_blocks_all_documents(schema):
    state, review = fixture()
    table = next(table for parse in state["ocr_parse_results"] for table in parse["tables"] if table["businessSchema"] == schema)
    table["structureConfidence"] = .1
    facts, output = evaluate(state, review, "evaluate_r39_document_content")
    assert "documentContent" not in facts["r39"]
    assert output["result"] == "evidence_insufficient"
